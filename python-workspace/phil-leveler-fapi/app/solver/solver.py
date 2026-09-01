"""BFS solver that finds the minimum number of player moves required to win a
Phil level.

A "move" is the player pushing one movable top-layer block (MOVE_ONE or ICE)
one step in a cardinal direction.  The level is won when a continuous
orthogonal path of Phil-walkable cells connects the PHIL cell to the GOAL
cell on the top layer (flood-fill check after every move).

Spikes are modelled as cubes with up to five independently spiked faces (UP,
NORTH, SOUTH, EAST, WEST; the bottom face is never spiked).  A movable block
that can destroy spikes removes the spikes from the single face it slides into;
Phil cannot occupy a cell that sits against a still-spiked face.  See
`.claude/game-mechanics.md` at the repo root for the full rule reference.

Scoring / points are **not** computed here — they are a live game mechanic only.
"""

from __future__ import annotations

from collections import deque
from typing import NamedTuple, Optional, Sequence, Union

from app.models.level import BlockSpec, BlockType, Face

# ---------------------------------------------------------------------------
# Direction helpers
# ---------------------------------------------------------------------------

DIRECTIONS = ("up", "down", "left", "right")

_DELTA: dict[str, tuple[int, int]] = {
    "up": (-1, 0),
    "down": (1, 0),
    "left": (0, -1),
    "right": (0, 1),
}

# When a block travels in a direction it strikes the spike face *opposite* to
# its motion (a block moving right hits the spike's WEST face, and so on).
_HIT_FACE: dict[str, Face] = {
    "up": Face.SOUTH,
    "down": Face.NORTH,
    "left": Face.EAST,
    "right": Face.WEST,
}

# The neighbouring cell each cardinal face guards, relative to the spike block.
# UP guards the spike's own cell (relevant only for ground-level spikes) and is
# handled separately, so it is intentionally absent here.
_FACE_DELTA: dict[Face, tuple[int, int]] = {
    Face.NORTH: (-1, 0),
    Face.SOUTH: (1, 0),
    Face.EAST: (0, 1),
    Face.WEST: (0, -1),
}

ALL_FACES: frozenset[Face] = frozenset(
    {Face.UP, Face.NORTH, Face.SOUTH, Face.EAST, Face.WEST}
)

MOVABLE_TYPES = (BlockType.MOVE_ONE, BlockType.ICE)

# ---------------------------------------------------------------------------
# Type aliases for readability
# ---------------------------------------------------------------------------

# A row/column pair.
Pos = tuple[int, int]


class Cell(NamedTuple):
    """A single top-layer cell, carrying per-block properties.

    Storing properties on the cell (rather than position-indexed side tables)
    means they travel with the block automatically as it moves, and keeps the
    whole top layer hashable for use as a BFS visited key.

    Attributes:
        type: The block type occupying this cell.
        can_destroy_spike: If true, this block destroys the spike face it
            slides into.  Meaningful only for movable blocks.
        is_destroyed_by_spike: If true, this block is consumed when it strikes
            a live spike face.  Meaningful only for movable blocks.
        spiked_faces: The faces that still carry spikes.  Non-empty only while
            ``type`` is SPIKE; a SPIKE whose faces are all cleared is converted
            to a MOVE_ONE cell.
        capacity: For a QUICKSAND floor cell, how many top-layer blocks must
            sink before it becomes walkable.  Meaningful only on the bottom
            layer; carried here so floor cells share the same config-bearing
            representation as top-layer cells.  Defaults to 2.
    """

    type: BlockType
    can_destroy_spike: bool = False
    is_destroyed_by_spike: bool = False
    spiked_faces: frozenset[Face] = frozenset()
    capacity: int = 2


# An immutable 2-D grid of Cell values (top layer).
TopGrid = tuple[tuple[Cell, ...], ...]

# An immutable 2-D grid of Cell values (bottom layer).  The bottom layer never
# changes during play, but each cell carries its own static config (e.g. a
# QUICKSAND cell's ``capacity``), so it uses the same Cell representation as the
# top layer rather than a bare BlockType.
BottomGrid = tuple[tuple[Cell, ...], ...]

