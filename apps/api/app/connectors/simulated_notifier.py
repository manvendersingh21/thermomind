"""Simulated notifier: in-app outbox only. Nothing leaves the process (no email/SMS)."""
from __future__ import annotations

import logging
import secrets
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any

from app.connectors.base import Notifier

log = logging.getLogger("thermomind.connectors.notifier")

MAX_ITEMS = 500  # in-memory retention: oldest items are dropped


class SimulatedNotifier(Notifier):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: deque[dict[str, Any]] = deque(maxlen=MAX_ITEMS)

    def notify(self, persona: str, message: str) -> dict[str, Any]:
        item = {
            "id": f"ntf_conn_{secrets.token_hex(4)}",
            "persona": persona,
            "message": message,
            "delivery": "in_app_simulated",
            "source": "connector_outbox",
            "simulated": True,
            "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        }
        with self._lock:
            self._items.append(item)
        return {"delivery": "in_app_simulated", "id": item["id"], "simulated": True}

    def outbox(self, limit: int = 100) -> list[dict[str, Any]]:
        """Own outbox plus plant work-request notifications (guarded import), newest first."""
        with self._lock:
            items = [dict(i) for i in self._items]
        items.extend(self._plant_notifications(limit))
        items.sort(key=lambda i: i.get("created_at_utc", ""), reverse=True)
        return items[: max(1, int(limit))]

    @staticmethod
    def _plant_notifications(limit: int) -> list[dict[str, Any]]:
        try:
            from app.plant import store
            from app.plant.personas import PERSONAS
        except Exception:  # noqa: BLE001 - plant package optional
            return []
        out: list[dict[str, Any]] = []
        try:
            for pid in PERSONAS:
                for n in store.list_notifications(pid, limit):
                    d = n.model_dump()
                    d.update({"source": "plant_work_requests", "simulated": True})
                    out.append(d)
        except Exception as exc:  # noqa: BLE001
            log.warning("plant notifications unavailable: %s", type(exc).__name__)
        return out
