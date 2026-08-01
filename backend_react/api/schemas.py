"""Request/response models for the ReAct backend API."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="The user's question.")
    history: list[ChatTurn] = Field(
        default_factory=list,
        description="Prior turns for follow-up context (user/assistant only).",
    )


class TraceStep(BaseModel):
    step: int
    tool: str
    arguments: dict[str, Any]
    observation: dict[str, Any]


class ChatResponse(BaseModel):
    answer: str
    trace: list[TraceStep]
    steps: int


class HealthResponse(BaseModel):
    status: str
    model: str
    max_concurrency: int
