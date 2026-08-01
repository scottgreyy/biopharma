"""
FastAPI entrypoint for the multi-agent supervisor backend (Approach 2, LangGraph).

Run:
    uvicorn backend_supervisor.main:app --reload --port 8002

Interactive API docs at /docs.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.auth.routes import router as auth_router
from shared.config import get_settings
from backend_supervisor.api.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if not Path(settings.db.assets_db_path).exists():
        raise RuntimeError(
            f"Database not found at {settings.db.assets_db_path}. "
            f"Run:  python -m shared.db.init_db"
        )
    yield


app = FastAPI(
    title="Asset Management Assistant — Supervisor Backend",
    description=(
        "Approach 2: a LangGraph multi-agent supervisor. A supervisor node "
        "routes each query to specialized Inventory/People workers with minimal "
        "per-worker context (token-optimized), then synthesizes the answer. "
        "Workers run sequentially on free tier and parallelize automatically "
        "when the concurrency limit is raised."
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
