"""In-memory dataset bundles plus a tiny SQLite registry.

The frames themselves live in process memory (the UCI set is ~37k x 13 floats);
SQLite only records *which* datasets exist (id, source, created_at, summary JSON)
so other processes/tools can see what was loaded. Raw frames are never mutated:
``year_frame``/``window`` hand out copies.
"""
from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from app import config
from app.data.provenance import UCI_PLANT_DESCRIPTION, uci_provenance_notes, upload_provenance_notes
from app.data.validator import MEASUREMENT_COLUMNS
from app.schemas import (
    MEASUREMENTS,
    UCI_CITATION,
    UCI_LICENSE,
    UCI_SOURCE_ID,
    UCI_URL,
    DatasetDetail,
    DatasetSummary,
    MeasurementInfo,
    SeriesPoint,
    SeriesResponse,
    SourceFileInfo,
)

UNKNOWN_YEAR = -1
UCI_DATASET_ID = "ds_uci_551"
TIME_AXIS_TYPE = "ordered_hourly_sample_without_actual_timestamp"


def _clean_float(value: object) -> float | None:
    """float or None (NaN/inf/None -> None) so Pydantic/JSON never see NaN."""
    if value is None:
        return None
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


@dataclass
class DatasetBundle:
    dataset_id: str
    frame: pd.DataFrame  # columns: source_year(int), row_index(int, 0-based per year), + MEASUREMENT_COLUMNS
    source: str
    source_files: list[SourceFileInfo]
    warnings: list[str]
    created_at_utc: str
    has_timestamps: bool = field(default=False)  # always False for UCI; never fabricated

    # --- derived metadata ----------------------------------------------------------
    @property
    def is_uci(self) -> bool:
        return self.source == UCI_SOURCE_ID

    def years(self) -> list[int]:
        if self.frame.empty:
            return []
        years = sorted(int(y) for y in self.frame["source_year"].unique())
        return [y for y in years if y != UNKNOWN_YEAR]

    def rows_per_year(self) -> dict[str, int]:
        if self.frame.empty:
            return {}
        counts = self.frame["source_year"].value_counts().sort_index()
        return {("unknown" if int(y) == UNKNOWN_YEAR else str(int(y))): int(n) for y, n in counts.items()}

    def _source_meta(self) -> dict[str, str | None]:
        if self.is_uci:
            return {
                "source_license": UCI_LICENSE,
                "source_url": UCI_URL,
                "citation": UCI_CITATION,
                "plant": UCI_PLANT_DESCRIPTION,
            }
        return {"source_license": None, "source_url": None, "citation": None, "plant": None}

    def summary(self) -> DatasetSummary:
        return DatasetSummary(
            dataset_id=self.dataset_id,
            source=self.source,
            row_count=int(len(self.frame)),
            years=self.years(),
            columns=list(MEASUREMENT_COLUMNS),
            has_timestamps=self.has_timestamps,
            time_axis_type=TIME_AXIS_TYPE,
            created_at_utc=self.created_at_utc,
            warnings=list(self.warnings),
            **self._source_meta(),
        )

    def measurement_stats(self) -> list[MeasurementInfo]:
        out: list[MeasurementInfo] = []
        for key in MEASUREMENT_COLUMNS:
            info = MEASUREMENTS[key]
            series = self.frame[key] if key in self.frame.columns else pd.Series(dtype="float64")
            valid = series.dropna()
            out.append(
                MeasurementInfo(
                    key=key,
                    name=info["name"],
                    unit=info["unit"],
                    count=int(valid.size),
                    missing=int(series.size - valid.size),
                    min=_clean_float(valid.min()) if valid.size else None,
                    max=_clean_float(valid.max()) if valid.size else None,
                    mean=_clean_float(valid.mean()) if valid.size else None,
                    median=_clean_float(valid.median()) if valid.size else None,
                )
            )
        return out

    def provenance_notes(self) -> list[str]:
        if self.is_uci:
            return uci_provenance_notes()
        return upload_provenance_notes([sf.filename for sf in self.source_files])

    def detail(self) -> DatasetDetail:
        return DatasetDetail(
            **self.summary().model_dump(),
            source_files=list(self.source_files),
            measurements=self.measurement_stats(),
            rows_per_year=self.rows_per_year(),
            provenance_notes=self.provenance_notes(),
        )

    # --- frame access ----------------------------------------------------------------
    def year_frame(self, year: int) -> pd.DataFrame:
        """Rows for one source year, sorted by row_index, index reset. Empty frame if the year is absent."""
        mask = self.frame["source_year"] == int(year)
        return self.frame.loc[mask].sort_values("row_index", kind="stable").reset_index(drop=True).copy()

    def window(self, year: int, start: int, end: int) -> pd.DataFrame:
        """Slice ``[start, end)`` of ``year_frame(year)``; raises IndexError when out of range."""
        yf = self.year_frame(year)
        n = len(yf)
        if n == 0:
            raise IndexError(f"dataset {self.dataset_id} has no rows for year {year}")
        if not (0 <= start < end <= n):
            raise IndexError(
                f"window [{start}, {end}) is out of range for year {year} (0..{n} rows available)"
            )
        return yf.iloc[start:end].reset_index(drop=True).copy()


