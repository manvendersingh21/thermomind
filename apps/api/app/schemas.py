"""
ThermoMind shared schemas — THE CONTRACT.

Every module (data, analytics, agent, api, web) builds against these types.
Do not rename fields without updating contracts/api.md and apps/web/src/api/types.ts.

Provenance vocabulary (used everywhere, incl. UI badges):
  provenance_kind: "real_observation" | "model_derived" | "synthetic_overlay" | "measured_plus_synthetic_overlay"
  scenario_label:  "real_only" | "synthetic_overlay"
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Dataset / measurements
# ---------------------------------------------------------------------------

MEASUREMENTS: dict[str, dict[str, str]] = {
    "AT": {"name": "Ambient temperature", "unit": "°C"},
    "AP": {"name": "Ambient pressure", "unit": "mbar"},
    "AH": {"name": "Ambient humidity", "unit": "%"},
    "AFDP": {"name": "Air filter differential pressure", "unit": "mbar"},
    "GTEP": {"name": "Gas turbine exhaust pressure", "unit": "mbar"},
    "TIT": {"name": "Turbine inlet temperature", "unit": "°C"},
    "TAT": {"name": "Turbine after temperature", "unit": "°C"},
    "TEY": {"name": "Turbine energy yield", "unit": "MWh"},
    "CDP": {"name": "Compressor discharge pressure", "unit": "mbar (as published; unit under validation)"},
    "CO": {"name": "Carbon monoxide", "unit": "mg/m³"},
    "NOX": {"name": "Nitrogen oxides", "unit": "mg/m³"},
}
MEASUREMENT_KEYS = list(MEASUREMENTS.keys())
FEATURE_KEYS = ["AT", "AP", "AH", "AFDP", "GTEP", "TIT", "TAT", "CDP"]  # model inputs
TARGET_KEY = "TEY"

UCI_SOURCE_ID = "UCI_GAS_TURBINE_551"
UCI_LICENSE = "CC-BY-4.0"
UCI_DOI = "10.24432/C5WC95"
UCI_URL = "https://archive.ics.uci.edu/dataset/551/gas+turbine+co+and+nox+emission+data+set"
UCI_CITATION = (
    "Kaya, H., Tüfekci, P. & Gürgen, F. (2019). Gas Turbine CO and NOx Emission Data Set. "
    "UCI Machine Learning Repository. https://doi.org/10.24432/C5WC95"
)

ProvenanceKind = Literal[
    "real_observation", "model_derived", "synthetic_overlay", "measured_plus_synthetic_overlay"
]
ScenarioLabel = Literal["real_only", "synthetic_overlay"]


class MeasurementInfo(BaseModel):
    key: str
    name: str
    unit: str
    count: int
    missing: int
    min: float | None = None
    max: float | None = None
    mean: float | None = None
    median: float | None = None


class SourceFileInfo(BaseModel):
    filename: str
    source_year: int | None
    rows: int
    sha256: str
    bytes: int


class DatasetSummary(BaseModel):
    dataset_id: str
    source: str  # e.g. UCI_GAS_TURBINE_551 or USER_UPLOAD
    source_license: str | None = None
    source_url: str | None = None
    citation: str | None = None
    plant: str | None = None  # "undisclosed Turkish gas-turbine plant"
    row_count: int
    years: list[int]
    columns: list[str]
    has_timestamps: bool = False
    time_axis_type: str = "ordered_hourly_sample_without_actual_timestamp"
    created_at_utc: str
    warnings: list[str] = Field(default_factory=list)


class DatasetDetail(DatasetSummary):
    source_files: list[SourceFileInfo]
    measurements: list[MeasurementInfo]
    rows_per_year: dict[str, int]
    provenance_notes: list[str] = Field(default_factory=list)


class UploadResult(BaseModel):
    dataset_id: str
    rows: int
    columns: list[str]
    source: str
    sha256: str
    warnings: list[str] = Field(default_factory=list)


class SeriesPoint(BaseModel):
    row_index: int
    value: float | None
    expected: float | None = None  # only populated when include_expected (model-derived)


class SeriesResponse(BaseModel):
    dataset_id: str
    measure: str
    unit: str
    source_year: int
    start: int
    end: int  # exclusive
    total_rows_in_year: int
    downsample_factor: int = 1
    points: list[SeriesPoint]
    provenance_kind: ProvenanceKind = "real_observation"
    scenario_id: str | None = None
    synthetic: bool = False
    source: str = UCI_SOURCE_ID
    time_axis_type: str = "ordered_hourly_sample_without_actual_timestamp"


# ---------------------------------------------------------------------------
# Model / evaluation
# ---------------------------------------------------------------------------


class SplitInfo(BaseModel):
    train_years: list[int]
    validation_years: list[int]
    test_years: list[int]
    train_rows: int
    validation_rows: int
    test_rows: int
    method: str = "chronological_by_source_year"


class MetricSet(BaseModel):
    mae: float
    rmse: float
    r2: float
    n: int


class ModelEvaluation(BaseModel):
    model_id: str
    model_version: str
    algorithm: str
    features: list[str]
    target: str = TARGET_KEY
    target_unit: str = "MWh"
    seed: int
    split: SplitInfo
    validation: MetricSet
    holdout: MetricSet  # untouched test year(s)
    naive_baselines: dict[str, MetricSet]  # e.g. {"train_mean": ..., "previous_observation": ...}
    residual_std_validation: float  # std of (observed-expected) on validation; used for thresholds
    residual_quantiles_validation: dict[str, float]  # {"p01":..,"p05":..,"p50":..,"p95":..,"p99":..}
    feature_ranges_train: dict[str, list[float]]  # {"AT":[min,max],...} for OOD flags
    trained_at_utc: str
    notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


class Transformation(BaseModel):
    measurement: str
    operation: str  # "add_ramp", "multiply_ramp", "add_offset", "spike", "none"
    params: dict[str, Any]
    description: str


class ScenarioInfo(BaseModel):
    scenario_id: str  # S01_NORMAL, S02_INTAKE_RESTRICTION, S03_SENSOR_INCONSISTENCY, S04_AMBIENT_SHIFT
    title: str
    synthetic: bool
    description: str
    rationale: str
    affected_measurements: list[str]
    default_year: int = 2014
    default_start: int = 1200
    default_end: int = 1320  # exclusive
    default_seed: int = 42
    expected_behavior: str  # what a good investigator should conclude (NOT passed to the agent)


class ScenarioPreviewRequest(BaseModel):
    dataset_id: str
    scenario_id: str
    year: int = 2014
    start_index: int = 1200
    end_index: int = 1320
    measurements: list[str] = Field(default_factory=lambda: ["AFDP", "TEY", "CDP"])
    seed: int | None = None


class ScenarioSeries(BaseModel):
    measure: str
    unit: str
    original: list[SeriesPoint]  # real observations (never modified)
    overlay: list[SeriesPoint]  # after synthetic transform (== original for S01)
    expected: list[SeriesPoint] | None = None  # model-derived expected (for TEY)


class ScenarioPreviewResponse(BaseModel):
    dataset_id: str
    scenario_id: str
    synthetic: bool
    scenario_label: ScenarioLabel
    year: int
    start_index: int
    end_index: int
    seed: int
    transformations: list[Transformation]
    series: list[ScenarioSeries]
    provenance: dict[str, Any]


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


class SampleRange(BaseModel):
    source_year: int
    start: int
    end: int  # exclusive


class Evidence(BaseModel):
    evidence_id: str  # ev_<slug>_<nn>, stable per case
    case_id: str
    kind: ProvenanceKind
    metric: str  # measurement key or derived key, e.g. "TEY_residual"
    unit: str
    title: str
    sample_range: SampleRange
    reference_range: SampleRange | None = None
    observed_stat: float | None
    comparison_stat: float | None
    delta: float | None = None
    delta_pct: float | None = None
    z_score: float | None = None
    method: str  # e.g. "median_window_vs_reference"
    computation: str  # human-readable formula with the actual numbers
    data_quality: Literal["pass", "warn", "fail"] = "pass"
    is_synthetic: bool = False
    model_version: str | None = None
    flags: list[str] = Field(default_factory=list)  # e.g. ["out_of_training_range", "isolated_single_sensor"]
    values: dict[str, Any] = Field(default_factory=dict)  # extra numbers used in computation


class DataQualityReport(BaseModel):
    case_id: str
    missing_values: dict[str, int]
    out_of_training_range: dict[str, int]  # measurement -> count of rows outside train range
    sensor_consistency_flags: list[str]
    scenario_label: ScenarioLabel
    synthetic_measurements: list[str]
    source: str
    notes: list[str] = Field(default_factory=list)


class BaselineComparison(BaseModel):
    case_id: str
    model_version: str
    window: SampleRange
    reference: SampleRange
    observed_tey_mean: float
    expected_tey_mean: float
    residual_mean: float
    residual_std_window: float
    residual_std_validation: float
    residual_z: float  # residual_mean / residual_std_validation
    reference_residual_mean: float
    unit: str = "MWh"
    holdout_mae: float
    holdout_r2: float
    caveats: list[str]


class HypothesisEvaluation(BaseModel):
    case_id: str
    hypothesis_key: str  # intake_restriction | operating_condition | sensor_issue | unknown
    supporting_evidence_ids: list[str]
    contradicting_evidence_ids: list[str]
    deterministic_notes: list[str]
    deterministic_support_score: float  # 0..1, heuristic, labelled as such


# ---------------------------------------------------------------------------
# Investigation / agent
# ---------------------------------------------------------------------------

HYPOTHESIS_KEYS = ["intake_restriction", "operating_condition", "sensor_issue", "unknown"]


class InvestigationRequest(BaseModel):
    dataset_id: str
    scenario_id: str = "S01_NORMAL"
    year: int = 2014
    start_index: int = 1200
    end_index: int = 1320
    seed: int | None = None
    use_meta: bool = True  # False => offline deterministic preview, clearly labelled


class Observation(BaseModel):
    statement: str
    evidence_ids: list[str]


class Hypothesis(BaseModel):
    name: str
    key: str | None = None  # one of HYPOTHESIS_KEYS when applicable
    rank: int
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    status: Literal["possible", "inconclusive", "not_supported"]
    rationale: str | None = None
    what_would_change_assessment: str | None = None


class DiagnosticReport(BaseModel):
    case_id: str
    title: str
    summary: str
    severity: Literal["informational", "review", "urgent_review"]
    data_source: str = UCI_SOURCE_ID
    scenario_label: ScenarioLabel
    observations: list[Observation]
    hypotheses: list[Hypothesis]
    additional_data_needed: list[str]
    engineer_review_checks: list[str]
    limitations: list[str]
    disclaimer: str = "Not a validated plant safety or control system."
    report_status: Literal["draft_requires_human_review"] = "draft_requires_human_review"


class AgentEvent(BaseModel):
    seq: int
    ts_utc: str
    kind: Literal[
        "case_opened", "model_request", "model_response", "tool_call", "tool_result",
        "validation", "rewrite_requested", "report_accepted", "error", "fallback",
    ]
    tool_name: str | None = None
    args: dict[str, Any] | None = None  # validated args only
    summary: str  # short, redacted, UI-safe
    evidence_ids: list[str] = Field(default_factory=list)
    latency_ms: int | None = None
    ok: bool = True
    tokens: dict[str, int] | None = None


InvestigationStatus = Literal["queued", "running", "completed", "needs_review", "failed"]
ReviewDecision = Literal["accepted", "rejected", "more_data_requested"]


class ReviewRecord(BaseModel):
    decision: ReviewDecision
    reviewer: str = "demo-engineer"
    comment: str | None = None
    ts_utc: str


class ReviewRequest(BaseModel):
    decision: ReviewDecision
    reviewer: str = "demo-engineer"
    comment: str | None = None


class Investigation(BaseModel):
    case_id: str
    status: InvestigationStatus
    created_at_utc: str
    completed_at_utc: str | None = None
    request: InvestigationRequest
    scenario: ScenarioInfo
    scenario_label: ScenarioLabel
    window: SampleRange
    reference: SampleRange
    model_version: str | None
    meta_model: str | None  # actual model id used, None if offline
    meta_used: bool  # True only if a real Meta API call produced the report
    mode: Literal["meta_live", "offline_preview"]
    report: DiagnosticReport | None = None
    deterministic_summary: dict[str, Any] = Field(default_factory=dict)  # tool outputs for offline preview
    evidence: list[Evidence]
    data_quality: DataQualityReport | None = None
    baseline: BaselineComparison | None = None
    events: list[AgentEvent] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
    report_hash: str | None = None
    review: ReviewRecord | None = None
    error: str | None = None


class InvestigationCreated(BaseModel):
    case_id: str
    status: InvestigationStatus


# ---------------------------------------------------------------------------
# Health / demo status
# ---------------------------------------------------------------------------


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    build: str
    data_ready: bool
    model_ready: bool
    meta_configured: bool
    meta_model: str
    meta_base_url: str


class DemoStatus(BaseModel):
    data: dict[str, Any]
    model: dict[str, Any]
    meta: dict[str, Any]
    backend: dict[str, Any]
    scenarios: dict[str, Any]
    build: dict[str, Any]
    ready_for_demo: bool
    blockers: list[str]
