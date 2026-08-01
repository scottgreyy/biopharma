"""
Idempotent async database initializer.

Run directly:  python -m shared.db.init_db
It (re)creates data/assets.db from schema.sql and seeds it from the CSV.

Uses a normal read-write connection ONLY here (seeding is the one legitimate
write path). All request-time access goes through the read-only safe_execute.
"""
from __future__ import annotations

import asyncio
import csv
from pathlib import Path

import aiosqlite

from shared.config import get_settings

# Maps CSV headers -> DB columns, decoupling the source file's naming from the
# schema. If the client sends a differently-headed CSV later, only this changes.
_CSV_TO_COLUMN = {
    "Asset Code": "asset_code",
    "Asset Name": "asset_name",
    "Category": "category",
    "Employee Name": "employee_name",
    "Location": "location",
    "Purchase Date": "purchase_date",
}
_COLUMNS = list(_CSV_TO_COLUMN.values())


def _read_rows(csv_path: Path) -> list[tuple[str, ...]]:
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = set(_CSV_TO_COLUMN) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV is missing required columns: {sorted(missing)}")
        rows: list[tuple[str, ...]] = []
        for line in reader:
            rows.append(tuple(line[h].strip() for h in _CSV_TO_COLUMN))
        return rows


async def init_db() -> int:
    """Create schema and load seed data. Returns the number of rows inserted."""
    settings = get_settings()
    schema_sql = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
    rows = _read_rows(settings.db.assets_csv)

    settings.db.assets_db_path.parent.mkdir(parents=True, exist_ok=True)

    # Read-write connection — seeding is the only sanctioned write path.
    async with aiosqlite.connect(settings.db.assets_db_path) as db:
        await db.executescript(schema_sql)
        placeholders = ", ".join("?" for _ in _COLUMNS)
        await db.executemany(
            f"INSERT INTO assets ({', '.join(_COLUMNS)}) VALUES ({placeholders})",
            rows,
        )
        await db.commit()
    return len(rows)


if __name__ == "__main__":
    n = asyncio.run(init_db())
    s = get_settings()
    print(f"Initialized {s.db.assets_db_path} with {n} asset rows from {s.db.assets_csv}.")