class DatasetRepository:
    """Keeps bundles in memory and mirrors a registry row into SQLite."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = Path(db_path) if db_path is not None else Path(config.DB_PATH)
        self._bundles: dict[str, DatasetBundle] = {}
        self._init_db()

    # --- sqlite registry ---------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS datasets (
                    dataset_id TEXT PRIMARY KEY,
                    source     TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata   TEXT NOT NULL
                )
                """
            )

    def _upsert_registry(self, bundle: DatasetBundle) -> None:
        metadata = json.dumps(bundle.detail().model_dump(mode="json"), ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO datasets (dataset_id, source, created_at, metadata) VALUES (?, ?, ?, ?)
                ON CONFLICT(dataset_id) DO UPDATE SET
                    source = excluded.source, created_at = excluded.created_at, metadata = excluded.metadata
                """,
                (bundle.dataset_id, bundle.source, bundle.created_at_utc, metadata),
            )

    def registry_rows(self) -> list[dict]:
        """Registry contents (ids/sources/created_at/metadata) — for diagnostics and tests."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT dataset_id, source, created_at, metadata FROM datasets ORDER BY created_at"
            ).fetchall()
        return [
            {"dataset_id": r[0], "source": r[1], "created_at": r[2], "metadata": json.loads(r[3])}
            for r in rows
        ]

    # --- public API ----------------------------------------------------------------------
    def register(self, bundle: DatasetBundle) -> DatasetBundle:
        self._bundles[bundle.dataset_id] = bundle
        self._upsert_registry(bundle)
        return bundle

    def get(self, dataset_id: str) -> DatasetBundle:
        try:
            return self._bundles[dataset_id]
        except KeyError:
            raise KeyError(f"dataset '{dataset_id}' not found") from None

    def list(self) -> list[DatasetSummary]:
        return [b.summary() for b in self._bundles.values()]

    def seed_uci(self, raw_dir: Path) -> DatasetBundle:
        """Load the UCI files once; subsequent calls return the already-loaded bundle."""
        existing = self._bundles.get(UCI_DATASET_ID)
        if existing is not None:
            return existing
        from app.data.uci_loader import load_uci_dir  # local import avoids a circular import

        return self.register(load_uci_dir(Path(raw_dir)))

    def series(
        self,
        dataset_id: str,
        measure: str,
        year: int,
        start: int,
        limit: int,
        max_points: int = config.MAX_SERIES_POINTS,
    ) -> SeriesResponse:
        """Real observations for one measurement, downsampled by a uniform stride to <= max_points.

        ``start``/``limit`` are clamped to the year's bounds; ``end`` is exclusive.
        Raises KeyError for an unknown dataset, measurement or year (API maps to 404).
        """
        bundle = self.get(dataset_id)
        if measure not in MEASUREMENT_COLUMNS:
            raise KeyError(f"unknown measurement '{measure}' (expected one of {', '.join(MEASUREMENT_COLUMNS)})")
        yf = bundle.year_frame(year)
        total = len(yf)
        if total == 0:
            raise KeyError(f"dataset '{dataset_id}' has no rows for year {year}")

        start = max(0, min(int(start), total))
        limit = int(limit) if limit is not None and int(limit) > 0 else total
        end = min(start + limit, total)
        max_points = max(1, int(max_points))
        n = end - start
        stride = 1 if n <= max_points else int(math.ceil(n / max_points))

        points: list[SeriesPoint] = []
        if n > 0:
            idx = yf["row_index"].to_numpy()[start:end:stride]
            vals = yf[measure].to_numpy(dtype="float64")[start:end:stride]
            points = [
                SeriesPoint(row_index=int(i), value=(None if not np.isfinite(v) else float(v)))
                for i, v in zip(idx, vals)
            ]

        return SeriesResponse(
            dataset_id=dataset_id,
            measure=measure,
            unit=MEASUREMENTS[measure]["unit"],
            source_year=int(year),
            start=start,
            end=end,
            total_rows_in_year=total,
            downsample_factor=stride,
            points=points,
            provenance_kind="real_observation",
            scenario_id=None,
            synthetic=False,
            source=bundle.source,
            time_axis_type=TIME_AXIS_TYPE,
        )
