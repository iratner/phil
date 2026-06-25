from enum import Enum
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
    """Spike block — a cube with up to five independently spiked faces.

    The five faces are UP, NORTH, SOUTH, EAST and WEST (the bottom face is
    never spiked).  Which faces carry spikes is configurable per block via the
    ``spiked_faces`` field of :class:`BlockSpec`; a bare ``"spike"`` cell
    defaults to all five faces spiked.

    Interaction: when a movable block whose ``can_destroy_spike`` flag is true
    slides into one of the spiked faces, the spikes on *that face only* are
    destroyed.  Whether the incoming block itself is consumed is governed by
    its ``is_destroyed_by_spike`` flag.  A spike block cannot be pushed by the
    player while any face still carries spikes; once *all* faces are clear it
    becomes an ordinary movable (MOVE_ONE) block.

    Passability: Phil cannot occupy a cell that sits directly against a spiked
    face.  Destroying a face frees the cell adjacent to it.

    Spikes never revive — destroyed faces stay destroyed for the level.
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

    SPIKE_FLOOR = "spike_floor"
    """Ground-level spike — a spike block embedded in the floor.

    Only its top (UP) face is exposed and spiked.  Phil cannot stand on the
    cell while the top face carries spikes, and a top-layer block cannot pass
    over it.  A movable block with ``can_destroy_spike`` true that slides onto
    the cell destroys the top face (subject to its ``is_destroyed_by_spike``
    flag); once destroyed the cell behaves as plain EMPTY floor.  Shares the
    spike mechanics of :class:`BlockType.SPIKE` but is restricted to the
    bottom layer with a single face.
    """


class Face(str, Enum):
    """The spiked faces of a SPIKE / SPIKE_FLOOR block (bottom face excluded).

    Each value is its own JSON/string representation.  ``UP`` points out of the
    board (it guards the block's own cell when the spike is ground-level); the
    four cardinal faces guard the orthogonally-adjacent cell in their direction.
    """

    UP = "up"
    NORTH = "north"
    SOUTH = "south"
    EAST = "east"
    WEST = "west"


class BlockSpec(BaseModel):
    """A single cell that carries per-block properties beyond its type.

    A board cell may be expressed either as a bare ``BlockType`` string (which
    takes the type's default properties) or as this richer object when a level
    needs to override face configuration or spike-interaction behaviour.

    Unset (``None``) fields are resolved to type-appropriate defaults by the
    solver:
      - ``can_destroy_spike`` → true for movable blocks (MOVE_ONE / ICE),
        false otherwise.
      - ``is_destroyed_by_spike`` → true (a block that hits a live spike face
        is consumed by default).
      - ``spiked_faces`` → all five faces for SPIKE, the single UP face for
        SPIKE_FLOOR, empty otherwise.
    """

    model_config = ConfigDict(use_enum_values=True)

    type: BlockType = Field(description="The cell's block type.")
    can_destroy_spike: bool | None = Field(
        default=None,
        description="If true, this block destroys a spike face it slides into.",
    )
    is_destroyed_by_spike: bool | None = Field(
        default=None,
        description="If true, this block is consumed when it hits a live spike face.",
    )
    spiked_faces: list[Face] | None = Field(
        default=None,
        description="Which faces carry spikes (SPIKE / SPIKE_FLOOR only).",
    )


# A board cell is either a bare BlockType string or a BlockSpec object.
Cell = BlockType | BlockSpec


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
    board_top: list[list[Cell]] = Field(
        default_factory=list,
        description="2D array representing the top board layout. Each cell is a "
        "BlockType string or a BlockSpec object.",
    )
    board_bottom: list[list[Cell]] = Field(default_factory=list)
