"""Pydantic models for the grid-resilience feature (mounted under /api/grid by the principal).

Grid-local provenance vocabulary (superset of app.schemas.ProvenanceKind):
  real_observation  - computed directly from UCI measurements in the selected window / training years
  model_derived     - statistical fit on real data (e.g. TEY~AT slope); correlational, not an OEM curve
  derived_from_history - a statistic derived from historical real data (percentile, margin to a historical p99);
                      not a raw measurement and not an OEM limit
  assumption        - a user-editable input or a quantity computed only from user inputs (nameplate, H, pf, ...)
  synthetic_overlay - produced by the synthetic S05 grid-event overlay (drills only)
  simulated         - the simulated local network topology used by contingency options (not a real network)
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas import SampleRange, Transformation

GridProvenance = Literal["real_observation", "model_derived", "derived_from_history", "assumption", "synthetic_overlay",
                         "simulated"]
CardStatus = Literal["ok", "watch", "limited", "info"]
GridEvent = Literal["frequency_dip", "overvoltage", "load_step"]
ContingencyConstraint = Literal["transformer_thermal", "line_limit", "unit_derate"]

READINESS_DISCLAIMER = (
    "Advisory readiness indicators from historical public data plus labelled assumptions. "
    "Not an OEM capability curve, not a grid-code compliance assessment, and not a control system."
)
DRILL_BANNER = "Synthetic drill. Advisory only. This software issues no control actions."
BRIEF_DISCLAIMER = (
    "DRAFT operator support brief for a SYNTHETIC drill. Advisory only: ThermoMind changes no operating parameter "
    "and issues no control action. All operational decisions remain with authorised control-room personnel under the "
    "applicable grid code, TSO instructions and site procedures."
)
CONTINGENCY_DISCLAIMER = (
    "Options for human evaluation. No switching, load transfer or dispatch change is performed by this software."
)


class GridNumber(BaseModel):
    key: str
    label: str
    value: Optional[float]
    unit: str
    provenance: GridProvenance
    computation: str
    note: Optional[str] = None


class StatusCard(BaseModel):
    key: str
    title: str
    status: CardStatus
    headline: str
    numbers: list[GridNumber]
    computation: str
    note: Optional[str] = None


class ReadinessAssumptions(BaseModel):
    nameplate_mw: float
    h_constant_s: float
    power_factor: float
    h_typical_range_s: list[float]
    h_reference: str
    labels: dict[str, str] = Field(default_factory=dict)


class SeriesPt(BaseModel):
    row_index: int
    value: Optional[float]


class ReadinessCharts(BaseModel):
    tey: list[SeriesPt]
    tit: list[SeriesPt]
    nameplate_mw: float
    tit_p99_train: Optional[float]
    downsample_factor: int = 1


class ReadinessSummary(BaseModel):
    status: CardStatus
    headline: str
    bullets: list[str]


class GridReadiness(BaseModel):
    dataset_id: str
    year: int
    window: SampleRange
    rows: int
    training_years: list[int]
    assumptions: ReadinessAssumptions
    numbers: dict[str, GridNumber]
    cards: list[StatusCard]
    summary: ReadinessSummary
    charts: ReadinessCharts
    method_notes: list[str]
    disclaimer: str = READINESS_DISCLAIMER
    computed_at_utc: str
    time_axis_type: str = "ordered_hourly_sample_without_actual_timestamp"


# ---------------------------------------------------------------------------
# Drill
# ---------------------------------------------------------------------------


class DrillRequest(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    dataset_id: str = Field(..., max_length=128)
    year: int = Field(2014, ge=2000, le=2100)
    start: int = Field(1200, ge=0, le=100_000)
    end: int = Field(1320, ge=0, le=100_000)
    event: GridEvent = "load_step"
    use_meta: bool = False
    seed: int = Field(42, ge=0, le=2**31 - 1)
    nameplate_mw: float = Field(160.0, gt=0, le=2000)
    h_constant_s: float = Field(5.0, gt=0, le=20)
    power_factor: float = Field(0.85, gt=0.5, le=1.0)


class CoMovement(BaseModel):
    measure: str
    unit: str
    pre_mean: float
    step_mean_original: float
    step_mean_overlay: float
    delta_overlay_vs_original: float
    train_slope_per_mwh: float
    train_r: float
    computation: str


class DrillEvidence(BaseModel):
    scenario_id: str = "S05_GRID_EVENT"
    synthetic: bool = True
    scenario_label: Literal["synthetic_overlay"] = "synthetic_overlay"
    event: GridEvent
    event_note: str
    window: SampleRange
    step_rows: list[int]  # [lo, hi) window-relative rows of the synthetic step
    step_samples: SampleRange  # same rows as absolute sample indices
    tey_pre_mean: float
    tey_step_mean_original: float
    tey_step_mean_overlay: float
    tey_step_delta: float
    tey_step_delta_pct: float
    tey_computation: str
    co_movement: list[CoMovement]
    data_quality: dict[str, Any]
    capability: dict[str, GridNumber]
    transformations: list[Transformation]
    provenance: dict[str, str]


class GridBrief(BaseModel):
    headline: str = Field(min_length=8, max_length=300)
    what_the_data_shows: list[str] = Field(min_length=1, max_length=10)
    operator_verifications: list[str] = Field(min_length=1, max_length=12)
    plant_capability: list[str] = Field(min_length=1, max_length=8)
    notify: list[str] = Field(min_length=1, max_length=8)
    risks: list[str] = Field(min_length=1, max_length=8)
    disclaimer: str = BRIEF_DISCLAIMER

    @field_validator("what_the_data_shows", "operator_verifications", "plant_capability", "notify", "risks")
    @classmethod
    def _non_empty_items(cls, v: list[str]) -> list[str]:
        cleaned = [str(s).strip() for s in v]
        if any(not s for s in cleaned):
            raise ValueError("list items must be non-empty strings")
        return cleaned


class DrillEvent(BaseModel):
    seq: int
    kind: Literal["overlay_applied", "evidence_computed", "model_request", "model_response", "validation",
                  "rewrite_requested", "brief_accepted", "fallback", "error"]
    summary: str
    ok: bool = True
    latency_ms: Optional[int] = None
    tokens: Optional[dict[str, int]] = None


class SeriesPair(BaseModel):
    measure: str
    unit: str
    original: list[SeriesPt]
    overlay: list[SeriesPt]


class GridDrill(BaseModel):
    drill_id: str
    created_at_utc: str
    request: DrillRequest
    banner: str = DRILL_BANNER
    synthetic: bool = True
    mode: Literal["meta_live", "offline_preview", "offline_fallback"]
    meta_used: bool
    meta_model: Optional[str] = None
    brief: GridBrief
    brief_source: Literal["meta", "deterministic_offline"]
    evidence: DrillEvidence
    series: list[SeriesPair]
    validation_errors: list[str] = Field(default_factory=list)
    events: list[DrillEvent] = Field(default_factory=list)
    report_status: Literal["draft_requires_human_review"] = "draft_requires_human_review"


# ---------------------------------------------------------------------------
# Contingency options (simulated topology)
# ---------------------------------------------------------------------------


class ContingencyAssumptions(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    nameplate_mw: float = Field(160.0, gt=0, le=2000)
    power_factor: float = Field(0.85, gt=0.5, le=1.0)
    min_stable_mw: Optional[float] = Field(None, ge=0, le=5000, description="default 50% of nameplate (ASSUMPTION)")
    transformer_mva: float = Field(200.0, gt=0, le=5000)
    line_a_rating_mw: float = Field(120.0, ge=0, le=5000)
    line_b_rating_mw: float = Field(80.0, ge=0, le=5000)
    share_to_a: float = Field(0.6, ge=0, le=1, description="fraction of unit output flowing on line A")
    ss_a_spare_mw: float = Field(40.0, ge=0, le=5000)
    ss_b_spare_mw: float = Field(25.0, ge=0, le=5000)
    second_unit_available_mw: float = Field(0.0, ge=0, le=5000)
    tso_redispatch_assumed_mw: Optional[float] = Field(
        None, ge=0, le=5000, description="None = assume the TSO could cover the full request (their decision)")
    severity_pct: float = Field(25.0, ge=0, le=100, description="rating/capability reduction for the constraint")


class ContingencyRequest(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    dataset_id: str = Field(..., max_length=128)
    year: int = Field(2014, ge=2000, le=2100)
    start: int = Field(1200, ge=0, le=100_000)
    end: int = Field(1320, ge=0, le=100_000)
    shortfall_mw: Optional[float] = Field(None, ge=0, le=5000)
    constraint: Optional[ContingencyConstraint] = None
    assumptions: ContingencyAssumptions = Field(default_factory=ContingencyAssumptions)


class ContingencyOption(BaseModel):
    option_id: Literal["unit_partial_derate", "second_unit_shift", "tso_redispatch", "substation_spare"]
    rank: int
    title: str
    description: str
    applicable: bool
    covered_mw: float
    residual_shortfall_mw: float
    external_dependency: Literal["plant_internal", "site", "network_operator", "tso_external"]
    prerequisites: list[str]
    who_to_notify: list[str]
    computation: str
    provenance: GridProvenance = "simulated"


class TopologyNode(BaseModel):
    node_id: str
    label: str
    kind: Literal["unit", "transformer", "bus", "substation", "second_unit", "line"]
    capacity: Optional[float] = None
    unit: Optional[str] = None
    flow_mw: Optional[float] = None
    note: Optional[str] = None


class ContingencyResult(BaseModel):
    dataset_id: str
    year: int
    window: SampleRange
    simulated: bool = True
    constraint: Optional[ContingencyConstraint]
    shortfall_mw: float
    shortfall_source: Literal["user_input", "derived_from_constraint"]
    shortfall_semantics: str
    shortfall_computation: str
    output_proxy_mwh: float
    output_proxy_computation: str
    tit_margin_c: Optional[float]
    assumptions: ContingencyAssumptions
    assumption_labels: dict[str, str]
    topology: list[TopologyNode]
    options: list[ContingencyOption]
    status: Literal["no_shortfall", "covered", "partially_covered", "not_covered"]
    headline: str
    disclaimer: str = CONTINGENCY_DISCLAIMER
    computed_at_utc: str
