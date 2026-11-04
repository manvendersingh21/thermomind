"""``InvestigationStore``: SQLite persistence for investigations (JSON blobs).

One connection per call, WAL journal, so concurrent requests from the thread
pool are safe. The whole ``Investigation`` is stored as JSON produced by
``model_dump_json`` and re-hydrated with ``model_validate_json``; a few columns
are mirrored for ordering/filtering.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from pydantic import ValidationError

from app.schemas import Investigation, ReviewRecord

log = logging.getLogger("thermomind.db.storage")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS investigations (
    case_id     TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL,
    status      TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    json        TEXT NOT NULL
)
"""


class InvestigationStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self._init_db()

    # --- connection helpers -----------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(_SCHEMA)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_investigations_created ON investigations(created_at DESC)"
            )

    # --- public API ---------------------------------------------------------------------
    def save(self, inv: Investigation) -> Investigation:
        """Insert or replace the investigation (idempotent on case_id)."""
        payload = inv.model_dump_json()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO investigations (case_id, created_at, status, scenario_id, json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(case_id) DO UPDATE SET
                    created_at = excluded.created_at,
                    status = excluded.status,
                    scenario_id = excluded.scenario_id,
                    json = excluded.json
                """,
                (inv.case_id, inv.created_at_utc, inv.status, inv.scenario.scenario_id, payload),
            )
        return inv

    def get(self, case_id: str) -> Investigation:
        """Return one investigation; raises KeyError when unknown (API maps to 404)."""
        with self._connect() as conn:
            row = conn.execute("SELECT json FROM investigations WHERE case_id = ?", (case_id,)).fetchone()
        if row is None:
            raise KeyError(f"investigation '{case_id}' not found")
        return Investigation.model_validate_json(row[0])

    def list(self) -> list[Investigation]:
        """All investigations, newest first (created_at, then rowid as a tie-breaker)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT case_id, json FROM investigations ORDER BY created_at DESC, rowid DESC"
            ).fetchall()
        out: list[Investigation] = []
        for case_id, payload in rows:
            try:
                out.append(Investigation.model_validate_json(payload))
            except ValidationError as exc:  # one corrupt/legacy row must not break the whole list
                log.warning("skipping investigation %s: stored JSON fails validation (%d error(s))",
                            case_id, exc.error_count())
        return out

    def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM investigations").fetchone()
        return int(row[0]) if row else 0

    def set_review(self, case_id: str, review: ReviewRecord) -> Investigation:
        """Attach a human review record. Never touches dataset rows or evidence."""
        inv = self.get(case_id)
        updated = inv.model_copy(update={"review": review})
        return self.save(updated)
