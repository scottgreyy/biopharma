"""Evaluation engine. Runs labeled EVAL_CASES against one backend's /chat and
scores each response deterministically against ground truth, plus backend-specific
architecture metrics (tool/routing/intent). Optional LLM judge for fluency."""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from shared.eval.dataset import EVAL_CASES, HONESTY_MARKERS


@dataclass
class CaseResult:
    id: str
    category: str
    question: str
    answer: str
    correct: bool
    honesty_ok: bool | None
    arch_metric_ok: bool | None
    json_valid: bool | None
    latency_s: float
    error: str | None = None
    fluency: int | None = None


@dataclass
class EvalSummary:
    backend: str
    n: int
    correctness: float
    honesty: float | None
    arch_accuracy: float | None
    json_validity: float | None
    avg_latency_s: float
    robustness: float
    avg_fluency: float | None
    results: list[CaseResult] = field(default_factory=list)


def _contains_all(text: str, needles: list[str]) -> bool:
    t = text.lower()
    return all(n.lower() in t for n in needles)


def _contains_any(text: str, needles: list[str]) -> bool:
    t = text.lower()
    return any(n.lower() in t for n in needles)


def _score_answer(case: dict[str, Any], answer: str) -> bool:
    if case["is_honesty"]:
        return _contains_any(answer, HONESTY_MARKERS)
    ok = _contains_all(answer, case["expect_facts"]) if case["expect_facts"] else True
    if case.get("forbid_facts"):
        ok = ok and not _contains_any(answer, case["forbid_facts"])
    return ok


def _score_honesty(case: dict[str, Any], answer: str) -> bool | None:
    if not case["is_honesty"]:
        return None
    return _contains_any(answer, HONESTY_MARKERS)


def _arch_metric(backend: str, case: dict[str, Any], resp: dict[str, Any]) -> bool | None:
    if backend == "ReAct Agent":
        expected = case.get("expect_tool")
        if expected is None:
            return None
        tools_used = [s.get("tool") for s in resp.get("trace", [])]
        return expected in tools_used
    if backend == "Multi-Agent Supervisor":
        expected = case.get("expect_worker")
        workers = [a.get("worker") for a in resp.get("assignments", [])]
        return expected in workers if workers else False
    if backend == "Intent Router":
        expected = case.get("expect_intent")
        intents = [s.get("intent") for s in resp.get("steps", [])]
        plan_intents = [s.get("intent") for s in resp.get("plan", {}).get("steps", [])]
        return expected in (intents + plan_intents)
    return None


def _json_valid(backend: str, resp: dict[str, Any]) -> bool | None:
    if backend != "Intent Router":
        return None
    return bool(resp.get("plan", {}).get("steps"))


async def run_eval(
    backend: str,
    chat_fn: Callable[[str], Any],
    judge_fn: Callable[[str, str], int] | None = None,
) -> EvalSummary:
    results: list[CaseResult] = []
    for case in EVAL_CASES:
        t0 = time.time()
        error = None
        answer = ""
        resp: dict[str, Any] = {}
        try:
            resp = await chat_fn(case["question"])
            answer = resp.get("answer", "") or ""
        except Exception as e:
            error = str(e)
        latency = time.time() - t0

        correct = _score_answer(case, answer) if not error else False
        honesty_ok = _score_honesty(case, answer) if not error else None
        arch_ok = _arch_metric(backend, case, resp) if not error else None
        jv = _json_valid(backend, resp) if not error else None

        fluency = None
        if judge_fn and not error and answer:
            try:
                fluency = judge_fn(case["question"], answer)
            except Exception:
                fluency = None

        results.append(CaseResult(
            id=case["id"], category=case["category"], question=case["question"],
            answer=answer, correct=correct, honesty_ok=honesty_ok,
            arch_metric_ok=arch_ok, json_valid=jv, latency_s=round(latency, 2),
            error=error, fluency=fluency,
        ))

    n = len(results)
    completed = [r for r in results if r.error is None]
    robustness = len(completed) / n if n else 0.0
    correctness = sum(r.correct for r in results) / n if n else 0.0

    honesty_cases = [r for r in results if r.honesty_ok is not None]
    honesty = (sum(r.honesty_ok for r in honesty_cases) / len(honesty_cases)
               if honesty_cases else None)

    arch_cases = [r for r in results if r.arch_metric_ok is not None]
    arch_acc = (sum(r.arch_metric_ok for r in arch_cases) / len(arch_cases)
                if arch_cases else None)

    jv_cases = [r for r in results if r.json_valid is not None]
    json_validity = (sum(r.json_valid for r in jv_cases) / len(jv_cases)
                     if jv_cases else None)

    avg_latency = (sum(r.latency_s for r in completed) / len(completed)
                   if completed else 0.0)

    fluency_scores = [r.fluency for r in results if r.fluency is not None]
    avg_fluency = sum(fluency_scores) / len(fluency_scores) if fluency_scores else None

    return EvalSummary(
        backend=backend, n=n, correctness=correctness, honesty=honesty,
        arch_accuracy=arch_acc, json_validity=json_validity,
        avg_latency_s=round(avg_latency, 2), robustness=robustness,
        avg_fluency=avg_fluency, results=results,
    )
