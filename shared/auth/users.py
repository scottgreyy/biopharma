"""
User account persistence for JWT auth.

Uses a SEPARATE read-write SQLite file (users.db) so the assets database can
stay opened read-only everywhere else. Passwords are stored only as bcrypt
hashes — never plaintext.

Table is created lazily on first use (ensure_users_table), so there is no extra
init step for the reviewer beyond seeding the assets DB.
"""
from __future__ import annotations

from typing import Any

import aiosqlite

from shared.config import get_settings

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS users (
    username      TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


async def ensure_users_table() -> None:
    settings = get_settings()
    settings.db.users_db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(settings.db.users_db_path) as db:
        await db.execute(_CREATE_SQL)
        await db.commit()


async def get_user(username: str) -> dict[str, Any] | None:
    settings = get_settings()
    async with aiosqlite.connect(settings.db.users_db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT username, password_hash, created_at FROM users WHERE username = ?",
            (username,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def create_user(username: str, password_hash: str) -> bool:
    """Insert a new user. Returns False if the username already exists."""
    settings = get_settings()
    async with aiosqlite.connect(settings.db.users_db_path) as db:
        try:
            await db.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, password_hash),
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False  # PRIMARY KEY collision -> username taken
