"""
FastAPI routes for the ReAct backend.

Endpoints:
  GET  /health        — liveness + effective config (no auth; for probes/Streamlit).
  POST /chat          — run the agent, return answer + reasoning trace (auth).
  POST /chat/stream   — stream the final answer token-by-token (auth).

The trace is returned on /chat specifically so the Streamlit window (and the
demo video) can show the agent's tool-by-tool reasoning — the mandatory
"agentic behaviour" made visible.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from shared.config import get_settings
from shared.llm.ollama_client import chat_stream
from shared.auth.security import require_auth
from backend_react.core.agent import run_agent
from backend_react.core.prompts import SYSTEM_PROMPT
from backend_react.api.schemas import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
)

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
    s = get_settings()
    return HealthResponse(
        status="ok", model=s.llm.model, max_concurrency=s.llm.max_concurrency
    )


@router.post("/chat", response_model=ChatResponse, tags=["agent"])
async def chat_endpoint(
    req: ChatRequest, _: str = Depends(require_auth)
) -> ChatResponse:
    """Full agentic turn. Returns the answer plus the tool-call trace."""
    history = [t.model_dump() for t in req.history]
    result = await run_agent(req.message, history=history)
    return ChatResponse(answer=result.answer, trace=result.trace, steps=result.steps)


@router.post("/chat/stream", tags=["agent"])
async def chat_stream_endpoint(
    req: ChatRequest, _: str = Depends(require_auth)
) -> StreamingResponse:
    """Run the agent to a final answer, then STREAM that answer as it's
    regenerated for a live typing effect.

    Note the free-tier reality: because tool-calling needs the complete
    response to read tool_calls, the agentic phase is non-streamed; we then
    stream a final natural-language pass. Both phases go through the shared
    concurrency semaphore, so we never exceed 1 concurrent cloud call.
    """
    history = [t.model_dump() for t in req.history]
    result = await run_agent(req.message, history=history)

    # Re-render the final answer as a stream, grounded in the observations the
    # agent already gathered (passed as context), without re-calling tools.
    stream_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *history,
        {"role": "user", "content": req.message},
        {
            "role": "user",
            "content": (
                "Here is the information gathered by tools:\n"
                f"{json.dumps(result.trace, ensure_ascii=False)}\n\n"
                "Write the final answer to the original question for the user."
            ),
        },
    ]

    async def token_gen():
        async for token in chat_stream(stream_messages):
            yield token

    return StreamingResponse(token_gen(), media_type="text/plain")