# Quicksand fill tracker: sorted tuple of ((row, col), fill_count) pairs.
QuicksandCounts = tuple[tuple[Pos, int], ...]

# A raw cell as supplied by callers: a bare BlockType (or its string value) or
# a BlockSpec object, or an already-normalised Cell.
RawCell = Union[BlockType, BlockSpec, Cell, str]

_EMPTY_CELL = Cell(BlockType.EMPTY)


# ---------------------------------------------------------------------------
# Cell normalisation
# ---------------------------------------------------------------------------


def _to_cell(value: RawCell) -> Cell:
    """Normalise a raw cell value into a :class:`Cell` with resolved defaults.

    Accepts an already-built Cell, a BlockSpec (with optional overrides), or a
    bare BlockType / string.  Unset properties are filled in per type:
      - ``can_destroy_spike`` defaults to true for movable blocks, else false.
      - ``is_destroyed_by_spike`` defaults to true.
      - ``spiked_faces`` defaults to all five faces for SPIKE, else empty.
        (SPIKE_FLOOR lives on the bottom layer and is not represented here.)
      - ``capacity`` defaults to 2 (the QUICKSAND fill threshold); the default
        is uniform across types so equivalent cells compare equal for hashing.
    """
    if isinstance(value, Cell):
        return value

    if isinstance(value, BlockSpec):
        btype = BlockType(value.type)
        can_destroy = value.can_destroy_spike
        is_destroyed = value.is_destroyed_by_spike
        faces: Optional[frozenset[Face]] = (
            frozenset(Face(f) for f in value.spiked_faces)
            if value.spiked_faces is not None
            else None
        )
        capacity = value.capacity
    else:
        btype = BlockType(value)
        can_destroy = None
        is_destroyed = None
        faces = None
        capacity = None

    if can_destroy is None:
        can_destroy = btype in MOVABLE_TYPES
    if is_destroyed is None:
        is_destroyed = True
    if faces is None:
        faces = ALL_FACES if btype == BlockType.SPIKE else frozenset()
    if capacity is None:
        capacity = 2

    return Cell(
        type=btype,
        can_destroy_spike=can_destroy,
        is_destroyed_by_spike=is_destroyed,
        spiked_faces=faces,
        capacity=capacity,
    )


def _movable_cell(block_type: BlockType) -> Cell:
    """Return a fresh movable Cell with default spike-interaction flags.

    Used when a fully de-spiked SPIKE block becomes an ordinary movable block.
    """
    return Cell(
        type=block_type,
        can_destroy_spike=True,
        is_destroyed_by_spike=True,
        spiked_faces=frozenset(),
    )


# ---------------------------------------------------------------------------
# GameState
# ---------------------------------------------------------------------------


class GameState:
    """Immutable snapshot of the mutable parts of the board.

    The bottom layer never changes except for spike-floor destruction, so it is
    held outside the state and passed to every function that needs it.  Only the
    elements that *can* change during play are stored here so that the state can
    be hashed and used as a BFS visited key.

    Attributes:
        top: Current top-layer grid of Cells (carries block positions, spike
            face state, and per-block properties).
        holes_filled: Positions of HOLE cells filled by a non-ICE block.
            Filled holes are solid and walkable.
        ice_holes_filled: Positions of HOLE cells filled by an ICE block.
            Walkable but slippery — a top-layer block landing here keeps sliding.
        quicksand_counts: How many top-layer blocks have fallen into each
            QUICKSAND cell.  A cell is walkable once its count reaches 2.
        floor_spikes_destroyed: Positions of SPIKE_FLOOR cells whose top face
            has been destroyed.  These behave as plain EMPTY floor.
    """

    __slots__ = (
        "top",
        "holes_filled",
        "ice_holes_filled",
        "quicksand_counts",
        "floor_spikes_destroyed",
    )

    def __init__(
        self,
        top: TopGrid,
        holes_filled: frozenset[Pos],
        ice_holes_filled: frozenset[Pos],
        quicksand_counts: QuicksandCounts,
        floor_spikes_destroyed: frozenset[Pos],
    ) -> None:
        self.top = top
        self.holes_filled = holes_filled
        self.ice_holes_filled = ice_holes_filled
        self.quicksand_counts = quicksand_counts
        self.floor_spikes_destroyed = floor_spikes_destroyed

    # Equality and hashing let GameState be used as a dict key / set member.

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, GameState):
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self) -> int:
        return hash(self._key())

    def _key(self) -> tuple:
        return (
            self.top,
            self.holes_filled,
            self.ice_holes_filled,
            self.quicksand_counts,
            self.floor_spikes_destroyed,
        )


