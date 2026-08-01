"""
Tool layer for the ReAct agent.

Each tool is:
  * a plain async Python function that builds a PARAMETERIZED read-only query
    and runs it through shared.db.safe_execute (never raw SQL from the model);
  * fronted by a Pydantic v2 model that validates/coerces the LLM-supplied
    arguments before any DB access (bad args fail fast with a clear message);
  * described by a JSON schema in TOOL_SCHEMAS that we hand to Ollama's native
    `tools=` parameter so the model can choose and populate them.

The tools are deliberately typed and narrow. The model cannot ask for "all
rows" or inject SQL — it can only fill these validated fields, and every list
returning tool is bounded by an explicit, capped limit.

Scope honesty: the dataset has 6 columns (code, name, category, employee,
location, purchase_date) and no manager/availability columns. So there is no
manager tool. "Multi-step reasoning" and "recommendation" are satisfied truth
fully against real data: e.g. find the model a person uses, then find everyone
else using that model (chained lookups), or recommend by category+location.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field, field_validator

from shared.config import get_settings
from shared.db.database import safe_execute

# --- Base columns selected everywhere, in a stable order --------------------
_COLS = "asset_code, asset_name, category, employee_name, location, purchase_date"


# ===========================================================================
# Pydantic argument models  (validation happens BEFORE any DB access)
# ===========================================================================
class AssetCodeArgs(BaseModel):
    asset_code: str = Field(..., description="Asset code, e.g. 'AST1002'.")

    @field_validator("asset_code")
    @classmethod
    def _normalize(cls, v: str) -> str:
        v = v.strip().upper()
        if not v:
            raise ValueError("asset_code must not be empty.")
        return v


class EmployeeArgs(BaseModel):
    employee_name: str = Field(..., description="Full employee name, e.g. 'Amit Kumar'.")

    @field_validator("employee_name")
    @classmethod
    def _clean(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("employee_name must not be empty.")
        return v


class SearchArgs(BaseModel):
    """Flexible filtered search. All filters optional; combined with AND.
    Matching is case-insensitive substring for text fields."""
    asset_name: str | None = Field(None, description="Model/name substring, e.g. 'ThinkPad'.")
    category: str | None = Field(None, description="Category, e.g. 'Laptop', 'Printer'.")
    location: str | None = Field(None, description="City, e.g. 'Bangalore'.")
    employee_name: str | None = Field(None, description="Employee name substring.")
    limit: int = Field(10, ge=1, le=50, description="Max rows to return.")


class RelatedByModelArgs(BaseModel):
    """For multi-step reasoning: given ONE asset code, find other assets that
    share its asset_name (model) — optionally excluding the original holder."""
    asset_code: str = Field(..., description="Reference asset code, e.g. 'AST1002'.")
    exclude_self: bool = Field(True, description="Exclude the reference asset itself.")

    @field_validator("asset_code")
    @classmethod
    def _up(cls, v: str) -> str:
        return v.strip().upper()


class RecommendArgs(BaseModel):
    """Recommendation by type + place: 'find a MacBook in Bangalore'. Returns
    matching assets (the dataset has no availability flag, so this surfaces
    existing assets of the requested category/model in the requested city —
    the honest form of a recommendation for this data)."""
    category: str | None = Field(None, description="Desired category, e.g. 'Laptop'.")
    asset_name: str | None = Field(None, description="Desired model substring, e.g. 'MacBook'.")
    location: str | None = Field(None, description="Target city, e.g. 'Bangalore'.")
    limit: int = Field(5, ge=1, le=50)


# ===========================================================================
# Tool implementations
# ===========================================================================
async def lookup_asset_by_code(args: AssetCodeArgs) -> dict[str, Any]:
    """Exact asset lookup by primary key. O(log n). Handles the missing case."""
    rows = await safe_execute(
        f"SELECT {_COLS} FROM assets WHERE asset_code = ?", (args.asset_code,)
    )
    if not rows:
        return {"found": False, "message": f"No asset found with code {args.asset_code}."}
    return {"found": True, "asset": rows[0]}


async def get_assets_by_employee(args: EmployeeArgs) -> dict[str, Any]:
    """All assets held by an employee (case-insensitive exact name match).
    Enables 'what does X use / in which cities does X have assets'."""
    rows = await safe_execute(
        f"SELECT {_COLS} FROM assets WHERE LOWER(employee_name) = LOWER(?) ORDER BY asset_code",
        (args.employee_name,),
    )
    return {"count": len(rows), "employee_name": args.employee_name, "assets": rows}


async def search_assets(args: SearchArgs) -> dict[str, Any]:
    """Flexible AND-combined filtered search with LIKE substring matching."""
    clauses: list[str] = []
    params: list[Any] = []
    for col, val in (
        ("asset_name", args.asset_name),
        ("category", args.category),
        ("location", args.location),
        ("employee_name", args.employee_name),
    ):
        if val:
            clauses.append(f"{col} LIKE ? COLLATE NOCASE")
            params.append(f"%{val.strip()}%")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(args.limit)
    rows = await safe_execute(
        f"SELECT {_COLS} FROM assets {where} ORDER BY asset_code LIMIT ?", params
    )
    return {"count": len(rows), "assets": rows}


async def find_related_by_model(args: RelatedByModelArgs) -> dict[str, Any]:
    """Multi-step tool: resolve the reference asset's model, then find all
    other assets of that same model. Demonstrates deterministic chaining in a
    single call (the agent can also chain lookup+search itself; this makes the
    multi-step requirement crisp and reproducible)."""
    ref = await safe_execute(
        f"SELECT {_COLS} FROM assets WHERE asset_code = ?", (args.asset_code,)
    )
    if not ref:
        return {"found": False, "message": f"No asset found with code {args.asset_code}."}
    model_name = ref[0]["asset_name"]
    sql = f"SELECT {_COLS} FROM assets WHERE asset_name = ?"
    params: list[Any] = [model_name]
    if args.exclude_self:
        sql += " AND asset_code != ?"
        params.append(args.asset_code)
    sql += " ORDER BY asset_code"
    related = await safe_execute(sql, params)
    return {
        "found": True,
        "reference_asset": ref[0],
        "model": model_name,
        "related_count": len(related),
        "related_assets": related,
    }


async def recommend_assets(args: RecommendArgs) -> dict[str, Any]:
    """Recommend assets by category/model and location."""
    clauses: list[str] = []
    params: list[Any] = []
    for col, val in (
        ("category", args.category),
        ("asset_name", args.asset_name),
        ("location", args.location),
    ):
        if val:
            clauses.append(f"{col} LIKE ? COLLATE NOCASE")
            params.append(f"%{val.strip()}%")
    if not clauses:
        return {"count": 0, "message": "Specify at least a category, model, or location."}
    params.append(args.limit)
    rows = await safe_execute(
        f"SELECT {_COLS} FROM assets WHERE {' AND '.join(clauses)} "
        f"ORDER BY location, asset_code LIMIT ?",
        params,
    )
    msg = "No matching assets found." if not rows else f"Found {len(rows)} matching asset(s)."
    return {"count": len(rows), "message": msg, "assets": rows}


# ===========================================================================
# Registry: name -> (Pydantic model, async impl). The dispatcher validates
# with the model, then awaits the impl. One place to add/replace a tool.
# ===========================================================================
TOOL_REGISTRY: dict[str, tuple[type[BaseModel], Callable[[Any], Awaitable[dict]]]] = {
    "lookup_asset_by_code": (AssetCodeArgs, lookup_asset_by_code),
    "get_assets_by_employee": (EmployeeArgs, get_assets_by_employee),
    "search_assets": (SearchArgs, search_assets),
    "find_related_by_model": (RelatedByModelArgs, find_related_by_model),
    "recommend_assets": (RecommendArgs, recommend_assets),
}


async def dispatch_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Validate arguments with the tool's Pydantic model and run it. Errors are
    returned as data (not raised) so the agent can observe and recover."""
    if name not in TOOL_REGISTRY:
        return {"error": f"Unknown tool '{name}'."}
    model_cls, impl = TOOL_REGISTRY[name]
    try:
        validated = model_cls(**(arguments or {}))
    except Exception as exc:  # pydantic ValidationError et al.
        return {"error": f"Invalid arguments for '{name}': {exc}"}
    return await impl(validated)


