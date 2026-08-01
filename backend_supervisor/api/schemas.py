"""Request/response models for the supervisor backend."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    history: list[ChatTurn] = Field(default_factory=list)


class ChatResponse(BaseModel):
    answer: str
    assignments: list[dict[str, Any]]     # supervisor routing decision
    reason: str
    worker_outputs: list[dict[str, Any]]  # per-worker trace


class HealthResponse(BaseModel):
    status: str
    model: str
    max_concurrency: int
    parallel_workers: bool
