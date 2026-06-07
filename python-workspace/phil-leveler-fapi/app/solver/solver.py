"""BFS solver that finds the minimum number of player moves required to win a
Phil level.

A "move" is the player pushing one movable top-layer block (MOVE_ONE or ICE)
one step in a cardinal direction.  The level is won when a continuous
orthogonal path of Phil-walkable cells connects the PHIL cell to the GOAL
cell on the top layer (flood-fill check after every move).

Scoring / points are **not** computed here — they are a live game mechanic
only.  See `.claude/game-mechanics.md` at the repo root for the full rule
reference used to build this module.
"""

from __future__ import annotations

from collections import deque
from typing import Optional

from app.models.level import BlockType

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

# ---------------------------------------------------------------------------
# Type aliases for readability
# ---------------------------------------------------------------------------

# A row/column pair.
Pos = tuple[int, int]

# An immutable 2-D grid of BlockType values.
Grid = tuple[tuple[BlockType, ...], ...]

# Quicksand fill tracker: sorted tuple of ((row, col), fill_count) pairs.
QuicksandCounts = tuple[tuple[Pos, int], ...]

# Destroyed-spike record: (row, col, move_index_when_destroyed).
SpikeRecord = tuple[int, int, int]

# ---------------------------------------------------------------------------
# GameState
# ---------------------------------------------------------------------------


class GameState:
    """Immutable snapshot of the mutable parts of the board.

    The bottom layer never changes, so it is held outside the state and passed
    to every function that needs it.  Only the elements that *can* change
    during play are stored here so that the state can be hashed and used as a
    BFS visited key.

    Attributes:
        top: Current top-layer grid.  Immutable 2-D tuple of BlockType values.
        holes_filled: Positions of HOLE cells that have been filled by a
            non-ICE block.  Filled holes are solid and walkable.
        ice_holes_filled: Positions of HOLE cells that have been filled by an
            ICE block.  These cells are walkable but slippery — any top-layer
            block that would land here keeps sliding instead.
        quicksand_counts: How many top-layer blocks have fallen into each
            QUICKSAND cell.  A cell is walkable once its count reaches 2.
        destroyed_spikes: Which SPIKE cells have been retracted and when (move
            index).  Used to implement optional spike revival.
    """

    __slots__ = (
        "top",
        "holes_filled",
        "ice_holes_filled",
        "quicksand_counts",
        "destroyed_spikes",
    )

    def __init__(
        self,
        top: Grid,
        holes_filled: frozenset[Pos],
        ice_holes_filled: frozenset[Pos],
        quicksand_counts: QuicksandCounts,
        destroyed_spikes: tuple[SpikeRecord, ...],
    ) -> None:
        self.top = top
        self.holes_filled = holes_filled
        self.ice_holes_filled = ice_holes_filled
        self.quicksand_counts = quicksand_counts
        self.destroyed_spikes = destroyed_spikes

    # Equality and hashing let GameState be used as a dict key / set member.

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, GameState):
            return NotImplemented
        return (
            self.top == other.top
            and self.holes_filled == other.holes_filled
            and self.ice_holes_filled == other.ice_holes_filled
            and self.quicksand_counts == other.quicksand_counts
            and self.destroyed_spikes == other.destroyed_spikes
        )

    def __hash__(self) -> int:
        return hash(
            (
                self.top,
                self.holes_filled,
                self.ice_holes_filled,
                self.quicksand_counts,
                self.destroyed_spikes,
            )
        )

    def _key(self) -> tuple:
        return (
            self.top,
            self.holes_filled,
            self.ice_holes_filled,
            self.quicksand_counts,
            self.destroyed_spikes,
        )


# ---------------------------------------------------------------------------
# Grid helpers
# ---------------------------------------------------------------------------


def _grid_from_lists(rows: list[list[BlockType]]) -> Grid:
    """Convert a mutable 2-D list into an immutable tuple-of-tuples grid."""
    return tuple(tuple(row) for row in rows)


def _grid_to_lists(grid: Grid) -> list[list[BlockType]]:
    """Convert an immutable grid back to a mutable 2-D list for editing."""
    return [list(row) for row in grid]


