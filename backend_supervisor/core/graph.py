"""
LangGraph StateGraph for the multi-agent supervisor (Approach 2).

Graph shape:
    START -> supervisor -> dispatch_workers -> synthesize -> END

  * supervisor       : LLM emits a compact routing plan (which workers + each
                       worker's minimal sub_task/entities).
  * dispatch_workers : runs the assigned workers. On free tier (concurrency=1)
                       they run sequentially through the shared semaphore; when
                       LLM__MAX_CONCURRENCY>1 AND SUPERVISOR__PARALLEL_WORKERS,
                       independent workers run concurrently via asyncio.gather —
                       SAME code path, the semaphore is the throttle.
  * synthesize       : LLM writes the final answer from the compact worker
                       outputs only.

Why LangGraph here (and not a hand-rolled loop like Backend 1): the supervisor
pattern is genuinely a graph — typed shared state, conditional fan-out to
workers, a join, then synthesis. Using StateGraph makes that structure explicit
and is the right portfolio signal for "I use the multi-agent framework where it
fits." The LLM calls themselves go through our proven shared client (see
llm_adapter) so the free-tier concurrency guarantee is never bypassed.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, TypedDict

from langgraph.graph import StateGraph, START, END

from shared.config import get_settings
from backend_supervisor.core.llm_adapter import complete_json, complete_text
from backend_supervisor.core.prompts import (
    SUPERVISOR_SYSTEM_PROMPT,
    SYNTHESIS_SYSTEM_PROMPT,
)
from backend_supervisor.core.workers import WORKERS


class AgentState(TypedDict, total=False):
    """Shared state threaded through the graph."""
    question: str
    history: list[dict[str, Any]]
    assignments: list[dict[str, Any]]   # supervisor's routing decision
    reason: str                         # supervisor's short rationale
    worker_outputs: list[dict[str, Any]]
    answer: str


# ---- Node: supervisor (routing) -------------------------------------------
async def supervisor_node(state: AgentState) -> dict[str, Any]:
    """Ask the LLM for a compact routing plan. Falls back to a single inventory
    assignment if the plan is unusable, so the graph always progresses."""
    user = state["question"]
    # Only the current question goes to the router — keep the routing call cheap.
    plan = await complete_json(SUPERVISOR_SYSTEM_PROMPT, f"User question: {user}")

    assignments = plan.get("assignments") if isinstance(plan, dict) else None
    if not assignments or not isinstance(assignments, list):
        # Graceful fallback: treat it as a generic inventory search.
        assignments = [{
            "worker": "inventory",
            "sub_task": user,
            "entities": {},
        }]
    return {"assignments": assignments, "reason": (plan or {}).get("reason", "")}


# ---- Node: dispatch workers (concurrency-aware) ---------------------------
async def dispatch_workers_node(state: AgentState) -> dict[str, Any]:
    settings = get_settings()
    assignments = state.get("assignments", [])

    async def run_one(a: dict[str, Any]) -> dict[str, Any]:
        worker_fn = WORKERS.get(a.get("worker"))
        if worker_fn is None:
            return {"worker": a.get("worker"), "error": "unknown worker", "data": []}
        return await worker_fn(a.get("sub_task", ""), a.get("entities") or {})

    # Parallel only when the tier allows it AND the toggle is on. The workers
    # themselves gather data via deterministic tools; any LLM use inside still
    # passes through the semaphore, so we never exceed the cloud limit.
    if settings.supervisor.parallel_workers and settings.llm.max_concurrency > 1:
        outputs = await asyncio.gather(*(run_one(a) for a in assignments))
        outputs = list(outputs)
    else:
        outputs = []
        for a in assignments:
            outputs.append(await run_one(a))

    return {"worker_outputs": outputs}


# ---- Node: synthesize final answer ----------------------------------------
async def synthesize_node(state: AgentState) -> dict[str, Any]:
    payload = {
        "question": state["question"],
        "worker_outputs": state.get("worker_outputs", []),
    }
    answer = await complete_text(
        SYNTHESIS_SYSTEM_PROMPT,
        "Question and worker results (JSON):\n"
        + json.dumps(payload, ensure_ascii=False, default=str)
        + "\n\nWrite the final answer.",
    )
    return {"answer": answer or "I couldn't produce an answer."}


# ---- Build & compile the graph --------------------------------------------
def build_graph():
    g = StateGraph(AgentState)
    g.add_node("supervisor", supervisor_node)
    g.add_node("dispatch_workers", dispatch_workers_node)
    g.add_node("synthesize", synthesize_node)

    g.add_edge(START, "supervisor")
    g.add_edge("supervisor", "dispatch_workers")
    g.add_edge("dispatch_workers", "synthesize")
    g.add_edge("synthesize", END)
    return g.compile()


# Compiled once at import (stateless; safe to reuse across requests).
GRAPH = build_graph()


async def run_supervisor(
    question: str, history: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Entry point used by the API. Returns answer + routing + worker trace."""
    final_state = await GRAPH.ainvoke(
        {"question": question, "history": history or []}
    )
    return {
        "answer": final_state.get("answer", ""),
        "assignments": final_state.get("assignments", []),
        "reason": final_state.get("reason", ""),
        "worker_outputs": final_state.get("worker_outputs", []),
    }
