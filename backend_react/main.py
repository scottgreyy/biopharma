"""
FastAPI application entrypoint for the ReAct (Approach 1) backend.

Run:
    uvicorn backend_react.main:app --reload --port 8001

Interactive API docs (OpenAPI) are auto-served at /docs and /redoc — this is
the "API documentation" deliverable for this backend.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.config import get_settings
from shared.auth.routes import router as auth_router
from backend_react.api.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail fast with a clear message if the DB hasn't been seeded yet.
    settings = get_settings()
    if not Path(settings.db.assets_db_path).exists():
        raise RuntimeError(
            f"Database not found at {settings.db.assets_db_path}. "
            f"Run:  python -m shared.db.init_db"
        )
    yield


app = FastAPI(
    title="Asset Management Assistant — ReAct Backend",
    description=(
        "Approach 1: a tool-augmented ReAct agent over Ollama Cloud native "
        "function calling. Retrieves IT asset information via typed, read-only "
        "database tools."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS: the three backends are consumed by a single Streamlit app. Lock the
# origins down to localhost dev ports here; widen via config for deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(router)