def _in_bounds(grid: Grid, row: int, col: int) -> bool:
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
    bottom: Grid,
    holes_filled: frozenset[Pos],
    ice_holes_filled: frozenset[Pos],
    quicksand_counts: QuicksandCounts,
) -> BlockType:
    """Return the *effective* floor type at (row, col) after runtime changes.

    The bottom layer is immutable, but holes can be filled at runtime (by
    blocks falling in) and quicksand can become walkable after two fills.
    This function resolves the current effective floor type so the rest of
    the solver only needs to call it once per cell.

    Effective floor rules (in priority order):
    1. If the original cell is HOLE and it is in holes_filled → EMPTY.
    2. If the original cell is HOLE and it is in ice_holes_filled → ICE_FLOOR.
    3. If the original cell is QUICKSAND and fill count >= 2 → EMPTY.
    4. Otherwise return the original bottom-layer value.
    """
    pos = (row, col)
    original = bottom[row][col]
    if original == BlockType.HOLE:
        if pos in holes_filled:
            return BlockType.EMPTY
        if pos in ice_holes_filled:
            return BlockType.ICE_FLOOR
    if original == BlockType.QUICKSAND:
        if _qs_count(quicksand_counts, pos) >= 2:
            return BlockType.EMPTY
    return original


def _is_slippery_floor(floor: BlockType) -> bool:
    """Return True if the floor type causes top-layer blocks to keep sliding.

    Both ICE_FLOOR (placed on the bottom layer at level design time) and the
    runtime equivalent created when an ICE block fills a HOLE cause sliding.
    Phil is not affected — only sliding top-layer blocks are.
    """
    return floor == BlockType.ICE_FLOOR


def _is_phil_walkable(
    row: int,
    col: int,
    top_cell: BlockType,
    effective_floor: BlockType,
) -> bool:
    """Return True if Phil can occupy (row, col) given current board state.

    Phil can enter a cell when:
    - The top-layer cell is EMPTY, PHIL, or GOAL (nothing blocks him).
    - The effective floor is not HOLE, STATIC, or unfilled QUICKSAND.

    Callers must pass the *effective* floor (after applying runtime fill
    changes) rather than the raw bottom-layer value.
    """
    if top_cell not in (BlockType.EMPTY, BlockType.PHIL, BlockType.GOAL):
        return False
    if effective_floor in (BlockType.HOLE, BlockType.STATIC, BlockType.QUICKSAND):
        # QUICKSAND that reaches here still has count < 2 (unfilled),
        # because _effective_floor already returns EMPTY once count >= 2.
        return False
    return True


# ---------------------------------------------------------------------------
# Spike revival
# ---------------------------------------------------------------------------


def _apply_spike_revival(
    state: GameState,
    move_index: int,
    spike_revival_moves: Optional[int],
) -> GameState:
    """Restore any spikes that have served their retraction period.

    If spike_revival_moves is None, spikes never revive and this is a no-op.
    Otherwise, any spike whose (move_index - destroyed_at_move) >= threshold
    is placed back onto the top layer as a SPIKE cell.

    Args:
        state: Current game state.
        move_index: Index of the move *about to be applied* (0-based).
        spike_revival_moves: Number of player moves after which a retracted
            spike revives.  None means the spike never returns.

    Returns:
        A new GameState with revived spikes restored (or the same state if
        nothing changed).
    """
    if spike_revival_moves is None or not state.destroyed_spikes:
        return state

    surviving: list[SpikeRecord] = []
    revived: list[Pos] = []

    for row, col, destroyed_at in state.destroyed_spikes:
        if move_index - destroyed_at >= spike_revival_moves:
            revived.append((row, col))
        else:
            surviving.append((row, col, destroyed_at))

    if not revived:
        return state

    top_lists = _grid_to_lists(state.top)
    for row, col in revived:
        top_lists[row][col] = BlockType.SPIKE

    return GameState(
        top=_grid_from_lists(top_lists),
        holes_filled=state.holes_filled,
        ice_holes_filled=state.ice_holes_filled,
        quicksand_counts=state.quicksand_counts,
        destroyed_spikes=tuple(surviving),
    )


