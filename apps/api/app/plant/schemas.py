"""Pydantic types for the plant-ops layer (personas, work requests, what-if, precedents).

Additive and self-contained: nothing in ``app.schemas`` is changed. Mirrored by
``apps/web/src/plant/types.ts``.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from app.schemas import AgentEvent

DELIVERY_NOTE = "Simulated in-app notification — no email/SMS/paging integration."
WHATIF_LABEL = ("Modelled sensitivity from this plant's historical data — not physics, not a control "
                "recommendation; review with site procedures.")
WHATIF_DISCLAIMER = ("Read-only decision support. Modelled sensitivity (production baseline model, ceteris "
                     "paribus) and statistical association in this plant's historical data (2011–2013), not "
                     "causation and not physics. Not a control recommendation; review with site procedures.")
ASSOCIATION_LABEL = "statistical association in this plant's historical data, not causation, not physics"

WorkRequestStatus = Literal["open", "acknowledged", "done", "dismissed"]
Confidence = Literal["low", "medium", "high"]
Direction = Literal["increase", "decrease", "no_clear_change", "mixed", "unknown"]


# ----------------------------------------------------------------------------- personas
class Persona(BaseModel):
    persona_id: str
    name: str
    role: str
    subsystems: list[str]
    description: str
    demo_account: bool = True  # fake demo account, no authentication


class PersonasResponse(BaseModel):
    personas: list[Persona]
    default_persona: str
    routing_table: dict[str, str]  # hypothesis_key -> persona_id
    urgent_also_notify: list[str]
    delivery_note: str = DELIVERY_NOTE
    auth_note: str = "Demo personas only; no authentication. Selected via X-Persona header or ?persona=."


# ----------------------------------------------------------------------------- work requests
class WorkRequestComment(BaseModel):
    ts_utc: str
    persona: str
    status: WorkRequestStatus
    comment: Optional[str] = None


class WorkRequest(BaseModel):
    id: str
    case_id: str
    assigned_persona: str
    title: str
    status: WorkRequestStatus = "open"
    created_at_utc: str
    updated_at_utc: str
    checks: list[str] = Field(default_factory=list)  # report.engineer_review_checks
    routed_by: str  # "rule:<hypothesis_key>"
    hypothesis_key: str
    severity: str
    scenario_id: str
    scenario_label: str
    synthetic: bool
    investigation_status: str
    history: list[WorkRequestComment] = Field(default_factory=list)
    delivery: str = "in_app_simulated"
    delivery_note: str = DELIVERY_NOTE


class Notification(BaseModel):
    id: str
    persona: str
    kind: Literal["work_request", "info"]
    message: str
    read: bool = False
    created_at_utc: str
    delivery: Literal["in_app_simulated"] = "in_app_simulated"
    case_id: Optional[str] = None
    work_request_id: Optional[str] = None


class InboxResponse(BaseModel):
    persona: Persona
    notifications: list[Notification]
    work_requests: list[WorkRequest]
    unread_count: int
    open_count: int
    delivery_note: str = DELIVERY_NOTE


class StatusUpdateRequest(BaseModel):
    status: WorkRequestStatus
    comment: Optional[str] = None


# ----------------------------------------------------------------------------- subsystems
class Subsystem(BaseModel):
    key: str
    name: str
    measurements: list[str]
    description: str
    owner_persona: str


# ----------------------------------------------------------------------------- what-if
class WhatIfRequest(BaseModel):
    case_id: Optional[str] = None
    question: str = ""
    measurement: str
    delta: float
    persona: Optional[str] = None


class ChangeSpec(BaseModel):
    measurement: str
    delta: float
    unit: str
    within_training_range: bool


class SubsystemAssessment(BaseModel):
    subsystem: str
    impact_summary: str
    direction: Direction = "unknown"
    magnitude_hint: str = ""
    confidence: Confidence = "low"
    caveats: list[str] = Field(default_factory=list)
    tool_numbers_cited: list[str] = Field(default_factory=list)


class CrossImpact(BaseModel):
    subsystems: list[str] = Field(default_factory=list)
    description: str
    basis: str = ""  # e.g. "model sensitivity", "historical association", "generic background"


class WhatIfAnswer(BaseModel):
    question: str
    change: ChangeSpec
    subsystem_assessments: list[SubsystemAssessment]
    cross_impacts: list[CrossImpact] = Field(default_factory=list)
    what_to_check_before_acting: list[str] = Field(default_factory=list)
    disclaimer: str = WHATIF_DISCLAIMER


class AgentRun(BaseModel):
    agent: str  # subsystem key or "aggregator"
    ok: bool
    used_tools: bool
    latency_ms: int
    tokens: dict[str, int] = Field(default_factory=dict)
    events: list[AgentEvent] = Field(default_factory=list)
    error: Optional[str] = None
    assessment: Optional[SubsystemAssessment] = None  # this agent's own validated output


class WhatIfSession(BaseModel):
    session_id: str
    created_at_utc: str
    completed_at_utc: Optional[str] = None
    status: Literal["running", "completed", "needs_review", "failed"]
    persona: str
    request: WhatIfRequest
    mode: Literal["meta_live", "offline"]  # "offline" = deterministic sensitivity only (no Meta call)
    mode_label: str
    meta_used: bool
    meta_model: Optional[str] = None
    base_window: dict[str, Any]  # {source_year,start,end,dataset_id,case_id,basis}
    sensitivity: dict[str, Any] = Field(default_factory=dict)  # deterministic simulate_change output
    answer: Optional[WhatIfAnswer] = None
    agents: list[AgentRun] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
    wall_ms: Optional[int] = None
    label: str = WHATIF_LABEL
    error: Optional[str] = None


# ----------------------------------------------------------------------------- precedents
class Precedent(BaseModel):
    case_id: str
    scenario_id: str
    scenario_label: str
    synthetic: bool
    rank1_hypothesis: Optional[str]
    decision: str
    reviewer: str
    comment: Optional[str] = None
    reviewed_at_utc: str
    similarity: float  # cosine similarity of evidence z-score signatures


class PrecedentsResponse(BaseModel):
    case_id: Optional[str]
    signature_ids: list[str]
    precedents: list[Precedent]
    reviewed_cases_considered: int
    note: str = ("Precedents are reviewed human decisions on similar evidence patterns (cosine similarity of "
                 "z-score signatures), not ground truth and not verified fault labels.")