# ---------------------------------------------------------------------------
# Grid helpers
# ---------------------------------------------------------------------------


def _top_grid_from_lists(rows: Sequence[Sequence[RawCell]]) -> TopGrid:
    """Convert a mutable 2-D list of raw cells into an immutable Cell grid."""
    return tuple(tuple(_to_cell(cell) for cell in row) for row in rows)


def _top_grid_to_lists(grid: TopGrid) -> list[list[Cell]]:
    """Convert an immutable Cell grid back to a mutable 2-D list for editing."""
    return [list(row) for row in grid]


def _bottom_grid_from_lists(rows: Sequence[Sequence[RawCell]]) -> BottomGrid:
    """Convert a mutable 2-D floor list into an immutable Cell grid.

    Floor cells carry their own static per-cell config (e.g. a QUICKSAND cell's
    ``capacity``), so each raw cell is normalised through :func:`_to_cell` just
    like the top layer — nothing is discarded.  The grid is still immutable and
    never mutated during play; it simply travels alongside the mutable
    :class:`GameState`.
    """
    return tuple(tuple(_to_cell(cell) for cell in row) for row in rows)


def _in_bounds(grid: tuple, row: int, col: int) -> bool:
    """Return True if (row, col) is a valid coordinate for *grid*."""
    return 0 <= row < len(grid) and 0 <= col < len(grid[0])


# ---------------------------------------------------------------------------
# Quicksand helpers
# ---------------------------------------------------------------------------


def _qs_count(quicksand_counts: QuicksandCounts, pos: Pos) -> int:
    """Return the current fill count for a QUICKSAND cell at *pos*."""
    for p, count in quicksand_counts:
        if p == pos:
            return count
    return 0


def _qs_increment(quicksand_counts: QuicksandCounts, pos: Pos) -> QuicksandCounts:
    """Return a new QuicksandCounts with the count at *pos* incremented by 1."""
    updated = dict(quicksand_counts)
    updated[pos] = updated.get(pos, 0) + 1
    return tuple(sorted(updated.items()))


# ---------------------------------------------------------------------------
# Floor / walkability helpers
# ---------------------------------------------------------------------------


def _effective_floor(
    row: int,
    col: int,
    bottom: BottomGrid,
    holes_filled: frozenset[Pos],
    ice_holes_filled: frozenset[Pos],
    quicksand_counts: QuicksandCounts,
    floor_spikes_destroyed: frozenset[Pos] = frozenset(),
) -> BlockType:
    """Return the *effective* floor type at (row, col) after runtime changes.

    The bottom layer is immutable, but holes can be filled at runtime, quicksand
    can become walkable after two fills, and a ground-level spike's top face can
    be destroyed.  This resolves the current effective floor so the rest of the
    solver only needs to call it once per cell.

    Effective floor rules (in priority order):
    1. HOLE in holes_filled → EMPTY.
    2. HOLE in ice_holes_filled → ICE_FLOOR.
    3. QUICKSAND with fill count >= the cell's capacity → EMPTY.
    4. SPIKE_FLOOR in floor_spikes_destroyed → EMPTY.
    5. Otherwise the original bottom-layer value.
    """
    pos = (row, col)
    cell = bottom[row][col]
    original = cell.type
    if original == BlockType.HOLE:
        if pos in holes_filled:
            return BlockType.EMPTY
        if pos in ice_holes_filled:
            return BlockType.ICE_FLOOR
    if original == BlockType.QUICKSAND:
        if _qs_count(quicksand_counts, pos) >= cell.capacity:
            return BlockType.EMPTY
    if original == BlockType.SPIKE_FLOOR:
        if pos in floor_spikes_destroyed:
            return BlockType.EMPTY
    return original


