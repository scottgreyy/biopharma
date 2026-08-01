"""
FastAPI routes for the intent-router backend (Approach 3).

  GET  /health   — liveness + effective config.
  POST /chat     — extract intent, execute against DuckDB, synthesize answer.
                   Returns the plan + per-step trace so the reasoning is visible.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from shared.auth.security import require_auth
from shared.config import get_settings
from backend_router.core.executor import run_router
from backend_router.api.schemas import ChatRequest, ChatResponse, HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
    s = get_settings()
    return HealthResponse(
        status="ok",
        model=s.llm.model,
        engine="duckdb",
        max_concurrency=s.llm.max_concurrency,
    )


@router.post("/chat", response_model=ChatResponse, tags=["router"])
async def chat_endpoint(
    req: ChatRequest, _: str = Depends(require_auth)
) -> ChatResponse:
    history = [t.model_dump() for t in req.history]
    result = await run_router(req.message, history=history)
    return ChatResponse(answer=result.answer, plan=result.plan, steps=result.steps)
