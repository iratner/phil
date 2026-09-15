# Phil Level Solver — Architecture Reference

Audience: a coordinator/agent that needs to understand **how level solving is
built** in `python-workspace/phil-leveler-fapi` before delegating or making
changes. This is the *architecture* companion to [`game-mechanics.md`](./game-mechanics.md),
which is the authoritative reference for the game *rules* themselves. When a
rule and this doc seem to disagree, `game-mechanics.md` wins on rules and the
source code wins on structure.

Tooling note: this is a **`uv`-managed** project. Run everything through `uv`
(`uv run pytest`, `uv run python gen-openapi.py`). Bare `python` is not on PATH.

---

## 1. Where things live

| Concern | File |
|---|---|
| Data model (enums + pydantic) | `app/models/level.py` |
| Solver engine (all logic) | `app/solver/solver.py` |
| HTTP entry point | `app/routers/solver.py` (`POST /solver/solve`) |
| Levels CRUD stub | `app/routers/levels.py` (`/levels`, uses `Level`) |
| CLI entry point | `solve_level.py` (repo-local, string input only) |
| OpenAPI dump | `gen-openapi.py` → `openapi.json` |
| Tests | `tests/test_solver.py` (~59 tests, grouped by mechanic) |

The solver is **self-contained in one module** — `app/solver/solver.py` holds
the cell model, `GameState`, every rule helper, and the public `solve()`. There
is no separate rules/state file.

---

## 2. Two "Cell" types — do not confuse them

There are two things named `Cell`, one per layer of the stack:

1. **`Cell` in `app/models/level.py`** — a *type alias*: `Cell = BlockType | BlockSpec`.
   This is the **wire/input** shape. A board cell is either a bare `BlockType`
   string (e.g. `"empty"`) or a `BlockSpec` object carrying per-block config.
2. **`Cell` in `app/solver/solver.py`** — a hashable **`NamedTuple`** used
   *inside* the engine. Fields: `type`, `can_destroy_spike`,
   `is_destroyed_by_spike`, `spiked_faces` (frozenset), `capacity` (int).

The solver imports `BlockSpec`, `BlockType`, `Face` from the model but **not**
the model's `Cell` alias — it defines and uses its own NamedTuple. Input cells
are normalized into the NamedTuple at the boundary (see §4).

### The data model (`app/models/level.py`)

- `BlockType(str, Enum)` — the canonical cell-type enum (12 values; per-layer
  validity is in `game-mechanics.md`).
- `Face(str, Enum)` — `UP/NORTH/SOUTH/EAST/WEST`, the spikeable faces.
- `BlockSpec(BaseModel)` — the structured per-cell config object. It is
  **layer-agnostic**: it configures both top-layer blocks and floor cells.
  Fields (all optional except `type`, `None` = "use type default"):
  `type`, `can_destroy_spike`, `is_destroyed_by_spike`, `spiked_faces`,
  `capacity`. Which fields matter depends on `type` (e.g. `spiked_faces` for
  spikes, `capacity` for quicksand) — irrelevant fields are simply ignored.
- `Level(BaseModel)` — `name`, `created_by`, `board_top`, `board_bottom`, each
  grid typed `list[list[Cell]]`. Note: the `Level` model uses
  `board_top`/`board_bottom`; the solver endpoint uses a **separate**,
  differently-named request model with `floor`/`top` (see §6). They are not
  unified today.

---

## 3. Top vs bottom layer — the key structural asymmetry

- **Top layer** = what the player manipulates and what Phil occupies. It is the
  only thing that changes shape during a move, so it lives *inside* `GameState`
  as an immutable grid of solver-`Cell`s. Per-block config (spike faces, the
  movable flags) rides **on the cell** so it moves with the block automatically
  and is part of the BFS hash.
- **Bottom layer (floor)** = static for the whole search. It is passed around
  **separately** from `GameState` (as the `bottom` argument) precisely because
  it never changes — keeping it out of the state avoids bloating the visited-set
  hash. As of the per-block-config work it is **also a grid of solver-`Cell`s**
  (was previously bare `BlockType`), so floor cells can carry static config such
  as a `QUICKSAND` cell's `capacity`. `BottomGrid = tuple[tuple[Cell, ...], ...]`.
- **Runtime floor changes** (holes filling, quicksand accumulating, floor spikes
  breaking) do *not* mutate the bottom grid. They are recorded as side tables on
  `GameState` and resolved on demand by `_effective_floor` (see §5).

---

## 4. Input normalization pipeline

Raw input (`RawCell = BlockType | BlockSpec | Cell | str`) is converted to the
internal NamedTuple before any logic runs:

- `_to_cell(value)` — the single normalization funnel. Accepts an already-built
  `Cell` (returned as-is), a `BlockSpec` (config read off it), or a bare
  `BlockType`/string. Resolves `None` fields to type-appropriate defaults:
  - `can_destroy_spike` → true for movable types (`MOVE_ONE`/`ICE`), else false
  - `is_destroyed_by_spike` → true
  - `spiked_faces` → all five faces for `SPIKE`, else empty
  - `capacity` → 2 (uniform default so equivalent cells compare equal for hashing)
- `_top_grid_from_lists` / `_bottom_grid_from_lists` — map `_to_cell` across a
  2-D list into an immutable tuple-of-tuples. **Both** layers now go through
  `_to_cell`; the bottom layer no longer discards config.
- `_movable_cell(type)` and `_EMPTY_CELL` — canonical cells used when a
  de-spiked `SPIKE` converts to `MOVE_ONE` and when a block vacates a cell.

