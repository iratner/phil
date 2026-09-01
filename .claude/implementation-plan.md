# Plan: Phil Level Minimum-Moves Solver

## Context

The Phil game board has two layers — a floor (bottom) and a movable-block layer (top). A player slides top-level blocks to open a walkable path for Phil (who never moves) to reach a GOAL cell. This solver takes a level expressed as two 2D JSON arrays and uses BFS to find the fewest player moves required to win.

The solver lives in `phil-server-fapi-leveler/` and is usable both as a FastAPI endpoint and as a standalone CLI script.

---

## Updated `BlockType` Enum

Extend `app/models/level.py` — the `BlockType` enum becomes the single source of truth for both the Level model and the solver.

```python
class BlockType(str, Enum):
    # Both layers
    EMPTY = "empty"          # empty cell: Phil can walk (top) / solid walkable floor (bottom)
    STATIC = "static"        # immovable iron: can't be moved, Phil can't cross

    # Top layer
    PHIL = "phil"            # Phil's starting position (exactly one per level)
    GOAL = "goal"            # Win target (exactly one per level)
    MOVE_ONE = "move_one"    # Stone: slides exactly 1 space
    ICE = "ice"              # Ice block: slides 1 space; slippery when it fills a hole
    BOUNCE = "bounce"        # Bumper: can't be directly moved; bumps opposite-side blocks
    SPIKE = "spike"          # Cube of up to 5 spiked faces; a can_destroy_spike block clears the struck face

    # Bottom layer only
    HOLE = "hole"            # Pit — Phil can't cross; top blocks fall through
    QUICKSAND = "quicksand"  # Needs 2 top blocks to fall in before Phil can cross
    ICE_FLOOR = "ice_floor"  # Ice as a floor surface (initially placed; makes blocks slide)
    SPIKE_FLOOR = "spike_floor"  # Ground-level spike; only its top face is exposed/destroyable
```

Cells may be a bare `BlockType` string or a `BlockSpec` object
(`{type, can_destroy_spike?, is_destroyed_by_spike?, spiked_faces?}`).  Movable
blocks default `can_destroy_spike=true`, `is_destroyed_by_spike=true`; a `SPIKE`
defaults to all five faces.  See `.claude/game-mechanics.md` for full semantics.

Update the `Level` model's fields to `list[list[BlockType]]` (EMPTY replaces `null`). JSON serialization stays unchanged since `BlockType` is a `str` enum.

---

## Docstring Standard

Every function in the solver module must have a docstring that explains:
- What the function does
- The exact game mechanic it encodes (quoting the rule where useful)
- Its parameters and return value
- Any edge cases or invariants callers must uphold

This ensures the solver remains readable as the game rules evolve.

---

## Files to Create / Modify

### New: `app/solver/__init__.py`
Empty package marker.

### New: `app/solver/solver.py`
Core BFS solver. Key pieces:

**`GameState` (NamedTuple)**
```
top: tuple[tuple[Cell, ...], ...]               # Cells carry type + spike faces + block props
holes_filled: frozenset[tuple[int,int]]         # holes plugged by non-ice blocks (walkable)
ice_holes_filled: frozenset[tuple[int,int]]     # holes plugged by ice blocks (slippery, walkable)
quicksand_counts: tuple[tuple[tuple[int,int],int], ...] # sorted ((r,c), fill_count) pairs
floor_spikes_destroyed: frozenset[tuple[int,int]]      # SPIKE_FLOOR cells with a cleared top face
```
`bottom` is constant (read-only), so it is not part of the mutable state.
Each `Cell` is a NamedTuple `(type, can_destroy_spike, is_destroyed_by_spike,
spiked_faces)`; properties travel with the block as it moves.

**`find_phil_and_goal(top)`** — scan for `"phil"` and `"goal"` cell positions.

**`is_walkable(row, col, state, bottom)`**
- Top cell must be `BlockType.EMPTY`, `BlockType.PHIL`, or `BlockType.GOAL`
- Bottom cell must not be `BlockType.HOLE` (unless in `holes_filled` or `ice_holes_filled`)
- Bottom cell must not be `BlockType.STATIC`
- Bottom cell `BlockType.QUICKSAND` is only walkable when its count in `quicksand_counts` reaches 2
- Bottom cell `BlockType.SPIKE_FLOOR` is only walkable when in `floor_spikes_destroyed`
- No live spike face of an adjacent `SPIKE` may guard the cell

**`phil_can_reach_goal(state, phil_pos, goal_pos, bottom)`** — BFS/flood-fill from Phil's position; returns `True` if GOAL is reachable.

**`compute_destination(block_pos, direction, top, bottom, holes_filled) -> tuple`**
Returns the actual landing position for a moving block, accounting for ice-filled-hole sliding:

1. Compute first step = block_pos + direction delta
2. Spike encounters: a `SPIKE` whose struck face is live returns `("SPIKE", r, c)`; an intact `SPIKE_FLOOR` returns `("FLOOR_SPIKE", r, c)`.  A cleared spike face / any other non-empty top block / `STATIC` floor / out-of-bounds acts as a wall (or illegal on the first step)
3. If first-step floor is an unfilled `"hole"`: return `("FALL", row, col)` — block falls in immediately
4. If first-step floor is an ice-filled hole (`"ice"` in `holes_filled`): enter sliding loop
   - Keep advancing one cell at a time in the same direction
   - Stop (land) when: hitting wall, hitting a top block, hitting iron floor, or reaching non-ice-filled floor
   - If the next cell is an unfilled hole while sliding: return `("FALL", row, col)` at that hole
