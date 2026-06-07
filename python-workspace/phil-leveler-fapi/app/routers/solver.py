"""FastAPI router exposing the Phil level solver.

POST /solver/solve accepts a level (floor + top 2-D grids of BlockType values)
and returns the minimum number of player moves required to win, along with the
full move sequence.

See app/solver/solver.py for the full rule reference and algorithm details.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.models.level import BlockType
from app.solver.solver import solve

router = APIRouter(prefix="/solver", tags=["solver"])


class LevelSolveRequest(BaseModel):
    """Input model for the solve endpoint.

    Both grids must have the same dimensions.  floor uses bottom-layer cell
    types (EMPTY, STATIC, HOLE, QUICKSAND, ICE_FLOOR) and top uses top-layer
    cell types (EMPTY, STATIC, PHIL, GOAL, MOVE_ONE, ICE, BOUNCE, SPIKE).
    The top grid must contain exactly one PHIL cell and one GOAL cell.

    Attributes:
        floor: 2-D array representing the bottom (floor) layer.
        top: 2-D array representing the top (block) layer.
        max_depth: Maximum player moves to explore before declaring unsolvable.
            Raise for complex levels; lower for faster timeouts on simpler ones.
        spike_revival_moves: Number of player moves after which a retracted
            SPIKE revives.  Omit or pass null for spikes that never revive.
    """

    floor: list[list[BlockType]] = Field(
        description="2-D array of bottom-layer cell types."
    )
    top: list[list[BlockType]] = Field(
        description="2-D array of top-layer cell types. Must contain exactly one PHIL and one GOAL."
    )
    max_depth: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum player moves to explore (default 20).",
    )
    spike_revival_moves: Optional[int] = Field(
        default=None,
        ge=1,
        description="Moves after which retracted spikes revive. Null means never.",
    )


class MoveResult(BaseModel):
    """A single player move in the solution sequence.

    Attributes:
        block_row: Row index of the block being pushed.
        block_col: Column index of the block being pushed.
        direction: Direction of the push: "up", "down", "left", or "right".
    """

    block_row: int
    block_col: int
    direction: str


class SolveResult(BaseModel):
    """Response from the solve endpoint.

    Attributes:
        solvable: True if a solution was found within max_depth moves.
        min_moves: Fewest player moves needed to win, or null if unsolvable.
        moves: Ordered list of moves that produce the shortest solution, or
            null if unsolvable.  Each move identifies the block and direction.
    """

    solvable: bool
    min_moves: Optional[int]
    moves: Optional[list[MoveResult]]


@router.post("/solve", response_model=SolveResult)
def solve_level(request: LevelSolveRequest) -> SolveResult:
    """Find the minimum number of player moves to win a Phil level.

    Accepts the level as two 2-D grids of BlockType values and runs BFS over
    all reachable game states up to *max_depth* player moves deep.  Returns
    the shortest move sequence that creates a walkable path from PHIL to GOAL.

    Returns HTTP 422 (Unprocessable Entity) if the grids are missing required
    cells (PHIL or GOAL) — validation happens inside the solver and is surfaced
    as an HTTP error here.
    """
    if not request.floor or not request.top:
        raise HTTPException(status_code=422, detail="floor and top grids must be non-empty.")

    result = solve(
        floor_grid=request.floor,
        top_grid=request.top,
        max_depth=request.max_depth,
        spike_revival_moves=request.spike_revival_moves,
    )

    if result["solvable"]:
        moves = [MoveResult(**m) for m in result["moves"]]
    else:
        moves = None

    return SolveResult(
        solvable=result["solvable"],
        min_moves=result["min_moves"],
        moves=moves,
    )
