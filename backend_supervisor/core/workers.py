"""
Worker implementations for the supervisor graph.

Token-optimization core idea: workers do their DATA gathering with deterministic
shared tools (no LLM tokens spent choosing how to query), and only optionally
use the LLM for a tiny summary. Each worker receives just its sub_task +
entities from the supervisor — not the full conversation or the other worker's
context — which keeps every worker call cheap.

Both workers reuse shared.tools.asset_tools, so all three backends share one
tested data-access layer and differ only in orchestration.
"""
from __future__ import annotations

from typing import Any

from shared.tools.asset_tools import dispatch_tool


async def run_inventory_worker(sub_task: str, entities: dict[str, Any]) -> dict[str, Any]:
    """Asset-centric gathering. Chooses the right shared tool from the entities
    deterministically (no LLM call needed for tool selection)."""
    code = entities.get("asset_code")
    name = entities.get("asset_name")
    category = entities.get("category")
    location = entities.get("location")

    rows: list[dict[str, Any]] = []
    used: str = ""

    if code:
        used = "lookup_asset_by_code"
        res = await dispatch_tool(used, {"asset_code": code})
        rows = [res["asset"]] if res.get("found") else []
    elif name and (category or location):
        used = "recommend_assets"
        res = await dispatch_tool(used, {"asset_name": name, "category": category, "location": location})
        rows = res.get("assets", [])
    elif category or location or name:
        used = "search_assets"
        res = await dispatch_tool(used, {
            "category": category, "location": location, "asset_name": name,
        })
        rows = res.get("assets", [])
    else:
        used = "none"
        res = {"message": "No asset entities provided."}

    return {
        "worker": "inventory",
        "sub_task": sub_task,
        "tool_used": used,
        "count": len(rows),
        "data": rows,
    }


async def run_people_worker(sub_task: str, entities: dict[str, Any]) -> dict[str, Any]:
    """Employee-centric gathering via the shared tool."""
    employee = entities.get("employee_name")
    if not employee:
        return {"worker": "people", "sub_task": sub_task, "tool_used": "none",
                "count": 0, "data": [], "note": "No employee name provided."}

    res = await dispatch_tool("get_assets_by_employee", {"employee_name": employee})
    rows = res.get("assets", [])
    return {
        "worker": "people",
        "sub_task": sub_task,
        "tool_used": "get_assets_by_employee",
        "employee_name": employee,
        "count": len(rows),
        "cities": sorted({r["location"] for r in rows}),
        "data": rows,
    }


# Registry so the graph can dispatch by worker name.
WORKERS = {
    "inventory": run_inventory_worker,
    "people": run_people_worker,
}