# ---------------------------------------------------------------------------
# Block destination computation (includes ice sliding)
# ---------------------------------------------------------------------------


def _compute_destination(
    block_pos: Pos,
    direction: str,
    top: Grid,
    bottom: Grid,
    holes_filled: frozenset[Pos],
    ice_holes_filled: frozenset[Pos],
    quicksand_counts: QuicksandCounts,
) -> Optional[tuple[str, int, int]]:
    """Compute where a block ends up after being pushed in *direction*.

    Handles normal one-step movement and the ice-sliding rule: if the block
    would land on a slippery floor (ICE_FLOOR or an ice-filled hole), it
    keeps advancing until a stopping condition is met.

    Stopping conditions (in order of priority):
    - Next cell is out-of-bounds → land at current cell.
    - Next cell has a top-layer block (non-EMPTY, non-GOAL) → land at current.
    - Next cell's effective floor is STATIC → land at current cell.
    - Next cell's effective floor is an unfilled HOLE or QUICKSAND → fall there.
    - Next cell's effective floor is non-slippery → land at next cell.
    - Next cell's effective floor is slippery → continue sliding.

    Args:
        block_pos: Current (row, col) of the block being pushed.
        direction: One of "up", "down", "left", "right".
        top: Current top-layer grid.
        bottom: Bottom-layer grid (immutable).
        holes_filled: Holes filled by non-ice blocks.
        ice_holes_filled: Holes filled by ICE blocks (slippery).
        quicksand_counts: Current quicksand fill counts.

    Returns:
        A tuple ("LAND", row, col) if the block slides to a new position,
        ("FALL", row, col) if it falls into a hole or quicksand, or None if
        the move is entirely blocked (illegal).
    """
    dr, dc = _DELTA[direction]
    cur_row, cur_col = block_pos

    # First step is always required — a move must advance at least one cell.
    next_row, next_col = cur_row + dr, cur_col + dc

    if not _in_bounds(top, next_row, next_col):
        return None  # Can't move off the board.

    next_top = top[next_row][next_col]
    # SPIKE is handled separately by the caller (spike collision removes both).
    # GOAL and PHIL act as walls for blocks — only Phil himself can occupy them.
    # Every other non-EMPTY cell (STATIC, BOUNCE, MOVE_ONE, ICE, PHIL, GOAL) blocks movement.
    if next_top not in (BlockType.EMPTY, BlockType.SPIKE):
        return None  # Destination occupied.

    next_floor = _effective_floor(
        next_row, next_col, bottom, holes_filled, ice_holes_filled, quicksand_counts
    )

    if next_floor == BlockType.STATIC:
        return None  # Can't slide into an iron floor cell.

    if next_floor in (BlockType.HOLE, BlockType.QUICKSAND):
        # Block falls on the very first step.
        return ("FALL", next_row, next_col)

    # Block lands on the first step; if the floor is slippery it keeps going.
    cur_row, cur_col = next_row, next_col

    while _is_slippery_floor(next_floor):
        # Try to advance one more cell.
        peek_row, peek_col = cur_row + dr, cur_col + dc

        if not _in_bounds(top, peek_row, peek_col):
            break  # Wall — stop here.

        peek_top = top[peek_row][peek_col]
        if peek_top not in (BlockType.EMPTY, BlockType.SPIKE):
            break  # Blocked by another top-layer block (including GOAL/PHIL) — stop here.

        peek_floor = _effective_floor(
            peek_row, peek_col, bottom, holes_filled, ice_holes_filled, quicksand_counts
        )

        if peek_floor == BlockType.STATIC:
            break  # Can't enter an iron floor cell — stop here.

        if peek_floor in (BlockType.HOLE, BlockType.QUICKSAND):
            # Falls into the next cell.
            return ("FALL", peek_row, peek_col)

        # Advance.
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
    bottom: Grid,
    move_index: int,
    spike_revival_moves: Optional[int],
) -> Optional[GameState]:
    """Apply a single player push and return the resulting GameState.

    Implements (in order):
    1. Spike revival — any spike past its revival threshold is restored first.
    2. Destination computation — including ice sliding.
    3. FALL handling — hole fill or quicksand increment.
    4. LAND handling — place block at destination.
    5. Spike collision — block + spike both removed; spike record appended.
    6. Bumper interaction — chains as far as consecutive bumpers allow.
    7. No-op rejection — returns None if state is unchanged.

    Args:
        state: Current game state.
        block_pos: (row, col) of the block the player is pushing.
        direction: Direction of the push ("up" / "down" / "left" / "right").
        bottom: Immutable bottom-layer grid.
        move_index: Index of this player move (used for spike revival tracking).
        spike_revival_moves: Move threshold for spike revival (None = never).

    Returns:
        The new GameState after the move, or None if the move is illegal or
        results in no change to the board.
    """
    # 1. Apply spike revival before processing the move.
    state = _apply_spike_revival(state, move_index, spike_revival_moves)

    block_row, block_col = block_pos
    block_type = state.top[block_row][block_col]

    # Only MOVE_ONE and ICE blocks can be pushed.  (Bumper recursion pushes
    # these same types, so this guard also applies inside bumper resolution.)
    if block_type not in (BlockType.MOVE_ONE, BlockType.ICE):
        return None

    # 2. Compute destination.
    dest = _compute_destination(
        block_pos,
        direction,
        state.top,
        bottom,
        state.holes_filled,
        state.ice_holes_filled,
        state.quicksand_counts,
    )

    if dest is None:
        return None  # Move is illegal.

    dest_kind, dest_row, dest_col = dest

    top_lists = _grid_to_lists(state.top)
    holes_filled = state.holes_filled
    ice_holes_filled = state.ice_holes_filled
    quicksand_counts = state.quicksand_counts
    destroyed_spikes = state.destroyed_spikes

    # Remove the block from its current position.
    top_lists[block_row][block_col] = BlockType.EMPTY

    if dest_kind == "FALL":
        # 3a. Block falls into a HOLE.
        original_floor = bottom[dest_row][dest_col]
        if original_floor == BlockType.HOLE:
            if block_type == BlockType.ICE:
                # ICE fills the hole with a slippery surface.
                ice_holes_filled = ice_holes_filled | {(dest_row, dest_col)}
            else:
                # Any other block fills the hole solidly.
                holes_filled = holes_filled | {(dest_row, dest_col)}

        # 3b. Block falls into QUICKSAND.
        elif original_floor == BlockType.QUICKSAND:
            quicksand_counts = _qs_increment(quicksand_counts, (dest_row, dest_col))
            # Block is consumed — it does not appear on the top layer.

    else:
        # dest_kind == "LAND"
        dest_top = state.top[dest_row][dest_col]

        # 5. Spike collision — block and spike cancel each other.
        if dest_top == BlockType.SPIKE:
            # Both removed; spike recorded as destroyed.
            top_lists[dest_row][dest_col] = BlockType.EMPTY
            destroyed_spikes = destroyed_spikes + ((dest_row, dest_col, move_index),)

        else:
            # 4. Normal landing — place the block.
            top_lists[dest_row][dest_col] = block_type

            # 6. Bumper interaction — chains through consecutive bumpers.
            new_top = _grid_from_lists(top_lists)
            intermediate = GameState(
                top=new_top,
                holes_filled=holes_filled,
                ice_holes_filled=ice_holes_filled,
                quicksand_counts=quicksand_counts,
                destroyed_spikes=destroyed_spikes,
            )
            bumped = _resolve_bumper(
                intermediate,
                (dest_row, dest_col),
                direction,
                bottom,
                move_index,
                spike_revival_moves,
            )
            if bumped is not None:
                # The bumper chain produced a further state change.
                # 7. Check for no-op after full resolution.
                if bumped._key() == state._key():
                    return None
                return bumped

    new_top = _grid_from_lists(top_lists)
    new_state = GameState(
        top=new_top,
        holes_filled=holes_filled,
        ice_holes_filled=ice_holes_filled,
        quicksand_counts=quicksand_counts,
        destroyed_spikes=destroyed_spikes,
    )

    # 7. Reject no-ops.
    if new_state._key() == state._key():
        return None

    return new_state


