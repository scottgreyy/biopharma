"""
Shared async Ollama Cloud client.

Two responsibilities, both cross-cutting for all three backends:
  1. Build an AsyncClient bound to Ollama Cloud with the bearer key from env
     (never hardcoded — pulled from settings which pulls from OLLAMA_API_KEY).
  2. Enforce the cloud concurrency limit via a module-level asyncio.Semaphore.

Why AsyncClient (not Client): the sync client blocks the event loop, which
would serialize FastAPI's request handling. AsyncClient lets the server await
the (multi-second, network-bound) LLM call while serving other requests.

Why a semaphore, not a boolean flag: Ollama Cloud Free permits 1 concurrent
cloud model. `Semaphore(1)` serializes every LLM call process-wide — including
across the multi-agent backend's sub-agents and across simultaneous Streamlit
windows. Raising LLM_MAX_CONCURRENCY to 3/10 (Pro/Max) automatically permits
that many in-flight calls with no other change. A boolean couldn't express
"allow exactly N".
"""
from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Any

from ollama import AsyncClient

from shared.config import get_settings

# Process-wide gate on concurrent cloud LLM calls. Sized from config once.
_CONCURRENCY_GATE = asyncio.Semaphore(get_settings().llm.max_concurrency)


@lru_cache
def get_client() -> AsyncClient:
    """Cached AsyncClient. Header carries the bearer key from the environment."""
    settings = get_settings()
    return AsyncClient(
        host=settings.llm.host,
        headers={"Authorization": f"Bearer {settings.llm.api_key}"},
        timeout=settings.llm.timeout_seconds,
    )


async def chat(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    *,
    model: str | None = None,
    **kwargs: Any,
) -> Any:
    """Single non-streaming chat completion, gated by the concurrency semaphore.

    Returns the raw Ollama response object. Callers inspect
    `response.message.tool_calls` (native function calling) and
    `response.message.content`.
    """
    settings = get_settings()
    client = get_client()
    async with _CONCURRENCY_GATE:
        return await client.chat(
            model=model or settings.llm.model,
            messages=messages,
            tools=tools,
            **kwargs,
        )


async def chat_stream(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    **kwargs: Any,
):
    """Streaming chat for the final natural-language answer (no tools). Yields
    partial content strings. Held under the semaphore for the whole stream so a
    free-tier account never opens a second concurrent cloud call mid-stream."""
    settings = get_settings()
    client = get_client()
    async with _CONCURRENCY_GATE:
        async for part in await client.chat(
            model=model or settings.llm.model,
            messages=messages,
            stream=True,
            **kwargs,
        ):
            token = part.get("message", {}).get("content", "")
            if token:
                yield token
