"""Pydantic models for the ops workflow features (handover draft, CMMS draft, metrics)."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

HANDOVER_STATUS = "DRAFT — requires shift supervisor sign-off"
CMMS_STATUS = "DRAFT — not submitted"
CMMS_SYSTEM = "ThermoMind prototype — no CMMS integration"
CMMS_ASSET = "GT-1 (UCI dataset 551, undisclosed Turkish plant)"
METRICS_NOTICE = "prototype metrics from this demo database, not pilot results"
OFFLINE_LABEL = "offline draft, no Meta call"


# ----------------------------------------------------------------------------- handover
class HandoverRequest(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    hours: Literal[8, 12, 24] = 8
    persona: Optional[str] = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_\-\. ]{1,64}$")


class HandoverItem(BaseModel):
    case_id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=1200)


class WatchItem(BaseModel):
    case_id: Optional[str] = Field(default=None, max_length=64)  # None for plant-wide/system flags
    text: str = Field(min_length=1, max_length=1200)


class HandoverDraft(BaseModel):
    """Exactly what the model must return (validated before acceptance)."""
    headline: str = Field(min_length=1, max_length=600)
    open_items: list[HandoverItem] = Field(default_factory=list, max_length=60)
    watch_list: list[WatchItem] = Field(default_factory=list, max_length=60)
    completed: list[HandoverItem] = Field(default_factory=list, max_length=60)
    caveats: list[str] = Field(default_factory=list, max_length=30)


class HandoverCaseRef(BaseModel):
    case_id: str
    created_at_utc: str
    status: str
    mode: str
    scenario_id: str
    scenario_title: str
    scenario_label: str
    synthetic: bool
    window: str
    severity: Optional[str] = None
    rank1_hypothesis: Optional[str] = None
    rank1_status: Optional[str] = None
    report_title: Optional[str] = None
    review_decision: Optional[str] = None
    reviewer: Optional[str] = None


class HandoverNote(BaseModel):
    note_id: str
    created_at_utc: str
    hours: int
    persona: Optional[str] = None
    window_start_utc: str
    window_end_utc: str
    status: str = HANDOVER_STATUS
    mode: Literal["meta_live", "offline_fallback"]
    meta_used: bool  # True only when the accepted text came from Muse Spark
    meta_model: Optional[str] = None
    meta_calls: int = 0
    source_label: str  # e.g. "Meta Muse Spark draft (muse-spark-1.3)" or OFFLINE_LABEL
    rewrite_used: bool = False
    fallback_reason: Optional[str] = None
    validation_errors: list[str] = Field(default_factory=list)  # errors seen before acceptance/fallback
    draft: HandoverDraft
    cases: list[HandoverCaseRef] = Field(default_factory=list)
    work_requests_included: int = 0
    work_requests_available: bool = False
    health_flags: dict[str, Any] = Field(default_factory=dict)
    latency_ms: Optional[int] = None
    tokens: dict[str, int] = Field(default_factory=dict)
    note_hash: str = ""
    human_review: str = "Shift supervisor must review and sign off; sign-off in the UI is local only."


class HandoverNoteSummary(BaseModel):
    note_id: str
    created_at_utc: str
    hours: int
    persona: Optional[str] = None
    mode: str
    meta_used: bool
    source_label: str
    headline: str
    case_count: int
    note_hash: str


# ----------------------------------------------------------------------------- metrics
class MedianStat(BaseModel):
    median: Optional[float] = None
    n: int = 0
    unit: str = ""


class RateStat(BaseModel):
    rate: Optional[float] = None  # 0..1; None when n == 0
    numerator: int = 0
    n: int = 0


class OpsMetrics(BaseModel):
    notice: str = METRICS_NOTICE
    generated_at_utc: str
    cases_total: int
    by_mode: dict[str, int]
    by_status: dict[str, int]
    by_scenario_label: dict[str, int]
    live_cases: int
    live_wall_time_s: MedianStat
    tool_calls_per_live_case: MedianStat
    validator_first_pass_acceptance: RateStat
    rewrite_rate: RateStat
    review_counts: dict[str, int]
    evidence_citations_per_report: MedianStat
    cited_ids_resolving: RateStat
    time_to_review_s: MedianStat
    definitions: dict[str, str]
