"""SQLite tables owned by the collaboration layer (same DB file as investigations; only these are written).

``collab_decisions`` (autonomy-policy log) and ``onboarding_briefs``. The DB path is read from
``app.config.DB_PATH`` on every call so tests that repoint the config work. Reads of OTHER workstreams' tables
(read-only, for the activity feed) go through ``read_json_rows`` which returns [] when a table is missing.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from app import config
from app.features.collab.schemas import AutoDecision, OnboardingBrief

MAX_ROWS = 2000

_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS collab_decisions (
        decision_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, decision TEXT NOT NULL,
        created_at TEXT NOT NULL, json TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS idx_cd_case ON collab_decisions(case_id, created_at)",
    """CREATE TABLE IF NOT EXISTS onboarding_briefs (
        brief_id TEXT PRIMARY KEY, persona TEXT NOT NULL, created_at TEXT NOT NULL, mode TEXT NOT NULL,
        json TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS idx_ob_persona ON onboarding_briefs(persona, created_at DESC)",
]


def db_path() -> Path:
    return Path(config.DB_PATH)


def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    for stmt in _SCHEMA:
        conn.execute(stmt)
    return conn


# ----------------------------------------------------------------------------- decisions
def save_decision(d: AutoDecision) -> AutoDecision:
    with _connect() as conn:
        conn.execute("INSERT INTO collab_decisions (decision_id, case_id, decision, created_at, json) "
                     "VALUES (?,?,?,?,?)", (d.decision_id, d.case_id, d.decision, d.ts_utc, d.model_dump_json()))
        conn.execute("DELETE FROM collab_decisions WHERE rowid NOT IN "
                     "(SELECT rowid FROM collab_decisions ORDER BY created_at DESC, rowid DESC LIMIT ?)", (MAX_ROWS,))
    return d


def get_decision(decision_id: str) -> AutoDecision:
    with _connect() as conn:
        row = conn.execute("SELECT json FROM collab_decisions WHERE decision_id=?", (decision_id,)).fetchone()
    if row is None:
        raise KeyError(f"decision '{decision_id}' not found")
    return AutoDecision.model_validate_json(row[0])


def list_decisions(case_id: Optional[str] = None, limit: int = 200) -> list[AutoDecision]:
    sql, args = "SELECT json FROM collab_decisions", []
    if case_id:
        sql += " WHERE case_id=?"
        args.append(case_id)
    sql += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
    args.append(int(limit))
    with _connect() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [AutoDecision.model_validate_json(r[0]) for r in rows]


def decision_counts() -> dict[str, int]:
    """Counts over the LATEST decision per case (a human reopen supersedes an auto-triage)."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT decision, COUNT(*) FROM (SELECT case_id, decision, MAX(rowid) FROM collab_decisions "
            "GROUP BY case_id) GROUP BY decision").fetchall()
    out = {k: 0 for k in ("auto_triaged_no_action", "requires_human", "human_override_reopened")}
    for decision, n in rows:
        out[decision] = int(n)
    out["total"] = sum(out.values())
    return out


# ----------------------------------------------------------------------------- onboarding briefs
def save_brief(b: OnboardingBrief) -> OnboardingBrief:
    with _connect() as conn:
        conn.execute("INSERT INTO onboarding_briefs (brief_id, persona, created_at, mode, json) VALUES (?,?,?,?,?)",
                     (b.brief_id, b.persona, b.created_at_utc, b.mode, b.model_dump_json()))
        conn.execute("DELETE FROM onboarding_briefs WHERE rowid NOT IN "
                     "(SELECT rowid FROM onboarding_briefs ORDER BY created_at DESC, rowid DESC LIMIT ?)", (MAX_ROWS,))
    return b


def latest_brief(persona: str) -> Optional[OnboardingBrief]:
    with _connect() as conn:
        row = conn.execute("SELECT json FROM onboarding_briefs WHERE persona=? ORDER BY created_at DESC, rowid DESC "
                           "LIMIT 1", (persona,)).fetchone()
    return OnboardingBrief.model_validate_json(row[0]) if row else None


# ----------------------------------------------------------------------------- read-only access to other tables
def read_json_rows(table: str, like: Optional[str] = None, limit: int = 2000) -> list[str]:
    """JSON column of another workstream's table, optionally pre-filtered by LIKE; [] if missing/unreadable."""
    if table not in {"plant_notifications", "whatif_sessions", "handover_notes", "plant_work_requests"}:
        raise ValueError(f"table '{table}' is not readable by the collaboration layer")
    path = db_path()
    if not path.exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return []
    try:
        sql, args = f"SELECT json FROM {table}", []  # table name checked against the allow-list above
        if like:
            sql += " WHERE json LIKE ?"
            args.append(f"%{like}%")
        sql += " ORDER BY rowid DESC LIMIT ?"
        args.append(int(limit))
        return [r[0] for r in conn.execute(sql, args).fetchall()]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def table_exists(table: str) -> bool:
    path = db_path()
    if not path.exists():
        return False
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
        try:
            return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None
        finally:
            conn.close()
    except sqlite3.Error:
        return False
