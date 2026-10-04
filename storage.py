import sqlite3
import threading
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
DB_PATH = DATA_DIR / "lifekick.db"

_lock = threading.Lock()
_conn = None


def init_db():
    global _conn
    DATA_DIR.mkdir(exist_ok=True)
    _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA journal_mode=WAL;")
    _conn.execute(
        """
        CREATE TABLE IF NOT EXISTS workout_entries (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL,
            performed_at TEXT NOT NULL,
            reported_at  TEXT NOT NULL,
            kind         TEXT,
            details      TEXT
        )
        """
    )
    _conn.commit()


def save_workout(user_id, performed_at, reported_at, kind, details):
    with _lock:
        _conn.execute(
            "INSERT INTO workout_entries (user_id, performed_at, reported_at, kind, details) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, performed_at, reported_at, kind, details),
        )
        _conn.commit()


def get_workouts(user_id, since=None, limit=None):
    query = (
        "SELECT id, user_id, performed_at, reported_at, kind, details "
        "FROM workout_entries WHERE user_id = ?"
    )
    params = [user_id]
    if since is not None:
        query += " AND performed_at >= ?"
        params.append(since)
    query += " ORDER BY performed_at DESC"
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)
    with _lock:
        rows = _conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]