"""SQLite persistence for deliberation sessions (table ``deliberations``, same DB file as investigations).

The DB path is read from ``app.config.DB_PATH`` on every call so tests that repoint the config work.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Optional

from app import config
from app.features.deliberation.schemas import DeliberationSession

MAX_ROWS = 500
_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS deliberations (
        id TEXT PRIMARY KEY, created_at TEXT NOT NULL, case_id TEXT, persona TEXT NOT NULL,
        status TEXT NOT NULL, json TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS idx_delib_case ON deliberations(case_id, created_at DESC)",
]
_lock = threading.Lock()
_initialised: set[str] = set()


def _connect() -> sqlite3.Connection:
    path = Path(config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    key = str(path.resolve())
    if key not in _initialised:
        with _lock:
            for stmt in _SCHEMA:
                conn.execute(stmt)
            conn.commit()
            _initialised.add(key)
    return conn


def save(s: DeliberationSession) -> DeliberationSession:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO deliberations (id, created_at, case_id, persona, status, json) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET status=excluded.status, json=excluded.json",
            (s.deliberation_id, s.created_at_utc, s.case_id, s.persona, s.status, s.model_dump_json()))
        conn.execute("DELETE FROM deliberations WHERE rowid NOT IN "
                     "(SELECT rowid FROM deliberations ORDER BY created_at DESC, rowid DESC LIMIT ?)", (MAX_ROWS,))
    return s


def get(deliberation_id: str) -> DeliberationSession:
    with _connect() as conn:
        row = conn.execute("SELECT json FROM deliberations WHERE id=?", (deliberation_id,)).fetchone()
    if row is None:
        raise KeyError(f"deliberation '{deliberation_id}' not found")
    return DeliberationSession.model_validate_json(row[0])


def list_(case_id: Optional[str] = None, limit: int = 20) -> list[DeliberationSession]:
    sql, args = "SELECT json FROM deliberations", []
    if case_id:
        sql += " WHERE case_id=?"
        args.append(case_id)
    sql += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
    args.append(int(limit))
    with _connect() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [DeliberationSession.model_validate_json(r[0]) for r in rows]
