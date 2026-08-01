"""
FastAPI routes for the multi-agent supervisor backend (Approach 2).

  GET  /health   — liveness + effective config (incl. parallelism state).
  POST /chat     — run the LangGraph supervisor; return answer + routing +
                   worker trace so the multi-agent reasoning is visible.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from shared.auth.security import require_auth
from shared.config import get_settings
from backend_supervisor.core.graph import run_supervisor
from backend_supervisor.api.schemas import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
)

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
    s = get_settings()
    return HealthResponse(
        status="ok",
        model=s.llm.model,
        max_concurrency=s.llm.max_concurrency,
        parallel_workers=s.supervisor.parallel_workers,
    )


@router.post("/chat", response_model=ChatResponse, tags=["supervisor"])
async def chat_endpoint(
    req: ChatRequest, _: str = Depends(require_auth)
) -> ChatResponse:
    history = [t.model_dump() for t in req.history]
    result = await run_supervisor(req.message, history=history)
    return ChatResponse(
        answer=result["answer"],
        assignments=result["assignments"],
        reason=result["reason"],
        worker_outputs=result["worker_outputs"],
    )