def _resolve_bumper(
    state: GameState,
    landed_pos: Pos,
    direction: str,
    bottom: Grid,
    move_index: int,
    spike_revival_moves: Optional[int],
) -> Optional[GameState]:
    """Check for a bumper interaction after a block lands at *landed_pos*.

    Rule: when a movable block lands in a cell adjacent to a BOUNCE block,
    and another movable block sits on the *opposite* side of that BOUNCE block
    along the same axis, the opposite block is bumped one cell further in the
    same direction.

    The bump is part of the same player move — it is not an extra player move.
    Bumpers chain: a bumped block that lands adjacent to another BOUNCE block
    triggers a further bump, and so on down a row of consecutive bumpers.

    Args:
        state: State after the block has landed (but before bumper resolution).
        landed_pos: Where the block just landed.
        direction: The direction the player pushed (same direction used for bump).
        bottom: Immutable bottom-layer grid.
        move_index: Current move index.
        spike_revival_moves: Spike revival threshold.

    Returns:
        New state after the bump, or None if no bumper interaction occurred.
    """
    dr, dc = _DELTA[direction]
    land_row, land_col = landed_pos

    # The BOUNCE block would be one step further in the push direction.
    bounce_row, bounce_col = land_row + dr, land_col + dc
    if not _in_bounds(state.top, bounce_row, bounce_col):
        return None
    if state.top[bounce_row][bounce_col] != BlockType.BOUNCE:
        return None

    # The block to be bumped is one step past the BOUNCE block.
    target_row, target_col = bounce_row + dr, bounce_col + dc
    if not _in_bounds(state.top, target_row, target_col):
        return None
    target_type = state.top[target_row][target_col]
    if target_type not in (BlockType.MOVE_ONE, BlockType.ICE):
        return None  # Only movable blocks can be bumped.

    # Bump the target block by recursing.  The bumped block lands via
    # _apply_move, which itself re-runs bumper resolution — so a row of
    # consecutive bumpers chains.  This terminates: every bump advances a
    # block strictly further along the (fixed) push direction on a finite
    # board, so the chain runs out at a boundary or a non-bumper cell.
    return _apply_move(
        state,
        (target_row, target_col),
        direction,
        bottom,
        move_index,
        spike_revival_moves,
    )


