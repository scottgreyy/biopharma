"""FastAPI entrypoint for the admin (data-management) backend — port 8004.
The ONLY backend with read-write DB access; the three chat backends stay read-only."""
from __future__ import annotations
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from shared.auth.routes import router as auth_router
from shared.config import get_settings
from backend_admin.api.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if not Path(settings.db.assets_db_path).exists():
        raise RuntimeError(f"Database not found at {settings.db.assets_db_path}. Run: python -m shared.db.init_db")
    yield


app = FastAPI(
    title="Asset Management Assistant — Admin Backend",
    description="Data management: view, look up, add, delete, and upload assets.",
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
