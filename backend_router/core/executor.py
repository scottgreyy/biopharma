"""
Execution engine for the intent-router backend.

Flow per user turn:
  1. EXTRACT — ask the LLM for a RouterPlan (JSON only). Parse + validate with
     Pydantic. Invalid JSON -> one repair retry -> graceful fallback.
  2. EXECUTE — for each plan step, map intent -> QUERY_LIBRARY template, resolve
     any `from_previous` chaining deterministically, bind params via DuckDB
     $named parameters, run read-only. Unknown/unsupported intents short-circuit.
  3. SYNTHESIZE — hand the collected results back to the LLM to write the final
     natural-language answer.

The LLM never emits SQL and never sees the templates. Security is closed by
construction: intent is a validated enum, params are bound values.

Concurrency: every LLM call goes through shared.llm.chat (semaphore-gated), so
free-tier concurrency=1 is respected. DuckDB calls are synchronous and fast; we
run them inline between the two LLM calls.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from shared.config import get_settings
from shared.llm.ollama_client import chat
from backend_router.core.duckdb_engine import execute_named
from backend_router.core.intent import IntentName, RouterPlan
from backend_router.core.prompts import (
    INTENT_SYSTEM_PROMPT,
    SYNTHESIS_SYSTEM_PROMPT,
)
from backend_router.core.query_library import ALL_PARAM_KEYS, QUERY_LIBRARY


@dataclass
class RouterResult:
    answer: str
    plan: dict[str, Any]
    steps: list[dict[str, Any]] = field(default_factory=list)  # per-step trace


def _strip_fences(text: str) -> str:
    """Remove accidental ```json fences so json.loads succeeds."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)
        t = t[1] if len(t) > 1 else text
        if t.lstrip().lower().startswith("json"):
            t = t.lstrip()[4:]
    return t.strip()


async def _extract_plan(user_message: str, history: list[dict[str, Any]]) -> RouterPlan:
    """LLM call #1: get a validated RouterPlan. One repair retry on bad JSON."""
    messages = [
        {"role": "system", "content": INTENT_SYSTEM_PROMPT},
        *history,
        {"role": "user", "content": user_message},
    ]
    response = await chat(messages)
    raw = _content(response)

    try:
        return RouterPlan.model_validate_json(_strip_fences(raw))
    except (ValidationError, json.JSONDecodeError, ValueError):
        # Repair attempt: tell the model its output was invalid, ask again.
        messages.append({"role": "assistant", "content": raw})
        messages.append(
            {
                "role": "user",
                "content": "That was not valid JSON for the schema. Output ONLY the corrected JSON object, nothing else.",
            }
        )
        response = await chat(messages)
        raw2 = _content(response)
        return RouterPlan.model_validate_json(_strip_fences(raw2))


def _content(response: Any) -> str:
    msg = response["message"] if isinstance(response, dict) else response.message
    if isinstance(msg, dict):
        return msg.get("content", "") or ""
    return getattr(msg, "content", "") or ""


def _run_step(intent: IntentName, params: dict[str, Any]) -> dict[str, Any]:
    """Execute one plan step against DuckDB, or short-circuit unsupported."""
    if intent == IntentName.unsupported:
        return {"intent": intent.value, "unsupported": True, "rows": []}

    template = QUERY_LIBRARY.get(intent.value)
    if template is None:
        return {"intent": intent.value, "error": "unknown intent", "rows": []}

    # Pass the full param set; unused keys default to None -> DuckDB NULL, which
    # the templates' COALESCE/NULL guards ignore. Bind only known keys.
    bind = {k: params.get(k) for k in ALL_PARAM_KEYS}
    rows = execute_named(template, bind)
    return {"intent": intent.value, "params": bind, "rows": rows}


async def run_router(
    user_message: str,
    history: list[dict[str, Any]] | None = None,
) -> RouterResult:
    """Full intent-router turn: extract -> execute (with chaining) -> synthesize."""
    settings = get_settings()
    history = history or []

    # ---- 1. EXTRACT --------------------------------------------------------
    try:
        plan = await _extract_plan(user_message, history)
    except Exception as exc:  # noqa: BLE001 — surface a graceful failure
        return RouterResult(
            answer=(
                "I couldn't understand that request well enough to answer. "
                "Try asking about an asset code, an employee, or assets in a city."
            ),
            plan={"error": f"plan extraction failed: {exc}"},
            steps=[],
        )

    # ---- 2. EXECUTE (bounded, with deterministic chaining) -----------------
    executed: list[dict[str, Any]] = []
    max_steps = settings.router.max_chained_intents
    prev_rows: list[dict[str, Any]] = []

    for step in plan.steps[:max_steps]:
        params = step.params.model_dump()

        # Resolve chaining: pull fields from the previous step's first row.
        if step.from_previous and prev_rows:
            src = prev_rows[0]
            for target_param, source_field in step.from_previous.items():
                if source_field in src:
                    params[target_param] = src[source_field]

        result = _run_step(step.intent, params)
        executed.append(result)
        prev_rows = result.get("rows", []) or prev_rows  # keep last non-empty

    # ---- 3. SYNTHESIZE -----------------------------------------------------
    synthesis_input = {
        "question": user_message,
        "intent_summary": plan.intent_summary,
        "results": executed,
    }
    synth_messages = [
        {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "User question and retrieved results (JSON):\n"
                + json.dumps(synthesis_input, ensure_ascii=False, default=str)
                + "\n\nWrite the final answer."
            ),
        },
    ]
    response = await chat(synth_messages)
    answer = _content(response) or "I couldn't produce an answer."

    return RouterResult(answer=answer, plan=plan.model_dump(), steps=executed)