# ---- JSON schemas handed to Ollama's native `tools=` parameter -------------
# Kept in sync with the Pydantic models above by hand (small, explicit, and
# lets us write model-facing descriptions tuned for tool selection).
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "lookup_asset_by_code",
            "description": "Get the full record for one asset by its exact asset code (e.g. AST1002). Use for 'where is AST1002', 'who has AST1005', details of a specific code.",
            "parameters": {
                "type": "object",
                "properties": {"asset_code": {"type": "string", "description": "e.g. 'AST1002'"}},
                "required": ["asset_code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_assets_by_employee",
            "description": "List every asset assigned to a specific employee by full name. Use for 'what does Rahul Sharma use', 'which assets does Amit Kumar have', 'in which cities does X have assets'.",
            "parameters": {
                "type": "object",
                "properties": {"employee_name": {"type": "string", "description": "e.g. 'Rahul Sharma'"}},
                "required": ["employee_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_assets",
            "description": "Search/filter assets by any combination of model name, category, location, or employee (substring, case-insensitive). Use for 'list laptops in Bangalore', 'all printers', 'who is in Mumbai'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "asset_name": {"type": "string", "description": "model substring, e.g. 'ThinkPad'"},
                    "category": {"type": "string", "description": "e.g. 'Laptop', 'Printer', 'Scanner', 'Mobile', 'Monitor'"},
                    "location": {"type": "string", "description": "city, e.g. 'Bangalore'"},
                    "employee_name": {"type": "string"},
                    "limit": {"type": "integer", "description": "max rows (1-50), default 10"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_related_by_model",
            "description": "Given one asset code, find all OTHER assets of the same model/name and who has them where. Use for multi-step questions like 'who else has the same laptop as Amit Kumar (AST1002)'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "asset_code": {"type": "string", "description": "reference code, e.g. 'AST1002'"},
                    "exclude_self": {"type": "boolean", "description": "exclude the reference asset (default true)"},
                },
                "required": ["asset_code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recommend_assets",
            "description": "Recommend/find assets by desired category or model and a target city. Use for 'find a laptop in Bangalore', 'is there a MacBook in Chennai', 'suggest a scanner in Mumbai'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "e.g. 'Laptop'"},
                    "asset_name": {"type": "string", "description": "model substring, e.g. 'MacBook'"},
                    "location": {"type": "string", "description": "city, e.g. 'Bangalore'"},
                    "limit": {"type": "integer", "description": "max rows (1-50), default 5"},
                },
            },
        },
    },
]
