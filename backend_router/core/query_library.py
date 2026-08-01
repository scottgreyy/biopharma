"""
QUERY_LIBRARY: the fixed set of parameterized DuckDB templates.

This is the heart of the intent-router's security model. The LLM chooses an
intent NAME and supplies parameters; it never sees or writes SQL. Each template
uses DuckDB $named parameters so bound values are always data, never code.

Every template selects the canonical column set and is a pure SELECT. Adding a
capability = adding one entry here + one enum value in the intent schema.
"""
from __future__ import annotations

_COLS = "asset_code, asset_name, category, employee_name, location, purchase_date"

QUERY_LIBRARY: dict[str, str] = {
    # Exact asset lookup by code (case-insensitive).
    "lookup_asset_by_code": f"""
        SELECT {_COLS} FROM assets
        WHERE UPPER(asset_code) = UPPER($asset_code)
    """,
    # All assets held by a given employee (case-insensitive exact match).
    "assets_by_employee": f"""
        SELECT {_COLS} FROM assets
        WHERE LOWER(employee_name) = LOWER($employee_name)
        ORDER BY asset_code
    """,
    # Flexible filtered search. NULL params are ignored via COALESCE guards, so
    # one template serves any combination of category/location/model filters.
    "search_assets": f"""
        SELECT {_COLS} FROM assets
        WHERE ($category      IS NULL OR category      ILIKE '%' || $category      || '%')
          AND ($location      IS NULL OR location      ILIKE '%' || $location      || '%')
          AND ($asset_name    IS NULL OR asset_name    ILIKE '%' || $asset_name    || '%')
          AND ($employee_name IS NULL OR employee_name ILIKE '%' || $employee_name || '%')
        ORDER BY asset_code
    """,
    # Given a model name, find every asset of that model (the second half of a
    # multi-step "who else has the same model as X" chain).
    "assets_by_model": f"""
        SELECT {_COLS} FROM assets
        WHERE asset_name = $asset_name
        ORDER BY asset_code
    """,
    # Recommend by category/model + location.
    "recommend_assets": f"""
        SELECT {_COLS} FROM assets
        WHERE ($category   IS NULL OR category   ILIKE '%' || $category   || '%')
          AND ($asset_name IS NULL OR asset_name ILIKE '%' || $asset_name || '%')
          AND ($location   IS NULL OR location   ILIKE '%' || $location   || '%')
        ORDER BY location, asset_code
    """,
    # Simple analytical example that plays to DuckDB's strengths: count assets
    # per location (a GROUP BY aggregate — the OLAP shape DuckDB scales on).
    "count_by_location": """
        SELECT location, COUNT(*) AS asset_count
        FROM assets
        GROUP BY location
        ORDER BY asset_count DESC, location
    """,
}

# Full parameter set each intent may reference. The executor passes the whole
# dict (unused keys default to NULL), which lets DuckDB's COALESCE guards work.
ALL_PARAM_KEYS = (
    "asset_code",
    "employee_name",
    "category",
    "location",
    "asset_name",
)
