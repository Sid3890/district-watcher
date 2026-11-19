import json
import logging
from typing import Dict, Any, List, Optional
from contextlib import asynccontextmanager
import aiosqlite
from app.config import DB_PATH

logger = logging.getLogger("district_watcher.database")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS app_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    sound_enabled INTEGER NOT NULL DEFAULT 1,
    sound_tone TEXT NOT NULL DEFAULT 'chime',
    sound_volume REAL NOT NULL DEFAULT 0.8,
    desktop_notifications_enabled INTEGER NOT NULL DEFAULT 1,
    poll_interval_seconds INTEGER NOT NULL DEFAULT 45,
    last_selected_city TEXT DEFAULT 'Chennai'
);

INSERT OR IGNORE INTO app_settings (
    id, sound_enabled, sound_tone, sound_volume, 
    desktop_notifications_enabled, poll_interval_seconds, last_selected_city
) VALUES (1, 1, 'chime', 0.8, 1, 45, 'Chennai');

CREATE TABLE IF NOT EXISTS watch_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mode TEXT NOT NULL CHECK (mode IN ('SHOW_OPENING', 'SEAT_AVAILABILITY')),
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'PAUSED', 'TRIGGERED')),
    city TEXT NOT NULL,
    movie_title TEXT NOT NULL,
    movie_url TEXT NOT NULL,
    target_date TEXT NOT NULL,
    theatre_name TEXT NOT NULL,
    showtime_str TEXT,
    watched_seats_json TEXT,
    match_rule TEXT DEFAULT 'ANY' CHECK (match_rule IN ('ANY', 'ALL')),
    last_checked_at TEXT,
    last_check_summary TEXT,
    triggered_details_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS alert_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    watch_job_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    acknowledged INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (watch_job_id) REFERENCES watch_jobs(id) ON DELETE CASCADE
);
"""

@asynccontextmanager
async def get_db():
    """Async context manager for SQLite connection with automatic foreign keys & closing."""
    conn = await aiosqlite.connect(DB_PATH)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
    finally:
        await conn.close()

async def init_db() -> None:
    logger.info(f"Initializing database at {DB_PATH}")
    async with get_db() as conn:
        await conn.executescript(SCHEMA_SQL)
        await conn.commit()
    logger.info("Database schema initialized successfully")

# Settings CRUD
async def get_settings() -> Dict[str, Any]:
    async with get_db() as conn:
        cursor = await conn.execute("SELECT * FROM app_settings WHERE id = 1;")
        row = await cursor.fetchone()
        if row:
            return {
                "id": row["id"],
                "sound_enabled": bool(row["sound_enabled"]),
                "sound_tone": row["sound_tone"],
                "sound_volume": float(row["sound_volume"]),
                "desktop_notifications_enabled": bool(row["desktop_notifications_enabled"]),
                "poll_interval_seconds": int(row["poll_interval_seconds"]),
                "last_selected_city": row["last_selected_city"],
            }
        return {
            "id": 1,
            "sound_enabled": True,
            "sound_tone": "chime",
            "sound_volume": 0.8,
            "desktop_notifications_enabled": True,
            "poll_interval_seconds": 45,
            "last_selected_city": "Chennai",
        }

async def update_settings(updates: Dict[str, Any]) -> Dict[str, Any]:
    fields = []
    values = []
    for k, v in updates.items():
        if k in (
            "sound_enabled", "sound_tone", "sound_volume",
            "desktop_notifications_enabled", "poll_interval_seconds",
            "last_selected_city"
        ) and v is not None:
            fields.append(f"{k} = ?")
            if isinstance(v, bool):
                values.append(1 if v else 0)
            else:
                values.append(v)
    
    if fields:
        query = f"UPDATE app_settings SET {', '.join(fields)} WHERE id = 1;"
        async with get_db() as conn:
            await conn.execute(query, tuple(values))
            await conn.commit()
    return await get_settings()

# Watch Jobs CRUD
def _parse_job_row(row: aiosqlite.Row) -> Dict[str, Any]:
    watched_seats = None
    if row["watched_seats_json"]:
        try:
            watched_seats = json.loads(row["watched_seats_json"])
        except Exception:
            watched_seats = []
    
    triggered_details = None
    if row["triggered_details_json"]:
        try:
            triggered_details = json.loads(row["triggered_details_json"])
        except Exception:
            triggered_details = None

    return {
        "id": row["id"],
        "mode": row["mode"],
        "status": row["status"],
        "city": row["city"],
        "movie_title": row["movie_title"],
        "movie_url": row["movie_url"],
        "target_date": row["target_date"],
        "theatre_name": row["theatre_name"],
        "showtime_str": row["showtime_str"],
        "watched_seats": watched_seats,
        "match_rule": row["match_rule"],
        "last_checked_at": row["last_checked_at"],
        "last_check_summary": row["last_check_summary"],
        "triggered_details": triggered_details,
        "created_at": row["created_at"],
    }

async def create_watch_job(
    mode: str,
    city: str,
    movie_title: str,
    movie_url: str,
    target_date: str,
    theatre_name: str,
    showtime_str: Optional[str] = None,
    watched_seats: Optional[List[str]] = None,
    match_rule: str = "ANY",
) -> int:
    watched_seats_json = json.dumps(watched_seats) if watched_seats else None
    query = """
    INSERT INTO watch_jobs (
        mode, status, city, movie_title, movie_url, 
        target_date, theatre_name, showtime_str, 
        watched_seats_json, match_rule
    ) VALUES (?, 'ACTIVE', ?, ?, ?, ?, ?, ?, ?, ?);
    """
    async with get_db() as conn:
        cursor = await conn.execute(
            query,
            (
                mode, city, movie_title, movie_url,
                target_date, theatre_name, showtime_str,
                watched_seats_json, match_rule,
            )
        )
        await conn.commit()
        return cursor.lastrowid

async def get_watch_jobs(status: Optional[str] = None) -> List[Dict[str, Any]]:
    async with get_db() as conn:
        if status:
            cursor = await conn.execute(
                "SELECT * FROM watch_jobs WHERE status = ? ORDER BY id DESC;",
                (status,)
            )
        else:
            cursor = await conn.execute("SELECT * FROM watch_jobs ORDER BY id DESC;")
        rows = await cursor.fetchall()
        return [_parse_job_row(row) for row in rows]

async def get_watch_job(job_id: int) -> Optional[Dict[str, Any]]:
    async with get_db() as conn:
        cursor = await conn.execute("SELECT * FROM watch_jobs WHERE id = ?;", (job_id,))
        row = await cursor.fetchone()
        return _parse_job_row(row) if row else None

async def update_watch_status(job_id: int, status: str) -> bool:
    async with get_db() as conn:
        cursor = await conn.execute(
            "UPDATE watch_jobs SET status = ? WHERE id = ?;",
            (status, job_id)
        )
        await conn.commit()
        return cursor.rowcount > 0

async def update_watch_check_result(
    job_id: int,
    summary: str,
    triggered: bool = False,
    triggered_details: Optional[Dict[str, Any]] = None,
) -> bool:
    status_clause = ""
    values: List[Any] = [summary]
    if triggered:
        status_clause = ", status = 'TRIGGERED', triggered_details_json = ?"
        values.append(json.dumps(triggered_details or {}))
    
    values.append(job_id)
    query = f"""
    UPDATE watch_jobs 
    SET last_checked_at = datetime('now'),
        last_check_summary = ?
        {status_clause}
    WHERE id = ?;
    """
    async with get_db() as conn:
        cursor = await conn.execute(query, tuple(values))
        await conn.commit()
        return cursor.rowcount > 0

async def delete_watch_job(job_id: int) -> bool:
    async with get_db() as conn:
        cursor = await conn.execute("DELETE FROM watch_jobs WHERE id = ?;", (job_id,))
        await conn.commit()
        return cursor.rowcount > 0

# Alert Logs CRUD
async def create_alert_log(
    watch_job_id: int,
    event_type: str,
    title: str,
    message: str,
) -> int:
    query = """
    INSERT INTO alert_logs (watch_job_id, event_type, title, message)
    VALUES (?, ?, ?, ?);
    """
    async with get_db() as conn:
        cursor = await conn.execute(query, (watch_job_id, event_type, title, message))
        await conn.commit()
        return cursor.lastrowid

async def get_unacknowledged_alerts() -> List[Dict[str, Any]]:
    async with get_db() as conn:
        cursor = await conn.execute(
            "SELECT * FROM alert_logs WHERE acknowledged = 0 ORDER BY id ASC;"
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": row["id"],
                "watch_job_id": row["watch_job_id"],
                "event_type": row["event_type"],
                "title": row["title"],
                "message": row["message"],
                "acknowledged": bool(row["acknowledged"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

async def acknowledge_alert(alert_id: int) -> bool:
    async with get_db() as conn:
        cursor = await conn.execute(
            "UPDATE alert_logs SET acknowledged = 1 WHERE id = ?;",
            (alert_id,)
        )
        await conn.commit()
        return cursor.rowcount > 0

async def get_recent_alerts(limit: int = 50) -> List[Dict[str, Any]]:
    async with get_db() as conn:
        cursor = await conn.execute(
            "SELECT * FROM alert_logs ORDER BY id DESC LIMIT ?;",
            (limit,)
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": row["id"],
                "watch_job_id": row["watch_job_id"],
                "event_type": row["event_type"],
                "title": row["title"],
                "message": row["message"],
                "acknowledged": bool(row["acknowledged"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]