**Hashing invariant:** the solver `Cell` (and thus `GameState`) must stay
hashable. Any new config field added to `Cell` must be an **immutable** type
(note `spiked_faces` is a `frozenset`, not a `list`, for exactly this reason).

---

## 5. Core helpers (single responsibilities)

- `_effective_floor(row, col, bottom, holes_filled, ice_holes_filled, quicksand_counts, floor_spikes_destroyed)`
  → the **effective** `BlockType` of a floor cell after runtime changes. This is
  the one place that reconciles the static bottom grid with the mutable side
  tables. Priority: filled hole → `EMPTY`; ice-filled hole → `ICE_FLOOR`;
  quicksand with `fill_count >= cell.capacity` → `EMPTY`; destroyed floor spike →
  `EMPTY`; else original type. **Everyone reads the floor through this**, never
  the raw bottom grid.
- `_is_slippery_floor` — ice-surface test (drives sliding).
- `_cell_blocked_by_spike` — is `(row,col)` guarded by a live face of an
  adjacent top-layer `SPIKE`? (Phil-passability guard.)
- `_is_phil_walkable` — cell-local walkability (top cell + effective floor),
  *excluding* the adjacent-spike guard, which the flood-fill applies separately.
- `_qs_count` / `_qs_increment` — read/update the quicksand fill side table.

---

## 6. Control flow — `solve()`

`solve(floor_grid, top_grid, max_depth=20) -> dict`

1. Normalize both grids (`_bottom_grid_from_lists`, `_top_grid_from_lists`).
2. Build the initial `GameState`; find the single `PHIL` and `GOAL`
   (`_find_phil_and_goal`). Missing either → unsolvable.
3. Early-out: if `_phil_can_reach_goal` already holds → 0 moves.
4. **BFS**: queue of `(state, move_index, history)`, `visited: set[GameState]`.
   Each level of the BFS = one player move, so the first solution found is
   minimal.
   - `_get_valid_moves(state, bottom)` enumerates `(block_pos, direction)` pairs
     for every movable block whose push produces a changed state.
   - `_apply_move(state, block_pos, direction, bottom)` computes the next state
     (or `None` for illegal/no-op).
   - After each move, `_phil_can_reach_goal` (flood-fill from PHIL over
     walkable, non-spike-guarded cells) checks the win condition.
5. Returns `{"solvable": bool, "min_moves": int|None, "moves": [...]|None}`,
   each move `{"block_row", "block_col", "direction"}`.

### Inside a move (`_apply_move`)

1. `_compute_destination` computes where the pushed block ends up, handling
   one-step movement, **ice sliding** (loop until a stop condition), and the
   *geometry* of spike encounters. Returns a tagged result:
   `("LAND"|"FALL"|"SPIKE"|"FLOOR_SPIKE", row, col)` or `None`.
2. Resolve by tag:
   - `FALL` → hole fill (`holes_filled`/`ice_holes_filled`) or quicksand
     increment.
   - `LAND` → place the block, then `_resolve_bumper` (BOUNCE chains recurse
     through `_apply_move`).
   - `SPIKE` → `_resolve_spike_collision` (destroy struck face if able; consume
     block per `is_destroyed_by_spike`; a fully de-spiked spike becomes
     `MOVE_ONE`).
   - `FLOOR_SPIKE` → `_resolve_floor_spike_collision` (same logic vs a
     ground-level spike's top face; records `floor_spikes_destroyed`).
3. No-op rejection: if the new state equals the old one (`_key()` compare),
   return `None`.

### `GameState`

Immutable snapshot, hashable via `_key()`. Fields: `top` (the only shape-
changing part), `holes_filled`, `ice_holes_filled`, `quicksand_counts`,
`floor_spikes_destroyed`. **The bottom grid is deliberately not a field** — it
is constant across the whole search and passed separately.

---

## 7. Entry points

- **HTTP** — `app/routers/solver.py`, `POST /solver/solve`. Request model
  `LevelSolveRequest { floor: list[list[Cell]], top: list[list[Cell]], max_depth }`
  where `Cell` is the model union (so `BlockSpec` config flows straight through).
  Response `SolveResult { solvable, min_moves, moves }`. Grid-validation
  (missing PHIL/GOAL) surfaces from inside the solver.
- **CLI** — `solve_level.py`. Reads a JSON `{floor, top}` (or `--floor/--top`
  files). **Limitation:** its `_parse_grid` accepts **bare strings only** — it
  does not yet understand `BlockSpec` objects. This is the one surface that has
  not been migrated to per-block config.

---

## 8. Extending per-block config (the established pattern)

To add a new configurable knob (top-layer or floor):

1. Add an optional field to `BlockSpec` in `app/models/level.py` (with
   validation, `default=None` meaning "type default").
2. Add a matching field to the solver `Cell` NamedTuple with a **uniform
   immutable default** (so equivalent cells stay equal/hashable).
3. Resolve `None` → default inside `_to_cell`.
4. Read the field where the mechanic lives (e.g. `_effective_floor` for floor
   knobs, the spike/bump resolvers for block knobs).
5. Add tests in `tests/test_solver.py` and regenerate the spec:
   `uv run python gen-openapi.py`.

Because the bottom grid is now config-bearing, **future floor config needs no
new plumbing** and adds **no BFS-hashing cost** (the floor stays static and
outside `GameState`). Quicksand `capacity` is the worked example of this pattern.

---

## 9. Verifying changes

- Tests: `uv run pytest tests/test_solver.py -q` (fast, ~0.1s).
- Regenerate OpenAPI after any model change: `uv run python gen-openapi.py`
  (then confirm the field appears in `openapi.json`).
- Manual CLI (string-only levels): `uv run python solve_level.py --level FILE`.
