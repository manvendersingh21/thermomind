"""Adapter interfaces for plant systems.

ThermoMind is read-only decision support. A pilot would plug real systems in behind
these interfaces; everything in this repo that implements them is SIMULATED and says so.

Direction of data flow, by design:
  historian  -> ThermoMind   read only (HistorianSource)
  ThermoMind -> CMMS         DRAFT work orders only, never submitted (CmmsSink)
  ThermoMind -> people       notifications (Notifier)
  ThermoMind -> control      NOTHING. ControlSystem has no read or write methods.

A future OPC UA / PI Web API client would implement ``HistorianSource`` (browse + read
history) and nothing else. There is no write path to model, so none exists.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

CONTROL_NOTE = (
    "No control-system adapter exists in ThermoMind. Read-only decision support by design."
)


class HistorianSource(ABC):
    """Read-only process-data source. Implementations must not expose any write method."""

    @abstractmethod
    def describe(self) -> dict[str, Any]:
        """Name, kind, mode ('simulated' | 'live'), and provenance of the source."""

    @abstractmethod
    def tags(self) -> list[dict[str, Any]]:
        """Available tags/measurements with units."""

    @abstractmethod
    def read_window(self, tag: str, year: int, start: int, end: int) -> list[dict[str, Any]]:
        """Rows ``[start, end)`` of one tag for one source year, as ``{row_index, value}`` dicts."""

    @abstractmethod
    def latest(self, n: int) -> dict[str, Any]:
        """The last ``n`` rows delivered by the source, plus its cursor."""


class CmmsSink(ABC):
    """Maintenance-system sink. Drafts only: there is deliberately no submit method."""

    @abstractmethod
    def draft_work_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Store a draft; returns ``{"id": ..., "status": "DRAFT_NOT_SUBMITTED"}``."""


class Notifier(ABC):
    @abstractmethod
    def notify(self, persona: str, message: str) -> dict[str, Any]:
        """Deliver a message; simulated delivery returns ``{"delivery": "in_app_simulated", ...}``."""


class ControlSystem:
    """Placeholder for the DCS/PLC/SCADA boundary. It has NO write methods by design.

    The only method is ``capabilities()``, which states that nothing is connected. Do not
    add ``write``/``set``/``send``/``command`` here. If a pilot needs process data, add a
    read-only ``HistorianSource`` (OPC UA read client or PI/historian export), not a path
    into the control system.
    """

    def capabilities(self) -> dict[str, Any]:
        return {"read": False, "write": False, "note": CONTROL_NOTE}
