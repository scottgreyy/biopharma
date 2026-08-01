"""
Hand-rolled ReAct agent loop over Ollama native function calling.

Why hand-rolled (vs LangChain/LangGraph) for THIS backend:
  * Transparency — every Thought -> Action -> Observation step is captured in a
    `trace` the API returns, which is exactly what the demo video and README
    need to show, and what you defend in an interview.
  * Minimal deps and no framework version drift against Ollama's tool API.
  * ~1 file, ~1 loop. LangGraph earns its keep in the multi-agent backend
    (Approach 2), not here for a single agent with 5 tools.

Loop shape (native tool-calling variant of ReAct):
  1. Send messages + tool schemas to the model.
  2. If the model returns tool_calls -> execute each via the validated
     dispatcher, append the results as 'tool' role messages (Observations),
     and loop again (bounded by AGENT_MAX_STEPS).
  3. If the model returns plain content and no tool_calls -> that's the final
     answer; return it with the accumulated trace.

Concurrency: every model call goes through shared.llm.chat, which holds the
process-wide semaphore (=1 on free tier), so tool executions between calls are
fine but no two cloud calls are ever in flight at once.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from shared.config import get_settings
from shared.llm.ollama_client import chat
from backend_react.core.prompts import SYSTEM_PROMPT
from backend_react.core.tools import TOOL_SCHEMAS, dispatch_tool


@dataclass
class AgentResult:
    answer: str
    trace: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)  # full transcript
    steps: int = 0


def _extract_tool_calls(message: Any) -> list[dict[str, Any]]:
    """Normalize tool_calls from the Ollama response message into plain dicts
    of {name, arguments}. Handles both attribute-style and dict-style responses
    and argument payloads that arrive as a JSON string or an object."""
    raw = getattr(message, "tool_calls", None)
    if raw is None and isinstance(message, dict):
        raw = message.get("tool_calls")
    if not raw:
        return []
    calls: list[dict[str, Any]] = []
    for tc in raw:
        fn = getattr(tc, "function", None) or (tc.get("function") if isinstance(tc, dict) else None)
        if fn is None:
            continue
        name = getattr(fn, "name", None) or (fn.get("name") if isinstance(fn, dict) else None)
        args = getattr(fn, "arguments", None)
        if args is None and isinstance(fn, dict):
            args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except json.JSONDecodeError:
                args = {}
        calls.append({"name": name, "arguments": args or {}})
    return calls


def _message_to_dict(message: Any) -> dict[str, Any]:
    """Convert the assistant response message into a plain dict suitable for
    appending back into the messages list on the next turn."""
    if isinstance(message, dict):
        content = message.get("content", "") or ""
        tool_calls = message.get("tool_calls")
    else:
        content = getattr(message, "content", "") or ""
        tool_calls = getattr(message, "tool_calls", None)
    out: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        # Preserve tool_calls so the model sees its own prior actions.
        serializable = []
        for tc in tool_calls:
            fn = getattr(tc, "function", None) or (tc.get("function") if isinstance(tc, dict) else {})
            name = getattr(fn, "name", None) or (fn.get("name") if isinstance(fn, dict) else None)
            args = getattr(fn, "arguments", None)
            if args is None and isinstance(fn, dict):
                args = fn.get("arguments")
            serializable.append({"type": "function", "function": {"name": name, "arguments": args}})
        out["tool_calls"] = serializable
    return out


async def run_agent(
    user_message: str,
    history: list[dict[str, Any]] | None = None,
) -> AgentResult:
    """Run the ReAct loop for one user turn.

    `history` is the prior [{'role','content'}, ...] transcript (excluding the
    system prompt), enabling follow-up questions. Returns the final answer plus
    a step-by-step trace of tool calls and observations.
    """
    settings = get_settings()

    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    trace: list[dict[str, Any]] = []

    for step in range(1, settings.agent.max_steps + 1):
        response = await chat(messages, tools=TOOL_SCHEMAS)
        message = response["message"] if isinstance(response, dict) else response.message

        tool_calls = _extract_tool_calls(message)
        messages.append(_message_to_dict(message))

        if not tool_calls:
            # No further actions -> this is the final answer.
            content = messages[-1]["content"]
            return AgentResult(
                answer=content or "I couldn't produce an answer.",
                trace=trace,
                messages=messages,
                steps=step,
            )

        # Execute each requested tool; append observations for the next turn.
        for call in tool_calls:
            name, args = call["name"], call["arguments"]
            observation = await dispatch_tool(name, args)
            trace.append({"step": step, "tool": name, "arguments": args, "observation": observation})
            messages.append(
                {
                    "role": "tool",
                    "name": name,
                    "content": json.dumps(observation, ensure_ascii=False),
                }
            )

    # Step budget exhausted — ask the model once more for a best-effort answer
    # using what it has observed, without offering tools (forces a text reply).
    messages.append(
        {
            "role": "user",
            "content": "Based on the information gathered so far, give the best final answer you can.",
        }
    )
    response = await chat(messages)  # no tools -> text answer
    message = response["message"] if isinstance(response, dict) else response.message
    content = (message.get("content") if isinstance(message, dict) else message.content) or ""
    return AgentResult(
        answer=content or "I reached the step limit before finishing.",
        trace=trace,
        messages=messages,
        steps=settings.agent.max_steps,
    )