def _is_slippery_floor(floor: BlockType) -> bool:
    """Return True if the floor type causes top-layer blocks to keep sliding.

    Both ICE_FLOOR (placed at design time) and the runtime equivalent created
    when an ICE block fills a HOLE cause sliding.  Phil is unaffected.
    """
    return floor == BlockType.ICE_FLOOR


def _cell_blocked_by_spike(top: TopGrid, row: int, col: int) -> bool:
    """Return True if a still-spiked face of an adjacent SPIKE guards (row, col).

    A SPIKE at (sr, sc) with a cardinal face F guards the neighbour in F's
    direction.  Phil cannot occupy a cell guarded by any live face.  (The UP
    face of a top-layer spike guards nothing in 2-D; ground-level spike UP faces
    are handled through the effective floor instead.)
    """
    for face, (fdr, fdc) in _FACE_DELTA.items():
        # A spike that would guard (row, col) via *face* sits one step back
        # along that face's direction.
        sr, sc = row - fdr, col - fdc
        if _in_bounds(top, sr, sc):
            cell = top[sr][sc]
            if cell.type == BlockType.SPIKE and face in cell.spiked_faces:
                return True
    return False


def _is_phil_walkable(
    row: int,
    col: int,
    top_cell: Union[Cell, BlockType],
    effective_floor: BlockType,
) -> bool:
    """Return True if Phil can occupy (row, col) ignoring adjacent spike faces.

    Phil can enter a cell when:
    - The top-layer cell is EMPTY, PHIL, or GOAL (nothing blocks him).
    - The effective floor is not HOLE, STATIC, unfilled QUICKSAND, or an intact
      SPIKE_FLOOR.

    The adjacent-spike-face guard is applied separately by the flood-fill (see
    :func:`_cell_blocked_by_spike`) so this predicate stays purely cell-local.
    ``top_cell`` may be a Cell or a bare BlockType.

    Callers must pass the *effective* floor (after runtime fill changes).
    """
    cell_type = top_cell.type if isinstance(top_cell, Cell) else top_cell
    if cell_type not in (BlockType.EMPTY, BlockType.PHIL, BlockType.GOAL):
        return False
    if effective_floor in (
        BlockType.HOLE,
        BlockType.STATIC,
        BlockType.QUICKSAND,
        BlockType.SPIKE_FLOOR,
    ):
        # QUICKSAND / SPIKE_FLOOR reaching here are still impassable;
        # _effective_floor already returns EMPTY once they become walkable.
        return False
    return True


# ---------------------------------------------------------------------------
# Block destination computation (includes ice sliding + spike encounters)
# ---------------------------------------------------------------------------


