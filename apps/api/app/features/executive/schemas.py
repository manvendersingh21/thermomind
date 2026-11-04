"""Pydantic models for the executive view (feature-local; not part of the shared contract)."""
from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

Provenance = Literal["real", "model_derived", "simulated", "assumption", "prototype_metric"]
KpiGroup = Literal["performance", "reliability", "compliance", "grid", "people_knowledge", "decisions", "safety"]
Severity = Literal["attention", "info"]

GROUP_TITLES: dict[str, str] = {
    "performance": "Performance",
    "reliability": "Reliability",
    "compliance": "Compliance",
    "grid": "Grid",
    "people_knowledge": "People & knowledge",
    "decisions": "Decisions",
    "safety": "Safety & OT security",
}

FOOTER = ("All figures are prototype metrics from public data and simulated subsystems; "
          "no financial outcomes are claimed.")
BRIEF_DISCLAIMER = ("AI-drafted executive brief from prototype metrics on public data; not financial advice; "
                    "no savings claimed")
BRIEF_STATUS = "DRAFT — requires human review"
OFFLINE_LABEL = "OFFLINE FALLBACK — deterministic summary of the overview, not a Meta inference"


class Kpi(BaseModel):
    key: str
    group: KpiGroup
    label: str
    value: Optional[Union[float, int, str]] = None
    unit: str = ""
    provenance: Provenance
    source_endpoint: str
    caveat: str
    available: bool = True
    detail: dict = Field(default_factory=dict)


class AttentionItem(BaseModel):
    id: str
    severity: Severity
    title: str
    detail: str
    persona: str
    persona_name: str
    link: str
    rule: str
    kpi_keys: list[str] = Field(default_factory=list)
    case_ids: list[str] = Field(default_factory=list)


class OpenCase(BaseModel):
    case_id: str
    scenario_id: str
    synthetic: bool
    status: str
    severity: Optional[str] = None


class ExecutiveOverview(BaseModel):
    dataset_id: str
    year: int
    computed_at_utc: str
    attention: list[AttentionItem]
    kpis: list[Kpi]
    groups: dict[str, str] = Field(default_factory=lambda: dict(GROUP_TITLES))
    open_cases: list[OpenCase] = Field(default_factory=list)
    sources_unavailable: list[str] = Field(default_factory=list)
    method_notes: list[str] = Field(default_factory=list)
    footer: str = FOOTER
    read_only: Literal[True] = True


# ----------------------------------------------------------------------------- brief
class BriefRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    year: int = Field(2014, ge=2000, le=2100)
    dataset_id: str = Field("ds_uci_551", min_length=1, max_length=128)


class DecisionNeeded(BaseModel):
    decision: str = Field(..., min_length=1, max_length=600)
    owner_persona: Optional[str] = Field(None, max_length=64)
    why: str = Field("", max_length=600)


class BriefDraft(BaseModel):
    headline: str = Field(..., min_length=1, max_length=400)
    situation: str = Field(..., min_length=1, max_length=2000)
    risks: list[str] = Field(default_factory=list, max_length=12)
    decisions_needed: list[DecisionNeeded] = Field(default_factory=list, max_length=12)
    money_and_time_caveats: list[str] = Field(default_factory=list, max_length=12)
    next_30_days: list[str] = Field(default_factory=list, max_length=12)


class ExecutiveBrief(BaseModel):
    brief_id: str
    created_at_utc: str
    year: int
    dataset_id: str
    mode: Literal["meta_live", "offline_fallback"]
    meta_used: bool
    meta_model: Optional[str] = None
    meta_calls: int = 0
    source_label: str
    status: str = BRIEF_STATUS
    rewrite_used: bool = False
    fallback_reason: Optional[str] = None
    validation_errors: list[str] = Field(default_factory=list)
    brief: BriefDraft
    disclaimer: str = BRIEF_DISCLAIMER
    overview_numbers_checked: int = 0
    latency_ms: Optional[int] = None
    tokens: dict[str, int] = Field(default_factory=dict)
    brief_hash: str = ""
