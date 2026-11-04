"""Pydantic models for the maintenance planner (feature-local; not part of the shared contract).

Every economic input is a user-entered ASSUMPTION. Results are planning aids computed from the
real UCI measurements and the production baseline model; they require human review.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

DEFAULT_DATASET_ID = "ds_uci_551"

WashStatus = Literal["consider scheduling a wash (human decision)", "no economic case yet", "insufficient data"]
FilterStatus = Literal[
    "consider scheduling a filter change-out (human decision)", "no economic case yet", "insufficient data"
]

PLANNER_LABELS = ["REAL PUBLIC DATA", "MODEL-DERIVED", "USER ASSUMPTIONS", "HUMAN REVIEW REQUIRED"]
DISCLAIMER = (
    "Planning aid from historical data and your assumptions — not a maintenance instruction; "
    "schedule through site procedures."
)


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


class _EconomicsBase(BaseModel):
    dataset_id: str = Field(default=DEFAULT_DATASET_ID, min_length=1, max_length=128)
    year: int = Field(..., ge=1900, le=2100)
    energy_price_per_mwh: float = Field(default=60.0, ge=0, le=100_000, description="ASSUMPTION, currency per MWh")
    rolling_window_samples: int = Field(default=168, ge=24, le=2000, description="rolling median window (hourly samples)")


class CompressorWashRequest(_EconomicsBase):
    wash_outage_hours: float = Field(default=24.0, ge=0, le=2000)
    wash_direct_cost: float = Field(default=15_000.0, ge=0, le=1e9)
    expected_recovery_fraction: float = Field(default=0.7, gt=0, le=1)


class FilterChangeoutRequest(_EconomicsBase):
    afdp_limit_mbar: float = Field(default=7.0, gt=0, le=100)
    filter_change_cost: float = Field(default=20_000.0, ge=0, le=1e9)
    filter_outage_hours: float = Field(default=8.0, ge=0, le=2000)
    trend_window_samples: int = Field(default=720, ge=48, le=8760, description="trailing samples used for the linear trend")


# ---------------------------------------------------------------------------
# Shared result pieces
# ---------------------------------------------------------------------------


class Assumption(BaseModel):
    key: str
    label: str
    value: float | int | str
    unit: str
    source: Literal["user_input", "default"]


class CdpTrend(BaseModel):
    unit: str = "mbar (as published; unit under validation)"
    start_rolling: Optional[float] = None
    end_rolling: Optional[float] = None
    slope_per_1000_samples: Optional[float] = None
    note: str = (
        "Falling CDP at similar load is consistent with compressor fouling but has other causes; "
        "context only, not used in the economics."
    )


class WashSeriesPoint(BaseModel):
    row_index: int
    rolling_residual_mwh: Optional[float] = None
    cumulative_loss_mwh: Optional[float] = None
    cdp_rolling: Optional[float] = None


class FilterSeriesPoint(BaseModel):
    row_index: int
    afdp_rolling_mbar: Optional[float] = None
    trend_mbar: Optional[float] = None
    cumulative_loss_mwh: Optional[float] = None


class ProjectionPoint(BaseModel):
    row_index: int
    trend_mbar: float


class AfdpProxy(BaseModel):
    method: str
    coefficient_mwh_per_sample_per_mbar: Optional[float] = None
    residual_slope_mwh_per_mbar: Optional[float] = None
    model_sensitivity_mwh_per_mbar: Optional[float] = None
    training_years: list[int] = Field(default_factory=list)
    n_rows: int = 0
    statement: str = "Statistical association in this plant's data, not physics."
    notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


class _ResultBase(BaseModel):
    dataset_id: str
    year: int
    model_version: Optional[str] = None
    n_samples: int
    rolling_window_samples: int
    current_index: Optional[int] = None
    energy_unit_note: str = "TEY is MWh per hourly sample as published (≈ MWh per hour of operation); not converted."
    economics: dict[str, Optional[float]] = Field(default_factory=dict)
    break_even_reached: bool = False
    break_even_index: Optional[int] = None
    payback_hours_if_rate_persists: Optional[float] = None
    status_reasons: list[str] = Field(default_factory=list)
    computation: str
    assumptions: list[Assumption]
    caveats: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=lambda: list(PLANNER_LABELS))
    disclaimer: str = DISCLAIMER
    requires_human_review: Literal[True] = True


class CompressorWashResult(_ResultBase):
    status: WashStatus
    best_rolling_residual_mwh: Optional[float] = None
    best_index: Optional[int] = None
    current_rolling_residual_mwh: Optional[float] = None
    lost_output_rate_now_mwh_per_sample: Optional[float] = None
    cumulative_lost_output_mwh: Optional[float] = None
    typical_output_mwh_per_sample: Optional[float] = None
    cdp: CdpTrend = Field(default_factory=CdpTrend)
    series: list[WashSeriesPoint] = Field(default_factory=list)


class FilterChangeoutResult(_ResultBase):
    status: FilterStatus
    afdp_limit_mbar: float
    trend_window_samples: int
    current_afdp_rolling_mbar: Optional[float] = None
    clean_afdp_mbar: Optional[float] = None
    clean_index: Optional[int] = None
    trend_slope_mbar_per_1000_samples: Optional[float] = None
    limit_reached: bool = False
    samples_to_limit: Optional[float] = None
    projected_limit_index: Optional[int] = None
    afdp_training_range_mbar: Optional[list[float]] = None
    lost_output_rate_now_mwh_per_sample: Optional[float] = None
    cumulative_lost_output_mwh: Optional[float] = None
    typical_output_mwh_per_sample: Optional[float] = None
    proxy: AfdpProxy
    series: list[FilterSeriesPoint] = Field(default_factory=list)
    projection: list[ProjectionPoint] = Field(default_factory=list)


class PlannerOptions(BaseModel):
    dataset_id: str
    data_available: bool
    years: list[int]
    default_year: Optional[int] = None
    model_available: bool
    model_version: Optional[str] = None
    afdp_training_range_mbar: Optional[list[float]] = None
    wash_defaults: dict[str, float | int]
    filter_defaults: dict[str, float | int]
    labels: list[str] = Field(default_factory=lambda: list(PLANNER_LABELS))
    disclaimer: str = DISCLAIMER
    notes: list[str] = Field(default_factory=list)
