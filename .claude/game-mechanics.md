# Phil Game Mechanics Reference

This document captures all game mechanics as defined in `phil-game-rules.md` and
refined during the solver planning session.  It is the authoritative reference for
Claude when working on any code that touches game logic.

---

## Board Structure

* Two independent layers share the same grid coordinates:
  * **Bottom layer (floor)** — the surface Phil walks on; also determines how
    top-layer blocks behave when they slide over a cell.
  * **Top layer (blocks)** — the layer the player manipulates and the layer Phil
    occupies.
* Maximum dimensions: **16 columns × 24 rows** (may increase later).
* Both layers are represented as 2D arrays indexed `[row][col]`.
* The canonical cell-type enum is `BlockType` in
  `python-workspace/phil-leveler-fapi/app/models/level.py`.

### What each layer may contain

| Layer  | Valid BlockType values |
|--------|------------------------|
| Bottom | `EMPTY`, `STATIC`, `HOLE`, `QUICKSAND`, `ICE_FLOOR` |
| Top    | `EMPTY`, `STATIC`, `PHIL`, `GOAL`, `MOVE_ONE`, `ICE`, `BOUNCE`, `SPIKE` |

---

## Phil

* Phil is a sphere that lives on the **top layer**.
* His starting position is the single `PHIL` cell in the top layer.
* **Phil never moves** during gameplay.  The player moves blocks to create a
  path to the `GOAL` cell.
* Phil can enter a cell if **both** conditions hold:
  1. The top-layer cell is `EMPTY`, `PHIL`, or `GOAL` (nothing blocking him).
  2. The bottom-layer cell is walkable: not `HOLE` (unless filled), not
     `STATIC`, and not `QUICKSAND` with fewer than 2 blocks pushed in.
* Phil moves orthogonally only (no diagonal).
* Phil cannot jump over blocks on the top layer.

### Win condition

The level is **won** when a continuous orthogonal path of Phil-walkable cells
connects `PHIL` to `GOAL`.  This is checked after every player move via a
flood-fill from Phil's position.

---

## Player Moves

A **move** is the player pushing one movable top-layer block one step in a
cardinal direction (up / down / left / right).

Only `MOVE_ONE` and `ICE` blocks can be pushed directly by the player.

After a move resolves (including all secondary interactions), the board is
checked for the win condition.

---

## Top-Layer Block Types

### EMPTY
No block.  Phil can walk here (subject to floor).

### STATIC (Immovable Iron)
Cannot be moved by the player or by any game interaction.  Blocks Phil's path.

### PHIL
Phil's fixed starting position.  Treated as walkable for flood-fill purposes.

### GOAL
Win target.  Treated as walkable for flood-fill purposes (Phil can "enter" it).

### MOVE_ONE (Stone)
* Player can push in any of the 4 directions.
* Slides **exactly one cell**.
* If the destination top cell is occupied or out-of-bounds, the move is illegal.
* If the destination bottom cell is `HOLE`: block falls through → hole becomes
  solid walkable floor (treated as `EMPTY` from that point on).
* If the destination bottom cell is `QUICKSAND`: block is consumed, quicksand
  fill count increments (see Quicksand below).
* If the destination bottom cell is `ICE_FLOOR` or a runtime-ice-filled hole:
  the block keeps sliding (see Ice Sliding below).

### ICE (Ice Block)
* Behaves like `MOVE_ONE` with one extra rule:
* When an ICE block falls into a `HOLE`, the hole is filled **with ice** — the
  cell becomes slippery at runtime (tracked in solver state as `ice_holes_filled`,
  distinct from `holes_filled`).
* Ice-filled cells cause subsequent top-layer blocks that would land there to
  keep sliding (same as `ICE_FLOOR`).

### BOUNCE (Bumper)
* **Cannot** be moved directly by the player.
* Interaction trigger: a movable block is pushed into the cell *adjacent* to a
  BOUNCE block (the block lands next to the bumper).
* If another movable block exists on the **opposite side** of the BOUNCE block
  along the same axis, that block is bumped one cell further in the direction
  of the incoming block.
* The bump is part of the same player move (not an additional move).
* The bumped block itself may trigger further interactions (spike destruction,
  hole fill, etc.) but does **not** chain another bumper interaction.