def _compute_destination(
    block_pos: Pos,
    direction: str,
    top: TopGrid,
    bottom: BottomGrid,
    holes_filled: frozenset[Pos],
    ice_holes_filled: frozenset[Pos],
    quicksand_counts: QuicksandCounts,
    floor_spikes_destroyed: frozenset[Pos],
) -> Optional[tuple]:
    """Compute where a pushed block ends up, before block-specific resolution.

    Handles one-step movement, ice sliding, and the *geometry* of spike
    encounters.  Whether a spike face is destroyed and whether the block
    survives depends on the block's own properties and is resolved by the
    caller (:func:`_apply_move`).

    Stopping / outcome conditions (checked at each step):
    - Out-of-bounds → land at the current cell (or illegal on the first step).
    - Next cell is a SPIKE whose struck face is still spiked → ``("SPIKE", r, c)``.
    - Next cell is a SPIKE whose struck face is already clear, or any other
      non-EMPTY top block → it acts as a wall; stop at the current cell.
    - Next floor is STATIC → wall; stop at the current cell.
    - Next floor is an unfilled HOLE / QUICKSAND → ``("FALL", r, c)``.
    - Next floor is an intact SPIKE_FLOOR → ``("FLOOR_SPIKE", r, c)``.
    - Next floor is non-slippery → ``("LAND", r, c)``.
    - Next floor is slippery → keep sliding.

    Returns one of ``("LAND"|"FALL"|"SPIKE"|"FLOOR_SPIKE", row, col)`` or None
    if the move is entirely blocked (the block cannot advance and nothing else
    happens).
    """
    dr, dc = _DELTA[direction]
    cur_row, cur_col = block_pos
    hit_face = _HIT_FACE[direction]

    # --- First step (a move must advance at least one cell). ---------------
    next_row, next_col = cur_row + dr, cur_col + dc
    if not _in_bounds(top, next_row, next_col):
        return None  # Can't move off the board.

    next_cell = top[next_row][next_col]
    if next_cell.type == BlockType.SPIKE:
        if hit_face in next_cell.spiked_faces:
            return ("SPIKE", next_row, next_col)
        return None  # Spike face already gone — acts as a wall on step one.
    if next_cell.type != BlockType.EMPTY:
        return None  # Destination occupied by another block.

    next_floor = _effective_floor(
        next_row,
        next_col,
        bottom,
        holes_filled,
        ice_holes_filled,
        quicksand_counts,
        floor_spikes_destroyed,
    )
    if next_floor == BlockType.STATIC:
        return None  # Can't slide into an iron floor cell.
    if next_floor in (BlockType.HOLE, BlockType.QUICKSAND):
        return ("FALL", next_row, next_col)
    if next_floor == BlockType.SPIKE_FLOOR:
        return ("FLOOR_SPIKE", next_row, next_col)

    # Block lands on the first step; if the floor is slippery it keeps going.
    cur_row, cur_col = next_row, next_col

    while _is_slippery_floor(next_floor):
        peek_row, peek_col = cur_row + dr, cur_col + dc
        if not _in_bounds(top, peek_row, peek_col):
            break  # Wall — stop here.

        peek_cell = top[peek_row][peek_col]
        if peek_cell.type == BlockType.SPIKE:
            if hit_face in peek_cell.spiked_faces:
                return ("SPIKE", peek_row, peek_col)
            break  # Spike face gone — acts as a wall; stop at current cell.
        if peek_cell.type != BlockType.EMPTY:
            break  # Blocked by another top-layer block — stop here.

        peek_floor = _effective_floor(
            peek_row,
            peek_col,
            bottom,
            holes_filled,
            ice_holes_filled,
            quicksand_counts,
            floor_spikes_destroyed,
        )
        if peek_floor == BlockType.STATIC:
            break  # Can't enter an iron floor cell — stop here.
        if peek_floor in (BlockType.HOLE, BlockType.QUICKSAND):
            return ("FALL", peek_row, peek_col)
        if peek_floor == BlockType.SPIKE_FLOOR:
            return ("FLOOR_SPIKE", peek_row, peek_col)

        cur_row, cur_col = peek_row, peek_col
        next_floor = peek_floor

    return ("LAND", cur_row, cur_col)


# ---------------------------------------------------------------------------
# Move application
# ---------------------------------------------------------------------------


