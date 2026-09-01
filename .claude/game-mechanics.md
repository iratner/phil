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
| Bottom | `EMPTY`, `STATIC`, `HOLE`, `QUICKSAND`, `ICE_FLOOR`, `SPIKE_FLOOR` |
| Top    | `EMPTY`, `STATIC`, `PHIL`, `GOAL`, `MOVE_ONE`, `ICE`, `BOUNCE`, `SPIKE` |

A cell may be expressed either as a bare `BlockType` string or as a `BlockSpec`
object (`{ type, can_destroy_spike?, is_destroyed_by_spike?, spiked_faces? }`)
when it needs per-block overrides — see **Block Properties** and **SPIKE** below.

---

## Phil

* Phil is a sphere that lives on the **top layer**.
* His starting position is the single `PHIL` cell in the top layer.
* **Phil never moves** during gameplay.  The player moves blocks to create a
  path to the `GOAL` cell.
* Phil can enter a cell if **all** conditions hold:
  1. The top-layer cell is `EMPTY`, `PHIL`, or `GOAL` (nothing blocking him).
  2. The bottom-layer cell is walkable: not `HOLE` (unless filled), not
     `STATIC`, not `QUICKSAND` with fewer than 2 blocks pushed in, and not an
     intact `SPIKE_FLOOR`.
  3. No live spike face of an adjacent `SPIKE` block points at the cell (see
     **SPIKE**).
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

### Block Properties

Movable blocks carry two boolean properties that govern spike interactions.
They are static (they travel with the block as it moves) and default per type:

* `can_destroy_spike` — if true, the block destroys the spike face it slides
  into.  **Defaults to `true` for all movable blocks** (`MOVE_ONE`, `ICE`),
  `false` otherwise.
* `is_destroyed_by_spike` — if true, the block is consumed when it strikes a
  *live* spike face.  **Defaults to `true`.**

Both can be overridden per cell via `BlockSpec`.  The solver respects every
combination of these flags (see SPIKE).

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
A spike block is a cube with up to **five independently spiked faces**: `UP`,
`NORTH`, `SOUTH`, `EAST`, `WEST` (the bottom face is never spiked).  Which faces
carry spikes is configurable per block (`spiked_faces`); a bare `SPIKE` cell
defaults to **all five faces** spiked.

* **Cannot** be pushed by the player while *any* face still carries spikes.
* **Faces and Phil's passability:** each cardinal face guards the neighbouring
  cell in its direction — Phil cannot occupy a cell that sits against a live
  face.  Phil can never enter the spike's own cell (it is a block).  The `UP`
  face is the *top* of the cube: for a top-layer spike it guards nothing in
  2-D, but for a ground-level spike (`SPIKE_FLOOR`) it makes the cell itself
  non-walkable.
* **Side-face collision / destruction:** when a movable block slides into a
  top-layer spike it strikes the face *opposite* its motion (moving right
  strikes the `WEST` face, etc.).  Resolution depends on the incoming block's
  properties and the struck face:
  * If the struck face is already clear, the spike acts as an ordinary wall —
    the block stops before it.
  * Else if `can_destroy_spike` is true, that **one face** loses its spikes.
  * The incoming block is then consumed if `is_destroyed_by_spike` is true;
    otherwise it survives and stops in the cell immediately before the spike.
  * If the block can neither destroy the face nor be destroyed by it, the
    spike is a wall (block stops before it; a no-move push is illegal).
* **Top-face (`UP`) destruction:** the top face is destroyable when the spike
  is **ground-level** (`SPIKE_FLOOR`).  A block with `can_destroy_spike` that
  slides **onto** the cell destroys the top face (then is consumed, or lands on
  the now-flat cell, per `is_destroyed_by_spike`).  See `SPIKE_FLOOR` in the
  floor types below.
* **Becoming movable:** once **all** faces are cleared, a top-layer spike turns
  into an ordinary `MOVE_ONE` block (with default movable properties) and can
  be pushed.  (A default all-faces top-layer spike keeps its undestroyable `UP`
  face, so it never auto-converts; author `spiked_faces` without `UP` for
  spikes meant to be cleared.)
* **No revival** — destroyed faces stay destroyed for the rest of the level.

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

### SPIKE_FLOOR (Ground-Level Spike)
A spike embedded in the floor, exposing only its top (`UP`) face.

* Phil **cannot** stand on the cell while the top face carries spikes.
* A top-layer block cannot pass over it while intact — it collides with the top
  face on arrival (the same way a side-face collision works for a `SPIKE`):
  * A block with `can_destroy_spike` true destroys the top face; the block is
    then consumed if `is_destroyed_by_spike` is true, otherwise it lands on the
    now-flat cell.
  * A block that cannot destroy the face is consumed (if `is_destroyed_by_spike`)
    or stops in the cell before it.
* Once the top face is destroyed the cell behaves as plain `EMPTY` floor
  (walkable by Phil, slid over by blocks).  Tracked in solver state as
  `floor_spikes_destroyed`.

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
* **State representation** (`GameState`):
  * `top` — immutable 2D tuple of `Cell` values.  Each `Cell` carries its
    `type`, the movable properties `can_destroy_spike` / `is_destroyed_by_spike`,
    and `spiked_faces` (the faces a `SPIKE` still has).  Properties travel with
    the block as it moves; a fully de-spiked `SPIKE` becomes a `MOVE_ONE` cell.
  * `holes_filled` — frozenset of `(row, col)` positions where holes have been
    filled by non-ice blocks (now walkable as solid floor).
  * `ice_holes_filled` — frozenset of `(row, col)` positions where holes have
    been filled by ICE blocks (walkable but slippery).
  * `quicksand_counts` — sorted tuple of `((row, col), fill_count)` pairs.
  * `floor_spikes_destroyed` — frozenset of `(row, col)` `SPIKE_FLOOR` cells
    whose top face has been destroyed (now plain floor).
* **Scoring is not computed by the solver** — points and multipliers are live
  game mechanics only.
* **Depth limit**: configurable `max_depth` (default 20 moves) bounds the BFS
  for impractically hard or unsolvable levels.
* **Output**: `{ "solvable": bool, "min_moves": int | null, "moves": [...] }`
  where each move is `{ "block_row": int, "block_col": int, "direction": str }`.
