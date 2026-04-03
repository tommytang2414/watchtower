"""SQLite storage for monitoring metrics and alert state."""
import aiosqlite
import json
from datetime import datetime, timezone, timedelta
from typing import Optional

import os as _os
DATABASE_PATH = _os.path.join(_os.path.dirname(__file__), "monitor.db")


async def init_db():
    """Create tables if they don't exist."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                probe_name TEXT NOT NULL,
                probe_type TEXT NOT NULL,
                up INTEGER NOT NULL,
                response_time_ms REAL,
                status_code INTEGER,
                stale INTEGER,
                rates_count INTEGER,
                content_ok INTEGER,
                error_message TEXT,
                conclusion TEXT,
                matched_keywords TEXT,
                created_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sent_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                probe_name TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                resolved_at TEXT,
                UNIQUE(probe_name, alert_type)
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_checks_probe_created
            ON checks(probe_name, created_at DESC)
        """)
        await db.commit()


async def record_check(
    probe_name: str,
    probe_type: str,
    up: bool,
    response_time_ms: Optional[float] = None,
    status_code: Optional[int] = None,
    stale: Optional[bool] = None,
    rates_count: Optional[int] = None,
    content_ok: Optional[bool] = None,
    error_message: Optional[str] = None,
    conclusion: Optional[str] = None,
    matched_keywords: Optional[list] = None,
) -> int:
    """Insert a check result, return the row id."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        now = datetime.now(timezone(timedelta(hours=8))).isoformat()
        await db.execute(
            """
            INSERT INTO checks (
                probe_name, probe_type, up, response_time_ms, status_code,
                stale, rates_count, content_ok, error_message, conclusion,
                matched_keywords, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                probe_name,
                probe_type,
                int(up),
                response_time_ms,
                status_code,
                int(stale) if stale is not None else None,
                rates_count,
                int(content_ok) if content_ok is not None else None,
                error_message,
                conclusion,
                json.dumps(matched_keywords) if matched_keywords else None,
                now,
            ),
        )
        await db.commit()
        cursor = await db.execute("SELECT last_insert_rowid()")
        row = await cursor.fetchone()
        return row[0]


async def get_last_check(probe_name: str) -> Optional[dict]:
    """Get the most recent check for a probe."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM checks
            WHERE probe_name = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (probe_name,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_recent_checks(probe_name: str, hours: int = 24, limit: int = 100) -> list[dict]:
    """Get recent checks for a probe."""
    cutoff = datetime.now(timezone(timedelta(hours=8))) - timedelta(hours=hours)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM checks
            WHERE probe_name = ? AND created_at >= ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (probe_name, cutoff.isoformat(), limit),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_all_probe_names() -> list[str]:
    """Get distinct probe names."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT DISTINCT probe_name FROM checks ORDER BY probe_name"
        )
        rows = await cursor.fetchall()
        return [r[0] for r in rows]


async def get_recent_checks_all(hours: int = 24, limit_per_probe: int = 10) -> dict[str, list[dict]]:
    """Get recent checks for all probes."""
    result = {}
    probe_names = await get_all_probe_names()
    for name in probe_names:
        result[name] = await get_recent_checks(name, hours=hours, limit=limit_per_probe)
    return result


async def get_unresolved_alert(probe_name: str, alert_type: str) -> Optional[dict]:
    """Check if there's an unresolved alert."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM sent_alerts
            WHERE probe_name = ? AND alert_type = ? AND resolved_at IS NULL
            """,
            (probe_name, alert_type),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def upsert_alert(probe_name: str, alert_type: str) -> None:
    """Insert or update alert record. If resolved, set resolved_at."""
    now = datetime.now(timezone(timedelta(hours=8))).isoformat()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        existing = await get_unresolved_alert(probe_name, alert_type)
        if existing:
            # Already have unresolved alert — do nothing (dedup)
            return
        await db.execute(
            """
            INSERT OR REPLACE INTO sent_alerts (probe_name, alert_type, sent_at, resolved_at)
            VALUES (?, ?, ?, NULL)
            """,
            (probe_name, alert_type, now),
        )
        await db.commit()


async def resolve_alert(probe_name: str, alert_type: str) -> bool:
    """Mark an alert as resolved. Returns True if there was an alert to resolve."""
    now = datetime.now(timezone(timedelta(hours=8))).isoformat()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            UPDATE sent_alerts SET resolved_at = ?
            WHERE probe_name = ? AND alert_type = ? AND resolved_at IS NULL
            """,
            (now, probe_name, alert_type),
        )
        await db.commit()
        return cursor.rowcount > 0