def _apply_move(
    state: GameState,
    block_pos: Pos,
    direction: str,
    bottom: BottomGrid,
) -> Optional[GameState]:
    """Apply a single player push and return the resulting GameState.

    Implements (in order):
    1. Destination computation — including ice sliding and spike encounters.
    2. FALL — hole fill or quicksand increment.
    3. LAND — place the block, then resolve any bumper interaction.
    4. SPIKE collision — destroy the struck face (if the block can) and consume
       the block (if it is destroyed by spikes); a fully de-spiked SPIKE becomes
       a MOVE_ONE block.
    5. FLOOR_SPIKE collision — same logic against a ground-level spike's top face.
    6. No-op rejection — return None if the board is unchanged.

    Args:
        state: Current game state.
        block_pos: (row, col) of the block the player is pushing.
        direction: One of "up" / "down" / "left" / "right".
        bottom: Immutable bottom-layer grid.

    Returns:
        The new GameState, or None if the move is illegal or a no-op.
    """
    block_row, block_col = block_pos
    block_cell = state.top[block_row][block_col]

    # Only MOVE_ONE and ICE blocks can be pushed.  (Bumper recursion pushes
    # these same types, so this guard also applies inside bumper resolution.)
    if block_cell.type not in MOVABLE_TYPES:
        return None

    dest = _compute_destination(
        block_pos,
        direction,
        state.top,
        bottom,
        state.holes_filled,
        state.ice_holes_filled,
        state.quicksand_counts,
        state.floor_spikes_destroyed,
    )
    if dest is None:
        return None  # Move is illegal.

    dest_kind, dest_row, dest_col = dest

    top_lists = _top_grid_to_lists(state.top)
    holes_filled = state.holes_filled
    ice_holes_filled = state.ice_holes_filled
    quicksand_counts = state.quicksand_counts
    floor_spikes_destroyed = state.floor_spikes_destroyed

    # The block always leaves its starting cell.
    top_lists[block_row][block_col] = _EMPTY_CELL

    if dest_kind == "FALL":
        original_floor = bottom[dest_row][dest_col].type
        if original_floor == BlockType.HOLE:
            if block_cell.type == BlockType.ICE:
                ice_holes_filled = ice_holes_filled | {(dest_row, dest_col)}
            else:
                holes_filled = holes_filled | {(dest_row, dest_col)}
        elif original_floor == BlockType.QUICKSAND:
            quicksand_counts = _qs_increment(quicksand_counts, (dest_row, dest_col))
            # Block is consumed — it does not appear on the top layer.

    elif dest_kind == "SPIKE":
        _resolve_spike_collision(
            top_lists,
            block_cell,
            spike_pos=(dest_row, dest_col),
            direction=direction,
        )

    elif dest_kind == "FLOOR_SPIKE":
        floor_spikes_destroyed = _resolve_floor_spike_collision(
            top_lists,
            block_cell,
            floor_pos=(dest_row, dest_col),
            direction=direction,
            floor_spikes_destroyed=floor_spikes_destroyed,
        )

    else:  # dest_kind == "LAND"
        top_lists[dest_row][dest_col] = block_cell

        # Bumper interaction — chains through consecutive bumpers.
        intermediate = GameState(
            top=_top_grid_from_lists(top_lists),
            holes_filled=holes_filled,
            ice_holes_filled=ice_holes_filled,
            quicksand_counts=quicksand_counts,
            floor_spikes_destroyed=floor_spikes_destroyed,
        )
        bumped = _resolve_bumper(
            intermediate, (dest_row, dest_col), direction, bottom
        )
        if bumped is not None:
            if bumped._key() == state._key():
                return None
            return bumped

    new_state = GameState(
        top=_top_grid_from_lists(top_lists),
        holes_filled=holes_filled,
        ice_holes_filled=ice_holes_filled,
        quicksand_counts=quicksand_counts,
        floor_spikes_destroyed=floor_spikes_destroyed,
    )

    if new_state._key() == state._key():
        return None  # No-op.

    return new_state


def _resolve_spike_collision(
    top_lists: list[list[Cell]],
    block_cell: Cell,
    spike_pos: Pos,
    direction: str,
) -> None:
    """Resolve a block striking a top-layer SPIKE face, mutating *top_lists*.

    The block has already been cleared from its origin cell.  Here:
    - If the block can destroy spikes, the struck face's spikes are removed.
      When that empties the spike's last face, the spike becomes a MOVE_ONE.
    - If the block is *not* destroyed by spikes, it survives and stops in the
      cell immediately before the spike; otherwise it is consumed.

    Bumper interactions are not triggered by a spike-stop landing.
    """
    dr, dc = _DELTA[direction]
    hit_face = _HIT_FACE[direction]
    spike_row, spike_col = spike_pos
    spike_cell = top_lists[spike_row][spike_col]

    if block_cell.can_destroy_spike:
        remaining = spike_cell.spiked_faces - {hit_face}
        if remaining:
            top_lists[spike_row][spike_col] = spike_cell._replace(
                spiked_faces=remaining
            )
        else:
            # Last face gone — the spike is now an ordinary movable block.
            top_lists[spike_row][spike_col] = _movable_cell(BlockType.MOVE_ONE)

    if not block_cell.is_destroyed_by_spike:
        stop_row, stop_col = spike_row - dr, spike_col - dc
        top_lists[stop_row][stop_col] = block_cell
    # Otherwise the block is consumed (already removed from its origin).


