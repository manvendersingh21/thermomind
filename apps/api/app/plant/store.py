"""SQLite persistence for plant-ops records (same DB file as investigations, new tables).

The DB path is read from ``app.config.DB_PATH`` on every call so tests that repoint the config work.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Optional

from app import config
from app.plant.schemas import Notification, WhatIfSession, WorkRequest

MAX_SESSIONS = 500  # whatif_sessions retention (newest rows kept)

_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS plant_work_requests (
        id TEXT PRIMARY KEY, case_id TEXT NOT NULL, persona TEXT NOT NULL, status TEXT NOT NULL,
        created_at TEXT NOT NULL, json TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS idx_pwr_persona ON plant_work_requests(persona, created_at DESC)",
    """CREATE TABLE IF NOT EXISTS plant_notifications (
        id TEXT PRIMARY KEY, persona TEXT NOT NULL, read INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL, json TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS idx_pn_persona ON plant_notifications(persona, created_at DESC)",
    """CREATE TABLE IF NOT EXISTS whatif_sessions (
        session_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, persona TEXT NOT NULL,
        status TEXT NOT NULL, json TEXT NOT NULL)""",
]
_init_lock = threading.Lock()
_initialised: set[str] = set()


def _connect() -> sqlite3.Connection:
    path = Path(config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    key = str(path.resolve())
    if key not in _initialised:
        with _init_lock:
            for stmt in _SCHEMA:
                conn.execute(stmt)
            conn.commit()
            _initialised.add(key)
    return conn


# ----------------------------------------------------------------------------- work requests
def save_work_request(wr: WorkRequest) -> WorkRequest:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO plant_work_requests (id, case_id, persona, status, created_at, json) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET status=excluded.status, persona=excluded.persona, json=excluded.json",
            (wr.id, wr.case_id, wr.assigned_persona, wr.status, wr.created_at_utc, wr.model_dump_json()))
    return wr


def get_work_request(wr_id: str) -> WorkRequest:
    with _connect() as conn:
        row = conn.execute("SELECT json FROM plant_work_requests WHERE id=?", (wr_id,)).fetchone()
    if row is None:
        raise KeyError(f"work request '{wr_id}' not found")
    return WorkRequest.model_validate_json(row[0])


def list_work_requests(persona: Optional[str] = None, status: Optional[str] = None,
                       case_id: Optional[str] = None) -> list[WorkRequest]:
    sql, args = "SELECT json FROM plant_work_requests WHERE 1=1", []
    for col, val in (("persona", persona), ("status", status), ("case_id", case_id)):
        if val:
            sql += f" AND {col}=?"
            args.append(val)
    sql += " ORDER BY created_at DESC, rowid DESC"
    with _connect() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [WorkRequest.model_validate_json(r[0]) for r in rows]


# ----------------------------------------------------------------------------- notifications
def save_notification(n: Notification) -> Notification:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO plant_notifications (id, persona, read, created_at, json) VALUES (?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET read=excluded.read, json=excluded.json",
            (n.id, n.persona, int(n.read), n.created_at_utc, n.model_dump_json()))
    return n


def get_notification(n_id: str) -> Notification:
    with _connect() as conn:
        row = conn.execute("SELECT json FROM plant_notifications WHERE id=?", (n_id,)).fetchone()
    if row is None:
        raise KeyError(f"notification '{n_id}' not found")
    return Notification.model_validate_json(row[0])


def list_notifications(persona: str, limit: int = 100) -> list[Notification]:
    with _connect() as conn:
        rows = conn.execute("SELECT json FROM plant_notifications WHERE persona=? "
                            "ORDER BY created_at DESC, rowid DESC LIMIT ?", (persona, int(limit))).fetchall()
    return [Notification.model_validate_json(r[0]) for r in rows]


# ----------------------------------------------------------------------------- what-if sessions
def save_session(s: WhatIfSession) -> WhatIfSession:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO whatif_sessions (session_id, created_at, persona, status, json) VALUES (?,?,?,?,?) "
            "ON CONFLICT(session_id) DO UPDATE SET status=excluded.status, json=excluded.json",
            (s.session_id, s.created_at_utc, s.persona, s.status, s.model_dump_json()))
        conn.execute(  # retention: keep only the newest MAX_SESSIONS rows
            "DELETE FROM whatif_sessions WHERE rowid NOT IN "
            "(SELECT rowid FROM whatif_sessions ORDER BY created_at DESC, rowid DESC LIMIT ?)", (MAX_SESSIONS,))
    return s


def get_session(session_id: str) -> WhatIfSession:
    with _connect() as conn:
        row = conn.execute("SELECT json FROM whatif_sessions WHERE session_id=?", (session_id,)).fetchone()
    if row is None:
        raise KeyError(f"what-if session '{session_id}' not found")
    return WhatIfSession.model_validate_json(row[0])


def list_sessions(limit: int = 20) -> list[WhatIfSession]:
    with _connect() as conn:
        rows = conn.execute("SELECT json FROM whatif_sessions ORDER BY created_at DESC, rowid DESC LIMIT ?",
                            (int(limit),)).fetchall()
    return [WhatIfSession.model_validate_json(r[0]) for r in rows]
