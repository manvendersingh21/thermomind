"""Pydantic models for "Propose an action" (advisory multi-agent deliberation).

Read-only decision support: a deliberation is a discussion between software agents about a change an operator is
considering. The human decides; ThermoMind executes nothing and writes to no plant system.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from app.schemas import AgentEvent

BANNER = "Advisory deliberation between software agents — the human decides; ThermoMind executes nothing"
DISCLAIMER = "Advisory deliberation; the human decides; this software executes nothing"
SLOPE_LABEL = ("statistical association: least-squares slope over the 2011–2013 training years of this plant's "
               "data — not causation, not physics")
FALLBACK_LABEL = "deterministic fallback from the pre-checks (no model reasoning)"
OFFLINE_LABEL = "offline (no Meta call): deterministic pre-checks only"
LIVE_LABEL = "meta_live (Muse Spark subsystem agents + constraints agent + aggregator over deterministic pre-checks)"

Verdict = Literal["support", "oppose", "neutral", "insufficient_evidence"]
Confidence = Literal["low", "medium", "high"]
Recommendation = Literal["proceed_with_conditions", "do_not_proceed", "insufficient_evidence"]
Provenance = Literal["real_observation", "model_derived", "statistical_association", "derived_from_history",
                     "simulated", "assumption", "operator_intent", "not_observable"]
FindingStatus = Literal["ok", "info", "watch", "concern", "exceeds", "unavailable"]
Decision = Literal["approve_plan", "reject", "defer"]
SessionStatus = Literal["running", "completed", "needs_review", "failed"]


# ----------------------------------------------------------------------------- intents
class MagnitudeSpec(BaseModel):
    unit: str
    default: float
    min: float
    max: float
    step: float
    label: str


class IntentInfo(BaseModel):
    intent_id: str
    label: str
    description: str
    magnitude: Optional[MagnitudeSpec] = None
    subsystems: list[str] = Field(default_factory=list)
    primary_measurement: Optional[str] = None
    observable: bool = True
    notes: list[str] = Field(default_factory=list)


class MeasurementDelta(BaseModel):
    measurement: str
    delta: float
    unit: str
    role: Literal["primary", "implied"]
    basis: str
    provenance: Provenance
    slope: Optional[float] = None
    pearson_r: Optional[float] = None
    slope_of: Optional[str] = None  # implied delta = slope(measurement | slope_of) x delta(slope_of)


class ModelledChange(BaseModel):
    intent_id: str
    label: str
    text: str
    magnitude: Optional[float] = None
    unit: Optional[str] = None
    deltas: list[MeasurementDelta] = Field(default_factory=list)
    subsystems: list[str] = Field(default_factory=list)
    observable: bool = True
    qualitative_notes: list[str] = Field(default_factory=list)
    slope_label: str = SLOPE_LABEL
    training_years: list[int] = Field(default_factory=list)


class CustomIntent(BaseModel):
    text: str = Field(min_length=3, max_length=500)
    deltas: dict[str, float] = Field(default_factory=dict)


class ProposeRequest(BaseModel):
    case_id: Optional[str] = None
    dataset_id: str = "ds_uci_551"
    year: Optional[int] = None
    start: Optional[int] = Field(default=None, ge=0)
    end: Optional[int] = Field(default=None, ge=1)
    intent_id: Optional[str] = None
    custom: Optional[CustomIntent] = None
    magnitude: Optional[float] = None
    persona: Optional[str] = None


# ----------------------------------------------------------------------------- pre-checks
class ConstraintFinding(BaseModel):
    n: int
    key: str
    title: str
    status: FindingStatus
    detail: str
    provenance: Provenance
    source: str  # module / function that produced the numbers
    numbers: dict[str, Any] = Field(default_factory=dict)


# ----------------------------------------------------------------------------- agents
class AgentVerdict(BaseModel):
    subsystem: str
    verdict: Verdict
    confidence: Confidence
    reasons: list[str] = Field(default_factory=list)
    harms: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    tool_numbers_cited: list[str] = Field(default_factory=list)
    owner_persona: Optional[str] = None
    fallback: bool = False  # True = deterministic stand-in (no model reasoning)


class DelibAgentRun(BaseModel):
    agent: str
    role: Literal["subsystem", "constraints", "aggregator"]
    name: str = ""
    status: Literal["pending", "running", "done", "failed"] = "pending"
    ok: bool = False
    used_tools: bool = False
    latency_ms: int = 0
    tokens: dict[str, int] = Field(default_factory=dict)
    events: list[AgentEvent] = Field(default_factory=list)
    error: Optional[str] = None
    verdict: Optional[AgentVerdict] = None


class Consensus(BaseModel):
    support: int = 0
    oppose: int = 0
    neutral: int = 0
    insufficient: int = 0


class Dissent(BaseModel):
    subsystem: str
    why: str


class Outcome(BaseModel):
    recommendation: Recommendation
    summary: str = ""
    consensus: Consensus
    dissent: list[Dissent] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    what_could_go_wrong: list[str] = Field(default_factory=list)  # domino chain, in order
    rehearsal_suggestion: str = ""
    who_must_approve: list[str] = Field(default_factory=list)  # persona ids
    disclaimer: str = DISCLAIMER
    source: Literal["model", "deterministic_fallback"] = "model"
    source_label: str = ""
    guard_notes: list[str] = Field(default_factory=list)


class Rehearsal(BaseModel):
    status: Literal["available", "unavailable"]
    reason: str = ""
    steps: int = 0
    outcome_summary: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class HumanDecision(BaseModel):
    decision: Decision
    persona: str
    persona_label: str = ""
    comment: Optional[str] = None
    recorded_at_utc: str
    routed_to: str
    routed_to_label: str = ""
    notification_id: Optional[str] = None
    work_request_id: Optional[str] = None
    routing_note: str = ""
    executed: Literal[False] = False
    message: str = ""


class DecisionRequest(BaseModel):
    decision: Decision
    persona: Optional[str] = None
    comment: Optional[str] = Field(default=None, max_length=2000)


class DeliberationSession(BaseModel):
    deliberation_id: str
    created_at_utc: str
    completed_at_utc: Optional[str] = None
    status: SessionStatus
    persona: str
    request: ProposeRequest
    case_id: Optional[str] = None
    base_window: dict[str, Any] = Field(default_factory=dict)
    change: ModelledChange
    constraint_findings: list[ConstraintFinding] = Field(default_factory=list)
    agents: list[DelibAgentRun] = Field(default_factory=list)
    outcome: Optional[Outcome] = None
    rehearsal: Optional[Rehearsal] = None
    decisions: list[HumanDecision] = Field(default_factory=list)
    mode: Literal["meta_live", "offline"] = "offline"
    mode_label: str = OFFLINE_LABEL
    meta_model: Optional[str] = None
    validation_errors: list[str] = Field(default_factory=list)
    wall_ms: Optional[int] = None
    error: Optional[str] = None
    banner: str = BANNER
    disclaimer: str = DISCLAIMER
