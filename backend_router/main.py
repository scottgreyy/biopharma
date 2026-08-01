"""
FastAPI entrypoint for the intent-router backend (Approach 3, DuckDB).

Run:
    uvicorn backend_router.main:app --reload --port 8003

Interactive API docs at /docs.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.auth.routes import router as auth_router
from shared.config import get_settings
from backend_router.api.routes import router
from backend_router.core.duckdb_engine import get_connection


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if not Path(settings.db.assets_csv).exists():
        raise RuntimeError(
            f"Seed CSV not found at {settings.db.assets_csv}. "
            f"It ships in data/; check your paths."
        )
    # Warm the in-memory DuckDB (loads the CSV once) so the first request is fast
    # and any load error surfaces at startup, not mid-conversation.
    get_connection()
    yield


app = FastAPI(
    title="Asset Management Assistant — Intent-Router Backend",
    description=(
        "Approach 3: the LLM acts purely as a JSON intent + entity extractor. "
        "Validated intents map to a fixed library of parameterized DuckDB "
        "queries. The model never writes SQL."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(router)