# ---------------------------------------------------------------------------
# Phil reachability (win condition check)
# ---------------------------------------------------------------------------


def _find_phil_and_goal(top: Grid) -> tuple[Optional[Pos], Optional[Pos]]:
    """Scan the top layer and return (phil_pos, goal_pos).

    Returns (None, None) elements for whichever special cell is absent.
    A valid level has exactly one PHIL and one GOAL cell.
    """
    phil_pos: Optional[Pos] = None
    goal_pos: Optional[Pos] = None
    for r, row in enumerate(top):
        for c, cell in enumerate(row):
            if cell == BlockType.PHIL:
                phil_pos = (r, c)
            elif cell == BlockType.GOAL:
                goal_pos = (r, c)
    return phil_pos, goal_pos


def _phil_can_reach_goal(
    state: GameState,
    phil_pos: Pos,
    goal_pos: Pos,
    bottom: Grid,
) -> bool:
    """Return True if Phil can reach the GOAL from his starting position.

    Uses BFS flood-fill from *phil_pos* over cells walkable by Phil.  Phil is
    walkable at (r, c) when:
    - The top-layer cell is EMPTY, PHIL, or GOAL.
    - The effective floor is not HOLE, STATIC, or unfilled QUICKSAND.

    Phil's starting cell (PHIL) always satisfies both conditions.

    Args:
        state: Current game state.
        phil_pos: Phil's fixed position on the top layer.
        goal_pos: Position of the GOAL cell.
        bottom: Immutable bottom-layer grid.
    """
    visited: set[Pos] = set()
    queue: deque[Pos] = deque([phil_pos])
    visited.add(phil_pos)

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
                nr, nc, bottom,
                state.holes_filled,
                state.ice_holes_filled,
                state.quicksand_counts,
            )
            if _is_phil_walkable(nr, nc, state.top[nr][nc], floor):
                visited.add((nr, nc))
                queue.append((nr, nc))

    return False


