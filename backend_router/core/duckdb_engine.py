"""
DuckDB data layer for Backend 3 (intent-router).

Why DuckDB here specifically: Backends 1 & 2 run on SQLite (transactional point
lookups). Backend 3 demonstrates the analytical scaling path — DuckDB is a
columnar OLAP engine that stays fast on large GROUP BY / scan workloads. For 21
rows it is functionally identical; the point is to show the pattern and give a
one-flag migration story (DB__ENGINE=duckdb) for when the dataset grows large
enough for analytics to matter.

Security posture mirrors the SQLite guard:
  * The LLM NEVER emits SQL. It only extracts a named intent + parameters.
  * Every query comes from a fixed, code-owned QUERY_LIBRARY and is executed
    with DuckDB native parameter binding ($named), so values can never be
    interpreted as SQL. Injection is closed by construction.
  * The connection is loaded once from the seed CSV into an in-memory database.
    Nothing the router does can write to it (only SELECTs are ever run).
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

import duckdb

from shared.config import get_settings

# Matches $param_name occurrences in a template so we bind only what's used.
_PARAM_RE = re.compile(r"\$([a-zA-Z_][a-zA-Z0-9_]*)")

# Internal column names, matching the SQLite schema for cross-backend parity.
_COLUMN_MAP = {
    "Asset Code": "asset_code",
    "Asset Name": "asset_name",
    "Category": "category",
    "Employee Name": "employee_name",
    "Location": "location",
    "Purchase Date": "purchase_date",
}


@lru_cache
def get_connection() -> duckdb.DuckDBPyConnection:
    """Return a cached in-memory DuckDB connection seeded from the assets CSV.

    lru_cache makes this a process-wide singleton so we load the CSV exactly
    once. read_csv_auto infers types; we then rename columns to the internal
    snake_case names so query templates are identical in spirit to SQLite.
    """
    settings = get_settings()
    con = duckdb.connect(database=":memory:")

    csv_path = str(settings.db.assets_csv)
    # Load raw, then project to renamed columns into the canonical `assets` view.
    con.execute(
        "CREATE TABLE _raw AS SELECT * FROM read_csv_auto(?, header=True)",
        [csv_path],
    )
    select_exprs = ", ".join(
        f'"{src}" AS {dst}' for src, dst in _COLUMN_MAP.items()
    )
    con.execute(f"CREATE TABLE assets AS SELECT {select_exprs} FROM _raw")
    con.execute("DROP TABLE _raw")
    return con


def execute_named(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Execute a SELECT with DuckDB $named parameter binding, return dict rows.

    `sql` always comes from QUERY_LIBRARY (never from the LLM). `params` are the
    validated intent parameters. DuckDB binds them as values, so they can never
    be parsed as SQL.
    """
    con = get_connection()
    settings = get_settings()

    # Backstop row cap — enforce a LIMIT if the template didn't set one.
    if "limit" not in sql.lower():
        sql = f"{sql.rstrip().rstrip(';')} LIMIT {settings.db.max_query_rows}"

    # DuckDB rejects bound params not referenced in the SQL, so pass only the
    # $named params this template actually uses. Values still bind as data.
    needed = set(_PARAM_RE.findall(sql))
    bind = {k: params.get(k) for k in needed}

    cur = con.execute(sql, bind)
    columns = [d[0] for d in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]