def _resolve_floor_spike_collision(
    top_lists: list[list[Cell]],
    block_cell: Cell,
    floor_pos: Pos,
    direction: str,
    floor_spikes_destroyed: frozenset[Pos],
) -> frozenset[Pos]:
    """Resolve a block sliding onto a ground-level SPIKE_FLOOR cell.

    A SPIKE_FLOOR exposes only its top face.  If the block can destroy spikes,
    that face is destroyed (the cell becomes plain floor) and the block lands on
    it unless it is consumed.  If the block cannot destroy spikes it is either
    consumed or — if it survives — stops in the cell before the floor spike.

    Returns the (possibly updated) ``floor_spikes_destroyed`` set.
    """
    dr, dc = _DELTA[direction]
    floor_row, floor_col = floor_pos

    if block_cell.can_destroy_spike:
        floor_spikes_destroyed = floor_spikes_destroyed | {floor_pos}
        if not block_cell.is_destroyed_by_spike:
            # Floor is now flat — the block lands on it.
            top_lists[floor_row][floor_col] = block_cell
        # Otherwise the block is consumed.
    else:
        if not block_cell.is_destroyed_by_spike:
            stop_row, stop_col = floor_row - dr, floor_col - dc
            top_lists[stop_row][stop_col] = block_cell
        # Otherwise the block is consumed.

    return floor_spikes_destroyed


def _resolve_bumper(
    state: GameState,
    landed_pos: Pos,
    direction: str,
    bottom: BottomGrid,
) -> Optional[GameState]:
    """Check for a bumper interaction after a block lands at *landed_pos*.

    Rule: when a movable block lands in a cell adjacent to a BOUNCE block, and
    another movable block sits on the *opposite* side of that BOUNCE block along
    the same axis, the opposite block is bumped one cell further in the same
    direction.  The bump is part of the same player move.  Bumpers chain through
    a row of consecutive bumpers.

    Returns the new state after the bump, or None if no bump occurred.
    """
    dr, dc = _DELTA[direction]
    land_row, land_col = landed_pos

    bounce_row, bounce_col = land_row + dr, land_col + dc
    if not _in_bounds(state.top, bounce_row, bounce_col):
        return None
    if state.top[bounce_row][bounce_col].type != BlockType.BOUNCE:
        return None

    target_row, target_col = bounce_row + dr, bounce_col + dc
    if not _in_bounds(state.top, target_row, target_col):
        return None
    if state.top[target_row][target_col].type not in MOVABLE_TYPES:
        return None  # Only movable blocks can be bumped.

    # Bump the target by recursing.  _apply_move re-runs bumper resolution, so a
    # row of consecutive bumpers chains.  This terminates: every bump advances a
    # block strictly further along the fixed push direction on a finite board.
    return _apply_move(state, (target_row, target_col), direction, bottom)


# ---------------------------------------------------------------------------
# Phil reachability (win condition check)
# ---------------------------------------------------------------------------


def _find_phil_and_goal(top: TopGrid) -> tuple[Optional[Pos], Optional[Pos]]:
    """Scan the top layer and return (phil_pos, goal_pos).

    Returns None for whichever special cell is absent.  A valid level has
    exactly one PHIL and one GOAL cell.
    """
    phil_pos: Optional[Pos] = None
    goal_pos: Optional[Pos] = None
    for r, row in enumerate(top):
        for c, cell in enumerate(row):
            if cell.type == BlockType.PHIL:
                phil_pos = (r, c)
            elif cell.type == BlockType.GOAL:
                goal_pos = (r, c)
    return phil_pos, goal_pos


def _phil_can_reach_goal(
    state: GameState,
    phil_pos: Pos,
    goal_pos: Pos,
    bottom: BottomGrid,
) -> bool:
    """Return True if Phil can reach the GOAL from his starting position.

    BFS flood-fill from *phil_pos* over cells Phil can walk (see
    :func:`_is_phil_walkable`).  Phil's own starting cell always qualifies.
    """
    visited: set[Pos] = {phil_pos}
    queue: deque[Pos] = deque([phil_pos])

    while queue:
        row, col = queue.popleft()
        if (row, col) == goal_pos:
            return True

        for dr, dc in _DELTA.values():
            nr, nc = row + dr, col + dc
            if (nr, nc) in visited:
                continue
            if not _in_bounds(state.top, nr, nc):
                continue

            floor = _effective_floor(
                nr,
                nc,
                bottom,
                state.holes_filled,
                state.ice_holes_filled,
                state.quicksand_counts,
                state.floor_spikes_destroyed,
            )
            if _is_phil_walkable(
                nr, nc, state.top[nr][nc], floor
            ) and not _cell_blocked_by_spike(state.top, nr, nc):
                visited.add((nr, nc))
                queue.append((nr, nc))

    return False


