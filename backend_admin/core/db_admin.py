"""Read-write data-management layer for the admin backend. Separate from the
read-only chat path so the 'AI can never modify data' guarantee stays intact.
All writes parameterized; WAL mode + busy timeout so writes coexist with reads."""
from __future__ import annotations
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator
import aiosqlite
from shared.config import get_settings

COLUMNS = ["asset_code", "asset_name", "category", "employee_name", "location", "purchase_date"]
HEADER_TO_COLUMN = {
    "Asset Code": "asset_code", "Asset Name": "asset_name", "Category": "category",
    "Employee Name": "employee_name", "Location": "location", "Purchase Date": "purchase_date",
}

@asynccontextmanager
async def _connect() -> AsyncIterator[aiosqlite.Connection]:
    settings = get_settings()
    db = await aiosqlite.connect(settings.db.assets_db_path, timeout=10)
    try:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=5000")
        yield db
    finally:
        await db.close()

async def list_assets(limit: int = 500, offset: int = 0) -> list[dict[str, Any]]:
    async with _connect() as db:
        async with db.execute(f"SELECT {', '.join(COLUMNS)} FROM assets ORDER BY asset_code LIMIT ? OFFSET ?", (limit, offset)) as cur:
            return [dict(r) for r in await cur.fetchall()]

async def count_assets() -> int:
    async with _connect() as db:
        async with db.execute("SELECT COUNT(*) AS n FROM assets") as cur:
            row = await cur.fetchone()
            return int(row["n"]) if row else 0

async def get_asset(asset_code: str) -> dict[str, Any] | None:
    async with _connect() as db:
        async with db.execute(f"SELECT {', '.join(COLUMNS)} FROM assets WHERE asset_code = ?", (asset_code.strip().upper(),)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

async def add_asset(row: dict[str, Any]) -> dict[str, Any]:
    code = str(row.get("asset_code", "")).strip().upper()
    if not code:
        return {"ok": False, "message": "asset_code is required."}
    values = {c: str(row.get(c, "")).strip() for c in COLUMNS}
    values["asset_code"] = code
    async with _connect() as db:
        try:
            await db.execute(f"INSERT INTO assets ({', '.join(COLUMNS)}) VALUES ({', '.join('?' for _ in COLUMNS)})", tuple(values[c] for c in COLUMNS))
            await db.commit()
        except aiosqlite.IntegrityError:
            return {"ok": False, "message": f"Asset {code} already exists."}
    return {"ok": True, "message": f"Added asset {code}.", "asset": values}

async def delete_asset(asset_code: str) -> dict[str, Any]:
    code = asset_code.strip().upper()
    async with _connect() as db:
        cur = await db.execute("DELETE FROM assets WHERE asset_code = ?", (code,))
        await db.commit()
        if cur.rowcount == 0:
            return {"ok": False, "message": f"No asset found with code {code}."}
    return {"ok": True, "message": f"Deleted asset {code}."}

async def append_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    norm, seen, dupes = [], set(), set()
    for r in rows:
        code = str(r.get("asset_code", "")).strip().upper()
        if not code:
            return {"ok": False, "message": "A row is missing asset_code; nothing was added."}
        if code in seen:
            dupes.add(code)
        seen.add(code)
        norm.append({c: str(r.get(c, "")).strip() for c in COLUMNS} | {"asset_code": code})
    if dupes:
        return {"ok": False, "message": f"Upload has duplicate codes: {sorted(dupes)}. Nothing was added."}
    async with _connect() as db:
        ph = ", ".join("?" for _ in seen)
        async with db.execute(f"SELECT asset_code FROM assets WHERE asset_code IN ({ph})", tuple(seen)) as cur:
            existing = {r["asset_code"] for r in await cur.fetchall()}
        if existing:
            return {"ok": False, "message": f"These codes already exist: {sorted(existing)}. Nothing was added."}
        await db.executemany(f"INSERT INTO assets ({', '.join(COLUMNS)}) VALUES ({', '.join('?' for _ in COLUMNS)})", [tuple(r[c] for c in COLUMNS) for r in norm])
        await db.commit()
    return {"ok": True, "message": f"Appended {len(norm)} row(s).", "added": len(norm)}
