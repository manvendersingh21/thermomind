"""Simulated historian: replays real UCI rows as if a historian were feeding them.

Honesty rules: rows carry NO timestamps (the UCI data has none). Ordering is expressed by
``source_year`` + ``row_index`` + ``replay_tick`` (rows delivered since start). The replay
clock is only used to decide how many rows are due; it is never attached to a row.
"""
from __future__ import annotations

import math
import threading
import time
from typing import Any, Callable, Optional

import pandas as pd

from app.connectors.base import HistorianSource
from app.schemas import MEASUREMENT_KEYS, MEASUREMENTS

TIME_AXIS = "ordered_hourly_sample_without_actual_timestamp"
MAX_RATE = 1000.0
FrameProvider = Callable[[int], pd.DataFrame]


class HistorianError(ValueError):
    """Bad request to the historian (unknown year/tag/index)."""


def _clean(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


class SimulatedHistorian(HistorianSource):
    def __init__(self, frame_provider: FrameProvider, clock: Callable[[], float] = time.monotonic,
                 years: Optional[Callable[[], list[int]]] = None):
        self._provider = frame_provider
        self._clock = clock
        self._years = years
        self._lock = threading.RLock()
        self._frame: Optional[pd.DataFrame] = None
        self.running = False
        self.finished = False
        self.source_year: Optional[int] = None
        self.advance_rate = 1.0
        self.start_index = 0
        self.row_index: Optional[int] = None  # index of the most recently delivered row
        self.replay_tick = 0                  # rows delivered after the first one
        self._frac = 0.0
        self._last_clock: Optional[float] = None
        self._started = False

    # --- HistorianSource ----------------------------------------------------------------
    def describe(self) -> dict[str, Any]:
        return {
            "name": "Simulated historian (UCI replay)",
            "mode": "simulated",
            "simulated": True,
            "read_only": True,
            "source": "UCI Gas Turbine CO and NOx Emission Data Set (real public measurements, 2011-2015)",
            "time_axis": TIME_AXIS,
            "note": "Rows are real UCI samples replayed in order. No wall-clock timestamps are attached.",
        }

    def tags(self) -> list[dict[str, Any]]:
        return [
            {"tag": k, "name": MEASUREMENTS[k]["name"], "unit": MEASUREMENTS[k]["unit"],
             "provenance_kind": "real_observation", "simulated": True}
            for k in MEASUREMENT_KEYS
        ]

    def read_window(self, tag: str, year: int, start: int, end: int) -> list[dict[str, Any]]:
        if tag not in MEASUREMENT_KEYS:
            raise HistorianError(f"unknown tag '{tag}'")
        frame = self._year(year)
        if not (0 <= start < end <= len(frame)):
            raise HistorianError(f"window [{start}, {end}) out of range for {year} ({len(frame)} rows)")
        sub = frame.iloc[start:end]
        return [{"row_index": int(i), "value": _clean(v)} for i, v in zip(sub["row_index"], sub[tag])]

    def latest(self, n: int = 60) -> dict[str, Any]:
        with self._lock:
            self._sync()
            n = max(1, min(int(n), 2000))
            rows: list[dict[str, Any]] = []
            if self._frame is not None and self.row_index is not None:
                lo = max(self.start_index, self.row_index - n + 1)
                sub = self._frame.iloc[lo : self.row_index + 1]
                for pos, (_, r) in enumerate(sub.iterrows()):
                    idx = lo + pos
                    row: dict[str, Any] = {
                        "replay_tick": idx - self.start_index,
                        "source_year": int(self.source_year or 0),
                        "row_index": int(r["row_index"]),
                    }
                    for k in MEASUREMENT_KEYS:
                        row[k] = _clean(r[k])
                    rows.append(row)
            return {"simulated": True, "time_axis": TIME_AXIS, "cursor": self.cursor(), "rows": rows}

    # --- replay control -------------------------------------------------------------------
    def _year(self, year: int) -> pd.DataFrame:
        try:
            frame = self._provider(int(year))
        except KeyError as exc:
            raise HistorianError(str(exc)) from None
        if frame is None or len(frame) == 0:
            raise HistorianError(f"no rows for year {year}")
        return frame

    def start(self, year: int, advance_rate: float = 1.0, start_index: int = 0) -> dict[str, Any]:
        rate = float(advance_rate)
        if not math.isfinite(rate) or rate < 0 or rate > MAX_RATE:
            raise HistorianError(f"advance_rate must be between 0 and {MAX_RATE:g} rows per second")
        frame = self._year(year)
        if not (0 <= int(start_index) < len(frame)):
            raise HistorianError(f"start_index must be in [0, {len(frame)}) for {year}")
        with self._lock:
            self._frame = frame.reset_index(drop=True)
            self.source_year = int(year)
            self.advance_rate = rate
            self.start_index = int(start_index)
            self.row_index = int(start_index)
            self.replay_tick = 0
            self._frac = 0.0
            self._last_clock = self._clock()
            self.running = True
            self.finished = False
            self._started = True
            return self.cursor()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._sync()
            self.running = False
            self._last_clock = None
            return self.cursor()

    def tick(self, count: int = 1) -> dict[str, Any]:
        """Advance by whole rows regardless of the clock (works while stopped, once started)."""
        with self._lock:
            if not self._started:
                raise HistorianError("historian replay has not been started")
            self._sync()
            self._advance(max(1, int(count)))
            return self.cursor()

    def _advance(self, rows: int) -> None:
        assert self._frame is not None and self.row_index is not None
        last = len(self._frame) - 1
        step = min(rows, last - self.row_index)
        self.row_index += step
        self.replay_tick += step
        if self.row_index >= last:
            self.finished = True
            self.running = False

    def _sync(self) -> None:
        if not (self.running and self._frame is not None):
            return
        now = self._clock()
        if self._last_clock is not None:
            self._frac += max(0.0, now - self._last_clock) * self.advance_rate
        self._last_clock = now
        whole = int(self._frac)
        if whole > 0:
            self._frac -= whole
            self._advance(whole)

    def cursor(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self.running,
                "finished": self.finished,
                "started": self._started,
                "source_year": self.source_year,
                "row_index": self.row_index,
                "start_index": self.start_index if self._started else None,
                "replay_tick": self.replay_tick,
                "advance_rate": self.advance_rate,
                "rows_in_year": len(self._frame) if self._frame is not None else None,
                "simulated": True,
                "time_axis": TIME_AXIS,
            }

    def status(self) -> dict[str, Any]:
        with self._lock:
            self._sync()
            return self.cursor()