### SPIKE
* **Cannot** be moved directly by the player.
* Interaction: when any sliding top-layer block's path ends at a SPIKE cell,
  both the sliding block **and** the spike are removed (spike retracts, cell
  becomes `EMPTY`).
* Revival: spikes can optionally return after a configurable number of player
  moves (`spike_revival_moves` solver parameter).  Default is `None` (never
  revives).  When revival is active, the solver tracks `(row, col,
  destroyed_at_move)` tuples and restores the spike cell once the move-count
  threshold is reached.

---

## Bottom-Layer (Floor) Cell Types

### EMPTY
Solid, flat floor.  Phil can stand here.  Top blocks slide over without
special effect.

### STATIC (Immovable Iron)
Impassable floor fixture.  Phil cannot step here.  Top-layer blocks cannot
slide through it (acts as a wall for block movement).

### HOLE
* Phil cannot stand on or cross a hole.
* A top-layer block that slides over a hole **falls through**:
  * `MOVE_ONE` / other non-ice movable blocks: hole becomes solid (`EMPTY`),
    walkable by Phil.
  * `ICE` block: hole becomes an ice-filled cell (slippery — tracked separately
    in solver state).
* A filled hole is walkable from the next move onward.

### QUICKSAND
* Phil cannot cross until **exactly 2** top-layer blocks have fallen into it.
* The solver tracks the fill count per quicksand cell in `quicksand_counts`.
* At fill count ≥ 2 the cell is walkable (treated as `EMPTY`).

### ICE_FLOOR
* Phil can walk over it normally.
* Top-layer blocks that would land on an `ICE_FLOOR` cell **keep sliding** in
  the same direction until they:
  * Hit a wall / board boundary.
  * Hit another top-layer block.
  * Hit a `STATIC` bottom cell.
  * Reach a non-ice bottom cell (they land there).
  * Reach an unfilled `HOLE` or `QUICKSAND` (they fall through at that point).

---

## Ice Sliding — Detailed Rules

Ice sliding applies when a block's computed landing cell has an ice surface:
either an `ICE_FLOOR` cell or a hole that was previously filled by an `ICE`
block (tracked in `ice_holes_filled`).

Algorithm (`compute_destination`):
1. Compute the first step from the pushed block's position.
2. If the first step is blocked (top block, `STATIC` floor, or out-of-bounds):
   the move is illegal.
3. If the first-step floor is an unfilled `HOLE` or `QUICKSAND`: block falls
   immediately (`FALL` result).
4. If the first-step floor is ice (either `ICE_FLOOR` or in `ice_holes_filled`):
   enter sliding loop — keep advancing one cell at a time until a stop
   condition is met.
5. Stop conditions (block lands before / at the stopping cell):
   * Next cell is out-of-bounds → land at current cell.
   * Next cell has a top-layer block → land at current cell.
   * Next cell's floor is `STATIC` → land at current cell.
   * Next cell's floor is non-ice, non-hole → land at next cell.
   * Next cell's floor is an unfilled `HOLE`/`QUICKSAND` → fall at next cell.

---

## Solver Notes

* **What the solver computes**: minimum number of *player* moves to reach the
  win condition (path from PHIL to GOAL exists).
* **Algorithm**: BFS over `GameState` tuples; each BFS level = one player move.
* **State representation** (`GameState` NamedTuple):
  * `top` — immutable 2D tuple of current top-layer cell types.
  * `holes_filled` — frozenset of `(row, col)` positions where holes have been
    filled by non-ice blocks (now walkable as solid floor).
  * `ice_holes_filled` — frozenset of `(row, col)` positions where holes have
    been filled by ICE blocks (walkable but slippery).
  * `quicksand_counts` — sorted tuple of `((row, col), fill_count)` pairs.
  * `destroyed_spikes` — tuple of `(row, col, destroyed_at_move)` triples.
* **Scoring is not computed by the solver** — points and multipliers are live
  game mechanics only.
* **Depth limit**: configurable `max_depth` (default 20 moves) bounds the BFS
  for impractically hard or unsolvable levels.
* **Output**: `{ "solvable": bool, "min_moves": int | null, "moves": [...] }`
  where each move is `{ "block_row": int, "block_col": int, "direction": str }`.
