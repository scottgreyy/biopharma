"""Request/response models for the intent-router backend."""
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
    plan: dict[str, Any]           # the extracted intent plan (transparency)
    steps: list[dict[str, Any]]    # per-step execution trace


class HealthResponse(BaseModel):
    status: str
    model: str
    engine: str
    max_concurrency: int
