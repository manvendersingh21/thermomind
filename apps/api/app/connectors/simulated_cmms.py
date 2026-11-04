"""Simulated CMMS sink: keeps DRAFT work orders in memory. Nothing is ever submitted."""
from __future__ import annotations

import secrets
import threading
from datetime import datetime, timezone
from typing import Any

from app.connectors.base import CmmsSink

DRAFT_STATUS = "DRAFT_NOT_SUBMITTED"


class SimulatedCmms(CmmsSink):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._drafts: list[dict[str, Any]] = []

    def draft_work_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        draft = {
            "id": f"wo_draft_{secrets.token_hex(4)}",
            "status": DRAFT_STATUS,
            "simulated": True,
            "payload": dict(payload),
            # real creation time of the draft record, not a plant-data timestamp
            "drafted_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "note": "Simulated CMMS. Draft only; never sent to a real maintenance system.",
        }
        with self._lock:
            self._drafts.append(draft)
        return {"id": draft["id"], "status": DRAFT_STATUS}

    def drafts(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(d) for d in reversed(self._drafts)]
