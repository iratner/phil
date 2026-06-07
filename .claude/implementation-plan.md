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
    SPIKE = "spike"          # Can't be player-moved; destroys any block that slides into it

    # Bottom layer only
    HOLE = "hole"            # Pit — Phil can't cross; top blocks fall through
    QUICKSAND = "quicksand"  # Needs 2 top blocks to fall in before Phil can cross
    ICE_FLOOR = "ice_floor"  # Ice as a floor surface (initially placed; makes blocks slide)
```

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
top: tuple[tuple[str|None, ...], ...]           # immutable snapshot of top layer
holes_filled: frozenset[tuple[int,int]]         # holes plugged by non-ice blocks (walkable)
ice_holes_filled: frozenset[tuple[int,int]]     # holes plugged by ice blocks (slippery, walkable)
quicksand_counts: tuple[tuple[tuple[int,int],int], ...] # sorted ((r,c), fill_count) pairs
destroyed_spikes: tuple[tuple[int,int,int], ...] # (row, col, destroyed_at_move) triples
```
`bottom` is constant (read-only), so it is not part of the mutable state.

**`find_phil_and_goal(top)`** — scan for `"phil"` and `"goal"` cell positions.

**`is_walkable(row, col, state, bottom, move_index, spike_revival_moves)`**
- Top cell (after applying spike revival for this move_index) must be `BlockType.EMPTY`, `BlockType.PHIL`, or `BlockType.GOAL`
- Bottom cell must not be `BlockType.HOLE` (unless in `holes_filled` or `ice_holes_filled`)
- Bottom cell must not be `BlockType.STATIC`
- Bottom cell `BlockType.QUICKSAND` is only walkable when its count in `quicksand_counts` reaches 2

**`phil_can_reach_goal(state, phil_pos, goal_pos, bottom)`** — BFS/flood-fill from Phil's position; returns `True` if GOAL is reachable.

**`compute_destination(block_pos, direction, top, bottom, holes_filled) -> tuple`**
Returns the actual landing position for a moving block, accounting for ice-filled-hole sliding:

1. Compute first step = block_pos + direction delta
2. Reject (return `None`) if: out-of-bounds, destination top cell is a non-spike block, or destination floor is `"iron"`
3. If first-step floor is an unfilled `"hole"`: return `("FALL", row, col)` — block falls in immediately
4. If first-step floor is an ice-filled hole (`"ice"` in `holes_filled`): enter sliding loop
   - Keep advancing one cell at a time in the same direction
   - Stop (land) when: hitting wall, hitting a top block, hitting iron floor, or reaching non-ice-filled floor
   - If the next cell is an unfilled hole while sliding: return `("FALL", row, col)` at that hole
5. Otherwise return `("LAND", row, col)` at the furthest reachable non-ice cell

**`apply_move(state, block_pos, direction, bottom, move_index, spike_revival_moves) -> GameState | None`**
Implements all movement rules in order:

1. **Spike revival**: before processing, any spike in `destroyed_spikes` where `move_index - destroyed_at >= spike_revival_moves` is restored to the top layer (cell set back to `"spike"`, removed from `destroyed_spikes`). `spike_revival_moves=None` means never revive.
2. Call `compute_destination` to find where the block ends up (accounts for ice-filled sliding, see above)
3. If `"FALL"` into a **hole**: remove block from top; if block type is `"ice"` add to `ice_holes_filled`, else add to `holes_filled`
4. If `"FALL"` into **quicksand**: increment that cell's count in `quicksand_counts`; block is consumed (removed from top). When count reaches 2, the cell becomes walkable (Phil can cross it)
5. If `"LAND"`: place block at destination
6. **Spike collision**: if the block's destination top cell holds an active spike, both are removed; record `(row, col, move_index)` in `destroyed_spikes`
7. **Bumper interaction**: if the newly landed block is adjacent to a `"bounce"` cell, check the cell directly opposite the bumper on the same axis — if a movable block sits there, bump it one cell further (same direction). The bump is applied via a recursive `apply_move` call (max one level deep)
8. Reject if resulting state is identical to input state (no-op)

**`get_valid_moves(state, bottom)`** — yields `(block_pos, direction)` for every movable block (`"stone"`, `"ice"`) in all 4 directions where `apply_move` returns a new (non-identical) state.

**`solve(floor_grid, top_grid, max_depth=20, spike_revival_moves=None) -> dict`**
```python
def solve(floor_grid, top_grid, max_depth=20, spike_revival_moves=None):
    # Returns {"min_moves": int, "moves": [...], "solvable": bool}
    # BFS over GameState; visited = set of full GameState tuples
    # Each BFS node: (state, move_index, move_history)
    # Depth limit: max_depth (default 20) to bound search on hard levels
    # spike_revival_moves: None = never revive; int = revive after N player moves
```

### New: `app/routers/solver.py`
FastAPI router with one endpoint:

```
POST /solver/solve
Body: { "floor": [[...]], "top": [[...]], "max_depth": 20, "spike_revival_moves": null }
Response: { "solvable": bool, "min_moves": int | null, "moves": [...] | null }
```

Pydantic input model `LevelSolveRequest`:
```python
class LevelSolveRequest(BaseModel):
    floor: list[list[BlockType]]    # uses updated BlockType enum
    top:   list[list[BlockType]]
    max_depth: int = 20
    spike_revival_moves: Optional[int] = None  # None = never revive
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
- **Block types** — one subsection per block (MOVE_ONE, ICE, STATIC, BOUNCE, SPIKE, QUICKSAND) with exact movement/interaction rules
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
- Spike revival after a finite number of moves (skeleton in place; default is never-revive)

---

## Verification

1. **Unit test** — hand-craft a 3×3 minimal level (floor all null except one hole, top has one stone block and a GOAL), verify solver returns `min_moves=1`.
2. **CLI test**: `python solve_level.py --level sample_level.json` — confirm JSON output.
3. **API test**: `uvicorn app.main:app --reload --port 8080` then `curl -X POST localhost:8080/solver/solve -H 'Content-Type: application/json' -d @sample_level.json`
4. **Unsolvable level** — a level where the GOAL is fully surrounded by iron blocks should return `{"solvable": false}`.
