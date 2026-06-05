from enum import Enum
from typing import Annotated
from pydantic import BaseModel, Field, ConfigDict


class BlockType(str, Enum):
    ICE = "ice"
    SPIKE = "spike"
    BOUNCE = "bounce"
    MOVE_ONE = "move_one"
    STATIC = "static"


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
