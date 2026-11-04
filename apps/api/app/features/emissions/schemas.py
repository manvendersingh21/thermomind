"""Pydantic response models for the emissions-watch feature (feature-local; not part of the shared contract)."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Pollutant = Literal["CO", "NOX"]

DISCLAIMER = (
    "Screening only; permit limits, averaging periods and CEMS QA/QC are site-specific; "
    "not a compliance determination."
)
THRESHOLD_LABEL = "screening threshold = p95 of this year, not a permit limit"
TARGET_NOTE = (
    "CO and NOX are real measurements (mg/m³, as published). The UCI paper used them as prediction targets; "
    "here they are used as measurements only, not as model outputs."
)


class Thresholds(BaseModel):
    co: float
    nox: float
    co_default_p95: float
    nox_default_p95: float
    co_source: Literal["default_p95_of_year", "user"]
    nox_source: Literal["default_p95_of_year", "user"]
    label: str = THRESHOLD_LABEL
    unit: str = "mg/m³"


class Distribution(BaseModel):
    n: int
    mean: Optional[float] = None
    min: Optional[float] = None
    p05: Optional[float] = None
    p25: Optional[float] = None
    p50: Optional[float] = None
    p75: Optional[float] = None
    p95: Optional[float] = None
    p99: Optional[float] = None
    max: Optional[float] = None


class Correlation(BaseModel):
    x: str
    y: str
    n: int
    pearson: Optional[float] = None
    spearman: Optional[float] = None


class Kpis(BaseModel):
    rows_analyzed: int
    # "hours" = hourly-aggregate samples; rows are ordered samples without timestamps and are not guaranteed contiguous.
    hours_above_co: int
    hours_above_nox: int
    hours_above_any: int
    pct_above_co: Optional[float] = None
    pct_above_nox: Optional[float] = None
    excursions_co: int
    excursions_nox: int
    excursions_total: int
    longest_excursion_samples: int = 0
    corr_co_tey: Correlation
    corr_co_at: Correlation
    corr_nox_tey: Correlation
    corr_nox_at: Correlation


class ProfileBin(BaseModel):
    """One load-proxy (or TIT) bin. Bin edges come from the whole year's deciles; stats from the analysed window."""

    bin: int
    lo: float
    hi: float
    n: int
    tey_median: Optional[float] = None
    tit_median: Optional[float] = None
    at_median: Optional[float] = None
    co_median: Optional[float] = None
    co_p25: Optional[float] = None
    co_p75: Optional[float] = None
    co_p95: Optional[float] = None
    nox_median: Optional[float] = None
    nox_p25: Optional[float] = None
    nox_p75: Optional[float] = None
    nox_p95: Optional[float] = None


class Excursion(BaseModel):
    excursion_id: str
    pollutant: Pollutant
    start_index: int  # row_index of first sample (inclusive)
    end_index: int  # row_index of last sample (inclusive)
    n_samples: int
    peak_value: float
    peak_index: int
    mean_value: float
    threshold: float
    peak_ratio: float  # peak / threshold
    tey_mean: Optional[float] = None
    tit_mean: Optional[float] = None
    at_mean: Optional[float] = None
    tit_change: Optional[float] = None  # TIT(end) - TIT(3 samples before start), degC
    context_tags: list[str] = Field(default_factory=list)
    context: str  # one-line heuristic context
    context_is_heuristic: bool = True


class SeriesRow(BaseModel):
    row_index: int
    co: Optional[float] = None
    nox: Optional[float] = None
    tey: Optional[float] = None
    tit: Optional[float] = None
    at: Optional[float] = None


class EmissionsResponse(BaseModel):
    dataset_id: str
    source_year: int
    start: int  # window start row_index (inclusive)
    end: int  # window end row_index (exclusive)
    total_rows_in_year: int
    provenance_kind: str = "real_observation"
    screening_only: bool = True
    disclaimer: str = DISCLAIMER
    target_note: str = TARGET_NOTE
    co_unit: str = "mg/m³"
    nox_unit: str = "mg/m³"
    thresholds: Thresholds
    kpis: Kpis
    distribution_co: Distribution
    distribution_nox: Distribution
    profile_tey: list[ProfileBin]
    profile_tit: list[ProfileBin]
    profile_basis: str
    context_rules: list[str]
    excursions: list[Excursion]
    excursions_truncated: bool = False
    series: list[SeriesRow]
    downsample_factor: int = 1
    series_note: str = ""
