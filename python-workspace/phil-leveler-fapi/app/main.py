from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routers import levels, solver

app = FastAPI()

origins = [
    "http://localhost:3003",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods
    allow_headers=["*"],  # Allow all headers
)

app.include_router(levels.router)
app.include_router(solver.router)