5. Otherwise return `("LAND", row, col)` at the furthest reachable non-ice cell

**`apply_move(state, block_pos, direction, bottom) -> GameState | None`**
Implements all movement rules in order:

1. Call `compute_destination` to find where the block ends up (accounts for ice-filled sliding and spike encounters, see above)
2. If `"FALL"` into a **hole**: remove block from top; if block type is `"ice"` add to `ice_holes_filled`, else add to `holes_filled`
3. If `"FALL"` into **quicksand**: increment that cell's count in `quicksand_counts`; block is consumed (removed from top). When count reaches 2, the cell becomes walkable (Phil can cross it)
4. If `"LAND"`: place block at destination, then resolve any bumper interaction
5. **Spike collision** (`"SPIKE"`): if `can_destroy_spike`, clear the struck face (a fully de-spiked spike becomes `MOVE_ONE`); the block is consumed if `is_destroyed_by_spike`, else it stops in the cell before the spike
6. **Floor-spike collision** (`"FLOOR_SPIKE"`): same logic against a ground-level spike's top face, recording the cell in `floor_spikes_destroyed`
7. **Bumper interaction**: if the newly landed block is adjacent to a `"bounce"` cell, check the cell directly opposite the bumper on the same axis — if a movable block sits there, bump it one cell further (same direction). The bump is applied via a recursive `apply_move` call
8. Reject if resulting state is identical to input state (no-op)

**`get_valid_moves(state, bottom)`** — yields `(block_pos, direction)` for every movable block (`MOVE_ONE`, `ICE`) in all 4 directions where `apply_move` returns a new (non-identical) state.

**`solve(floor_grid, top_grid, max_depth=20) -> dict`**
```python
def solve(floor_grid, top_grid, max_depth=20):
    # Returns {"min_moves": int, "moves": [...], "solvable": bool}
    # BFS over GameState; visited = set of full GameState tuples
    # Each BFS node: (state, move_index, move_history)
    # Depth limit: max_depth (default 20) to bound search on hard levels
```

### New: `app/routers/solver.py`
FastAPI router with one endpoint:

```
POST /solver/solve
Body: { "floor": [[...]], "top": [[...]], "max_depth": 20 }
Response: { "solvable": bool, "min_moves": int | null, "moves": [...] | null }
```

Pydantic input model `LevelSolveRequest`:
```python
class LevelSolveRequest(BaseModel):
    floor: list[list[Cell]]    # Cell = BlockType | BlockSpec
    top:   list[list[Cell]]
    max_depth: int = 20
```

### Modified: `app/main.py`
Register the solver router:
```python
from app.routers import solver
app.include_router(solver.router, prefix="/solver")
```

### New: `.claude/game-mechanics.md` (repo root — create `.claude/` if absent)
A reference document for Claude capturing all game mechanics as defined in `phil-game-rules.md` and refined in this planning session. Sections:

- **Board structure** — two layers, dimensions, what each layer may contain
- **Phil** — starting position, movement rules, win condition
- **Block types** — one subsection per block (MOVE_ONE, ICE, STATIC, BOUNCE, SPIKE, SPIKE_FLOOR, QUICKSAND) with exact movement/interaction rules, plus per-block properties (can_destroy_spike / is_destroyed_by_spike)
- **Floor types** — EMPTY, HOLE, ICE_FLOOR, STATIC, QUICKSAND and their effect on Phil and top-layer blocks
- **Solver-specific notes** — what constitutes a "move" for BFS purposes, state representation, what the solver does/doesn't compute (no scoring)

### New: `solve_level.py` (root of `phil-server-fapi-leveler/`)
Standalone CLI script:
```
python solve_level.py --floor floor.json --top top.json
python solve_level.py --level level.json   # single file with "floor" and "top" keys
```
Prints JSON result to stdout: `{"solvable": true, "min_moves": 4, "moves": [...]}`

---

## Move Output Format

Each move in the returned `moves` list:
```json
{
  "block_row": 3,
  "block_col": 5,
  "direction": "right"
}
```
Points and move types are live game mechanics only — the solver does not compute or return them.

---

## What's Not in v1 (noted as TODO in code)
- (none currently) — spikes are five-faced and never revive; floor spikes (`SPIKE_FLOOR`) are supported

---

## Verification

1. **Unit test** — hand-craft a 3×3 minimal level (floor all null except one hole, top has one stone block and a GOAL), verify solver returns `min_moves=1`.
2. **CLI test**: `python solve_level.py --level sample_level.json` — confirm JSON output.
3. **API test**: `uvicorn app.main:app --reload --port 8080` then `curl -X POST localhost:8080/solver/solve -H 'Content-Type: application/json' -d @sample_level.json`
4. **Unsolvable level** — a level where the GOAL is fully surrounded by iron blocks should return `{"solvable": false}`.