# ---------------------------------------------------------------------------
# Valid-move enumeration
# ---------------------------------------------------------------------------


def _get_valid_moves(
    state: GameState,
    bottom: Grid,
    move_index: int,
    spike_revival_moves: Optional[int],
) -> list[tuple[Pos, str]]:
    """Return all legal (block_position, direction) pairs for the current state.

    A move is legal if _apply_move returns a non-None state that differs from
    the current state.

    Args:
        state: Current game state.
        bottom: Immutable bottom-layer grid.
        move_index: Index of the move about to be made.
        spike_revival_moves: Spike revival threshold.
    """
    moves: list[tuple[Pos, str]] = []
    for r, row in enumerate(state.top):
        for c, cell in enumerate(row):
            if cell not in (BlockType.MOVE_ONE, BlockType.ICE):
                continue
            for direction in DIRECTIONS:
                result = _apply_move(
                    state,
                    (r, c),
                    direction,
                    bottom,
                    move_index,
                    spike_revival_moves,
                )
                if result is not None:
                    moves.append(((r, c), direction))
    return moves


# ---------------------------------------------------------------------------
# Public solver entry point
# ---------------------------------------------------------------------------


def solve(
    floor_grid: list[list[BlockType]],
    top_grid: list[list[BlockType]],
    max_depth: int = 20,
    spike_revival_moves: Optional[int] = None,
) -> dict:
    """Find the minimum number of player moves to win the given Phil level.

    Uses BFS over game states.  Each BFS level corresponds to one player move.
    The search is bounded by *max_depth* to handle hard or unsolvable levels.

    A level is won when a continuous orthogonal path of Phil-walkable cells
    connects the PHIL cell to the GOAL cell on the top layer.

    Args:
        floor_grid: 2-D list of BlockType values representing the bottom layer.
            Valid values: EMPTY, STATIC, HOLE, QUICKSAND, ICE_FLOOR.
        top_grid: 2-D list of BlockType values representing the top layer.
            Valid values: EMPTY, STATIC, PHIL, GOAL, MOVE_ONE, ICE, BOUNCE, SPIKE.
            Must contain exactly one PHIL and one GOAL cell.
        max_depth: Maximum number of player moves to explore before giving up.
            Default is 20.  Raise this for complex levels at the cost of
            potentially much longer runtimes.
        spike_revival_moves: Number of player moves after which a retracted
            SPIKE revives.  None (the default) means spikes never return.

    Returns:
        A dict with the following keys:
            "solvable" (bool): True if a solution was found within max_depth.
            "min_moves" (int | None): Fewest moves needed, or None if unsolvable.
            "moves" (list | None): Ordered list of moves, each a dict with keys
                "block_row" (int), "block_col" (int), "direction" (str).
                None if unsolvable.
    """
    bottom = _grid_from_lists(floor_grid)
    top = _grid_from_lists(top_grid)

    initial_state = GameState(
        top=top,
        holes_filled=frozenset(),
        ice_holes_filled=frozenset(),
        quicksand_counts=(),
        destroyed_spikes=(),
    )

    phil_pos, goal_pos = _find_phil_and_goal(top)

    if phil_pos is None or goal_pos is None:
        return {"solvable": False, "min_moves": None, "moves": None}

    # Check if the level is already solved without any moves.
    if _phil_can_reach_goal(initial_state, phil_pos, goal_pos, bottom):
        return {"solvable": True, "min_moves": 0, "moves": []}

    # BFS: each node is (state, move_index, move_history).
    # move_history is a list of {"block_row", "block_col", "direction"} dicts.
    visited: set[GameState] = {initial_state}
    queue: deque[tuple[GameState, int, list[dict]]] = deque(
        [(initial_state, 0, [])]
    )

    while queue:
        current_state, move_index, history = queue.popleft()

        if move_index >= max_depth:
            continue

        for (block_pos, direction) in _get_valid_moves(
            current_state, bottom, move_index, spike_revival_moves
        ):
            next_state = _apply_move(
                current_state,
                block_pos,
                direction,
                bottom,
                move_index,
                spike_revival_moves,
            )
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
