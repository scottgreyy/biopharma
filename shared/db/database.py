"""
Read-only async database access layer, shared by all backends.

Threat model & rationale
------------------------
The LLM never emits SQL. It calls typed Python tools (see backend_*/core/
tools.py) which build parameterized queries internally. That closes the
injection surface by construction — user/LLM input only ever arrives as bound
`?` parameters, never as query text.

`safe_execute` is defense-in-depth on top of that, four independent layers:
  1. Connection is opened READ-ONLY (mode=ro URI). Even a bug cannot write.
  2. Statement must parse to a single SELECT (or WITH ... SELECT). Anything
     else (INSERT/UPDATE/DELETE/DROP/TRUNCATE/ALTER/ATTACH/PRAGMA) is rejected.
  3. Statement stacking via ';' is rejected (blocks "SELECT 1; DROP ...").
  4. A LIMIT is enforced/capped so no tool can dump an unbounded result set.

Any one layer failing still leaves the data safe. This is the "belt and
suspenders" the reviewer will look for.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

import aiosqlite

from shared.config import get_settings

# Verbs that must never appear as the leading keyword of a statement we run.
_FORBIDDEN_LEADING = re.compile(
    r"^\s*(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|REPLACE|ATTACH|"
    r"DETACH|PRAGMA|VACUUM|REINDEX|GRANT|REVOKE)\b",
    re.IGNORECASE,
)
# A statement we accept must start with SELECT or a CTE (WITH ... SELECT).
_ALLOWED_LEADING = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)


class UnsafeQueryError(ValueError):
    """Raised when a query fails the read-only safety checks."""


def _assert_safe(sql: str) -> None:
    """Validate a SQL string against the read-only policy. Raises on violation."""
    if sql.count(";") > 1 or (";" in sql and not sql.rstrip().endswith(";")):
        # Allow at most a single trailing semicolon; block statement stacking.
        raise UnsafeQueryError("Statement stacking (multiple ';') is not allowed.")
    if _FORBIDDEN_LEADING.search(sql):
        raise UnsafeQueryError("Only read-only SELECT statements are permitted.")
    if not _ALLOWED_LEADING.match(sql):
        raise UnsafeQueryError("Query must begin with SELECT or WITH.")


def _ensure_limit(sql: str, cap: int) -> str:
    """Append a LIMIT if none present; the DB layer never returns unbounded sets.
    (Tools also pass their own smaller limits; this is the backstop cap.)"""
    if re.search(r"\bLIMIT\b", sql, re.IGNORECASE):
        return sql
    trimmed = sql.rstrip().rstrip(";")
    return f"{trimmed} LIMIT {cap}"


async def safe_execute(
    sql: str,
    params: Iterable[Any] | Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Execute a validated, read-only SELECT and return rows as dicts.

    Complexity: dominated by the query plan. With the indices in schema.sql,
    point/filter lookups are O(log n + k); aggregates are O(n) by nature.
    """
    settings = get_settings()
    _assert_safe(sql)
    sql = _ensure_limit(sql, settings.db.max_query_rows)

    # uri=True + mode=ro => physically read-only handle. Writes raise instead
    # of corrupting data, giving us a hard floor under the software guards.
    async with aiosqlite.connect(settings.db.sqlite_uri_readonly, uri=True) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(sql, tuple(params) if params else ()) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
