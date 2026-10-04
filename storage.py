import sqlite3
import threading
from datetime import datetime, time, timedelta
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


def _exclusive_upper_bound(period_to):
    """Верхняя граница периода включительная, а сравнение строгое.

    Записи хранятся с временем (например, 2026-03-31T19:40:00), поэтому
    нестрогое сравнение по дате отбросило бы вечерние записи последнего дня:
    строка со временем больше строки, состоящей только из даты. Приводим
    границу к началу следующего дня и сравниваем строго.
    """
    day = datetime.fromisoformat(period_to).date()
    return datetime.combine(day + timedelta(days=1), time.min).isoformat()


def get_workouts(user_id, period_from=None, period_to=None, limit=None):
    query = (
        "SELECT id, user_id, performed_at, reported_at, kind, details "
        "FROM workout_entries WHERE user_id = ?"
    )
    params = [user_id]
    if period_from is not None:
        query += " AND performed_at >= ?"
        params.append(period_from)
    if period_to is not None:
        query += " AND performed_at < ?"
        params.append(_exclusive_upper_bound(period_to))
    query += " ORDER BY performed_at DESC"
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)
    with _lock:
        rows = _conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]