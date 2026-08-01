"""
LLM adapter for the LangGraph supervisor nodes.

Design decision (important): LangGraph provides the GRAPH (state, nodes,
conditional routing). For the actual model calls we reuse the project's proven
shared.llm client rather than langchain-ollama's ChatOllama. Two reasons:

  1. The shared client already enforces the Ollama Cloud concurrency semaphore
     (free-tier = 1). Going through ChatOllama would open a second, ungoverned
     path to the cloud and could exceed the tier limit.
  2. ChatOllama's cloud support depends on client_kwargs header forwarding to
     ollama.com, which varies by version. Our client is already verified.

If you prefer native ChatOllama later, only this file changes — the graph in
graph.py is agnostic to how a node talks to the model.

This module exposes two helpers the nodes use:
  * complete_json(system, user)  -> parsed dict (for the supervisor's routing
    decision and structured worker output), with one repair retry.
  * complete_text(system, user)  -> plain string (for final synthesis).
"""
from __future__ import annotations

import json
from typing import Any

from shared.llm.ollama_client import chat


def _content(response: Any) -> str:
    msg = response["message"] if isinstance(response, dict) else response.message
    if isinstance(msg, dict):
        return msg.get("content", "") or ""
    return getattr(msg, "content", "") or ""


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        parts = t.split("```")
        if len(parts) >= 2:
            t = parts[1]
            if t.lstrip().lower().startswith("json"):
                t = t.lstrip()[4:]
    return t.strip()


async def complete_text(system: str, user: str) -> str:
    """Single text completion through the semaphore-gated shared client."""
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    response = await chat(messages)
    return _content(response)


async def complete_json(system: str, user: str) -> dict[str, Any]:
    """Text completion expected to be JSON. One repair retry on parse failure."""
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    response = await chat(messages)
    raw = _content(response)
    try:
        return json.loads(_strip_fences(raw))
    except (json.JSONDecodeError, ValueError):
        messages.append({"role": "assistant", "content": raw})
        messages.append(
            {"role": "user", "content": "Output ONLY valid JSON for the requested schema. No prose, no fences."}
        )
        response = await chat(messages)
        return json.loads(_strip_fences(_content(response)))
