"""Pydantic models for the instrument-health scorecard endpoint."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.schemas import SampleRange

DISCLAIMER = "Statistical screening on historical data — not a calibration certificate."
SensorStatus = Literal["ok", "watch", "check"]


class CouplingPair(BaseModel):
    pair: str  # e.g. "CDP~TEY"
    a: str
    b: str
    expected: str  # human text: "strong positive", "weak positive", "negative"
    r_year: Optional[float] = None
    r_train: Optional[float] = None
    delta: Optional[float] = None
    drift: bool = False


class SensorHealth(BaseModel):
    key: str
    name: str
    unit: str
    rows: int
    missing: int
    out_of_range: int
    range_source: str  # "model.feature_ranges_train" | "training_years_min_max" | "unavailable"
    range_lo: Optional[float] = None
    range_hi: Optional[float] = None
    flatline_runs: int
    flatline_rows: int
    spikes: int  # contiguous spike events
    spike_points: int  # individual samples with robust z >= threshold
    spike_baseline_pct: float = 0.0  # same sensor's spike-sample rate over 2011-2013 (%)
    coupling: list[CouplingPair] = Field(default_factory=list)
    coupling_drift_pairs: list[str] = Field(default_factory=list)
    penalties: dict[str, float] = Field(default_factory=dict)
    score: float
    status: SensorStatus
    computation: str
    what_to_check: str


class ScorecardSummary(BaseModel):
    headline: str
    trust: list[str]  # status ok
    use_with_cross_check: list[str]  # status watch
    verify_first: list[str]  # status check
    mean_score: float
    coupling_drift_pairs: list[str]
    disclaimer: str = DISCLAIMER


class Scorecard(BaseModel):
    dataset_id: str
    year: int
    window: SampleRange
    sensors: list[SensorHealth]
    summary: ScorecardSummary
    computed_at_utc: str
    method_notes: list[str]
    provenance_kind: str = "real_observation"
    disclaimer: str = DISCLAIMER