# ---------------------------------------------------------------------------
# Valid-move enumeration
# ---------------------------------------------------------------------------


def _get_valid_moves(state: GameState, bottom: BottomGrid) -> list[tuple[Pos, str]]:
    """Return all legal (block_position, direction) pairs for the current state.

    A move is legal if :func:`_apply_move` returns a non-None state that differs
    from the current state.
    """
    moves: list[tuple[Pos, str]] = []
    for r, row in enumerate(state.top):
        for c, cell in enumerate(row):
            if cell.type not in MOVABLE_TYPES:
                continue
            for direction in DIRECTIONS:
                if _apply_move(state, (r, c), direction, bottom) is not None:
                    moves.append(((r, c), direction))
    return moves


# ---------------------------------------------------------------------------
# Public solver entry point
# ---------------------------------------------------------------------------


def solve(
    floor_grid: list[list[RawCell]],
    top_grid: list[list[RawCell]],
    max_depth: int = 20,
) -> dict:
    """Find the minimum number of player moves to win the given Phil level.

    Uses BFS over game states; each BFS level corresponds to one player move.
    The search is bounded by *max_depth* for hard or unsolvable levels.

    A level is won when a continuous orthogonal path of Phil-walkable cells
    connects the PHIL cell to the GOAL cell on the top layer.

    Args:
        floor_grid: 2-D list of bottom-layer cells.  Each cell is a BlockType
            (EMPTY, STATIC, HOLE, QUICKSAND, ICE_FLOOR, SPIKE_FLOOR) or a
            BlockSpec.  Floor cells carry their own static config — e.g. a
            QUICKSAND cell's ``capacity`` (default 2).
        top_grid: 2-D list of top-layer cells (BlockType or BlockSpec).  Valid
            types: EMPTY, STATIC, PHIL, GOAL, MOVE_ONE, ICE, BOUNCE, SPIKE.
            Must contain exactly one PHIL and one GOAL cell.
        max_depth: Maximum number of player moves to explore (default 20).

    Returns:
        A dict with keys:
            "solvable" (bool): True if a solution was found within max_depth.
            "min_moves" (int | None): Fewest moves needed, or None if unsolvable.
            "moves" (list | None): Ordered moves, each a dict with keys
                "block_row", "block_col", "direction"; None if unsolvable.
    """
    bottom = _bottom_grid_from_lists(floor_grid)
    top = _top_grid_from_lists(top_grid)

    initial_state = GameState(
        top=top,
        holes_filled=frozenset(),
        ice_holes_filled=frozenset(),
        quicksand_counts=(),
        floor_spikes_destroyed=frozenset(),
    )

    phil_pos, goal_pos = _find_phil_and_goal(top)
    if phil_pos is None or goal_pos is None:
        return {"solvable": False, "min_moves": None, "moves": None}

    # Already solved without any moves?
    if _phil_can_reach_goal(initial_state, phil_pos, goal_pos, bottom):
        return {"solvable": True, "min_moves": 0, "moves": []}

    # BFS: each node is (state, move_index, move_history).
    visited: set[GameState] = {initial_state}
    queue: deque[tuple[GameState, int, list[dict]]] = deque([(initial_state, 0, [])])

    while queue:
        current_state, move_index, history = queue.popleft()
        if move_index >= max_depth:
            continue

        for (block_pos, direction) in _get_valid_moves(current_state, bottom):
            next_state = _apply_move(current_state, block_pos, direction, bottom)
            if next_state is None or next_state in visited:
                continue

            visited.add(next_state)
            new_history = history + [
                {
                    "block_row": block_pos[0],
                    "block_col": block_pos[1],
                    "direction": direction,
                }
            ]

            if _phil_can_reach_goal(next_state, phil_pos, goal_pos, bottom):
                return {
                    "solvable": True,
                    "min_moves": move_index + 1,
                    "moves": new_history,
                }

            queue.append((next_state, move_index + 1, new_history))

    return {"solvable": False, "min_moves": None, "moves": None}
