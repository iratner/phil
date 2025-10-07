import re
from fastapi import APIRouter
from app.models.level import Level

router = APIRouter(
    prefix="/levels",
    tags=["levels"],
    responses={404: {"description": "Not found"}},
)


@router.get("/")
async def get_levels():
    return {"levels": ["easy", "medium", "hard"]}


@router.get("/{level_id}")
async def get_level(level_id: str):
    return {"level_id": level_id, "details": "Level details here"}


@router.post("/")
async def create_level(level: Level):
    return {"message": "Level created", "level": level}
