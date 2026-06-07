from enum import Enum
from typing import Annotated
from pydantic import BaseModel, Field, ConfigDict


class BlockType(str, Enum):
    """All cell types used across both board layers.

    Each value is used as its JSON/string representation so serialization
    requires no extra mapping.

    Top-layer cells describe what occupies that grid position for the player
    and for Phil.  Bottom-layer cells describe the floor Phil stands on and
    the surface top-layer blocks slide across.  EMPTY and STATIC are shared
    between both layers with consistent semantics.
    """

    # ── Shared (valid on either layer) ───────────────────────────────────────

    EMPTY = "empty"
    """No block present.
    Top layer: Phil can walk through this cell.
    Bottom layer: solid, flat floor — Phil can stand here.
    """

    STATIC = "static"
    """Immovable iron block.
    Top layer: cannot be moved by the player or by game interactions;
               blocks Phil's path.
    Bottom layer: impassable floor fixture; Phil cannot step here and
                  top-layer blocks cannot slide through it.
    """

    # ── Top layer only ────────────────────────────────────────────────────────

    PHIL = "phil"
    """Phil's fixed starting position on the top layer.
    Phil never moves; exactly one cell per level carries this type.
    The solver treats this cell as walkable (Phil occupies it).
    """

    GOAL = "goal"
    """The win-condition target on the top layer.
    Exactly one cell per level.  The level is solved when Phil's
    flood-fill reaches this cell.
    """

    MOVE_ONE = "move_one"
    """Stone block — slides exactly one space in the chosen direction.
    The player can push it; it stops after one cell (or immediately if
    the destination is blocked or out-of-bounds).
    If the destination floor is a HOLE or QUICKSAND the block falls through.
    """

    ICE = "ice"
    """Ice block — slides exactly one space like MOVE_ONE.
    Special rule: when an ICE block falls into a HOLE on the bottom layer it
    fills the hole but leaves the floor slippery.  Any subsequent top-layer
    block that would land on that ice-filled cell instead keeps sliding in
    the same direction until it hits a wall, a blocking top-layer block, a
    non-ice floor, or another hole.
    """

    BOUNCE = "bounce"
    """Bumper block — cannot be moved directly by the player.
    Interaction: when a movable block is pushed into a cell *adjacent* to a
    BOUNCE block, if another movable block sits on the *opposite* side of the
    BOUNCE block along the same axis, that opposite block is bumped one cell
    further in the incoming direction.  The bump itself counts as part of the
    same player move (not an extra move).
    """

    SPIKE = "spike"
    """Spike block — cannot be moved directly by the player.
    Interaction: any top-layer block that slides into the cell occupied by a
    SPIKE is destroyed; the spike then retracts (its cell becomes EMPTY).
    The spike can optionally revive after a configurable number of player
    moves (see solver parameter spike_revival_moves; None = never revives).
    """

    # ── Bottom layer only ─────────────────────────────────────────────────────

    HOLE = "hole"
    """Pit in the floor.
    Phil cannot stand on or cross a HOLE.
    Any top-layer block that slides over a HOLE cell falls through:
      - MOVE_ONE / BOUNCE: block is removed from the top layer; the hole
        becomes a solid filled cell (walkable by Phil, treated as EMPTY).
      - ICE: block removed from top layer; hole becomes ICE_FLOOR (slippery).
      - SPIKE / STATIC: cannot fall (they are never slideable).
    """

    QUICKSAND = "quicksand"
    """Quicksand pit on the bottom layer.
    Phil cannot cross until exactly 2 top-layer blocks have fallen into it.
    Each falling block increments the fill count tracked in solver state.
    At fill count >= 2 the cell becomes walkable (treated as EMPTY floor).
    Blocks continue to be consumed until the threshold is reached.
    """

    ICE_FLOOR = "ice_floor"
    """Ice surface present on the bottom layer from the start of the level
    (as opposed to ICE_FLOOR cells created at runtime when an ICE block
    falls into a HOLE — those are tracked in solver state, not here).
    Phil can walk over ICE_FLOOR normally.
    Top-layer blocks that would land on an ICE_FLOOR cell keep sliding in
    the same direction until they leave the ice surface or hit an obstacle.
    """


class Level(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,  # Automatically strip whitespace from strings
        validate_assignment=True,  # Validate on assignment after creation
        use_enum_values=True,  # Use enum values in serialization
    )

    name: str | None = Field(
        default=None, description="Name of the level", max_length=100
    )
    created_by: int | None = Field(
        default=None,
        description="User ID of the level creator",
        gt=0,  # Must be positive
    )
    board_top: list[list[BlockType]] = Field(
        default_factory=list, description="2D array representing the top board layout"
    )
    board_bottom: list[list[BlockType]] = Field(default_factory=list)
