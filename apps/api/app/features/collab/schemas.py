"""Pydantic models for the collaboration layer (autonomy policy, activity feed, domino map, onboarding)."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

AutonomyLevel = Literal["agent_auto", "human_review", "human_only"]
DecisionKind = Literal["auto_triaged_no_action", "requires_human", "human_override_reopened"]

ONBOARDING_BADGE = "AI-drafted onboarding guide — verify with your supervisor"
ONBOARDING_DISCLAIMER = ("AI-drafted onboarding guide for a demo persona on a read-only decision-support prototype "
                         "(public UCI data, no timestamps, no fault labels). Verify everything with your supervisor; "
                         "it is not a procedure and gives no authority to operate plant equipment.")
DEPENDENCY_CAVEAT = ("Dashed links are statistical association in this plant's historical data (training years, "
                     "|r| ≥ 0.4), not causation and not physics; solid arrows are the generic gas-turbine flow order. "
                     "The domino path is a reading aid for who to talk to, not a prediction.")


# ----------------------------------------------------------------------------- autonomy policy
class PolicyAction(BaseModel):
    action_id: str
    action: str
    level: AutonomyLevel
    actor: str  # who performs it: "agent" or the persona(s)
    why: str
    reversible: bool
    link: Optional[str] = None  # SPA route where it happens


class DecisionCounts(BaseModel):
    auto_triaged_no_action: int = 0
    requires_human: int = 0
    human_override_reopened: int = 0
    total: int = 0


class PolicyResponse(BaseModel):
    policy_id: str
    title: str
    levels: dict[str, str]
    actions: list[PolicyAction]
    auto_triage_conditions: list[str]
    counts: DecisionCounts
    note: str


class PolicyCondition(BaseModel):
    name: str
    passed: bool
    detail: str


class AutoDecision(BaseModel):
    decision_id: str
    case_id: str
    decision: DecisionKind
    reason: str
    policy_id: str
    ts_utc: str
    reversible: bool = True
    actor: str = "agent:autonomy_policy"
    routed_personas: list[str] = Field(default_factory=list)
    conditions: list[PolicyCondition] = Field(default_factory=list)
    synthetic: bool = False
    severity: Optional[str] = None
    supersedes: Optional[str] = None  # decision_id this one overrides (human reopen)
    comment: Optional[str] = None


class DecisionsResponse(BaseModel):
    decisions: list[AutoDecision]
    counts: DecisionCounts


class ReopenRequest(BaseModel):
    persona: Optional[str] = Field(None, max_length=64)
    comment: Optional[str] = Field(None, max_length=2000)


class ApplyExistingResponse(BaseModel):
    applied: int
    already_decided: int
    decisions: list[AutoDecision]


# ----------------------------------------------------------------------------- activity feed
class ActivityItem(BaseModel):
    ts_utc: str
    actor: str
    actor_kind: Literal["agent", "persona", "human", "system"]
    kind: str
    summary: str
    link: Optional[str] = None


class ActivityResponse(BaseModel):
    case_id: str
    items: list[ActivityItem]
    sources: dict[str, bool]
    note: str = ("Read-only aggregation of existing records (investigation, validator events, work requests, "
                 "simulated in-app notifications, reviews, policy decisions, what-if sessions, handover notes). "
                 "One shared record for every team; nothing here changes plant state.")


# ----------------------------------------------------------------------------- dependency graph
class GraphNode(BaseModel):
    id: str
    kind: Literal["subsystem", "measurement"]
    label: str
    layer: int
    subsystem: Optional[str] = None
    unit: Optional[str] = None
    owner_persona: Optional[str] = None
    owner_label: Optional[str] = None
    description: Optional[str] = None
    how_it_works: Optional[str] = None
    what_to_check: list[str] = Field(default_factory=list)
    implicated: bool = False
    on_path: bool = False
    stat_neighbour: bool = False


class GraphEdge(BaseModel):
    source: str
    target: str
    kind: Literal["physical", "membership", "statistical"]
    r: Optional[float] = None
    slope: Optional[float] = None
    label: str = ""
    on_path: bool = False


class Implicated(BaseModel):
    subsystem: str
    measurement: str
    reason: str


class WhatIfAnnotation(BaseModel):
    measurement: str
    delta: float
    unit: str
    applicable: bool
    delta_tey_mean: Optional[float] = None
    delta_tey_min: Optional[float] = None
    delta_tey_max: Optional[float] = None
    ood_flag: Optional[bool] = None
    note: str = ""
    label: str = "MODEL-DERIVED sensitivity of the statistical baseline (ceteris paribus), not a physics simulation"


class DependencyGraph(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    implicated: Optional[Implicated] = None
    domino_path: list[str] = Field(default_factory=list)
    whatif: Optional[WhatIfAnnotation] = None
    caveat: str = DEPENDENCY_CAVEAT
    threshold: float
    training_years: list[int] = Field(default_factory=list)
    case_id: Optional[str] = None
    synthetic: Optional[bool] = None


# ----------------------------------------------------------------------------- onboarding
class PlantPart(BaseModel):
    subsystem: str
    explanation: str


class WatchItem(BaseModel):
    measurement: str
    why: str


class Colleague(BaseModel):
    persona: str
    when: str


class OnboardingBriefBody(BaseModel):
    role_summary: str = Field(..., min_length=1, max_length=2000)
    how_the_plant_works: list[PlantPart] = Field(default_factory=list, max_length=12)
    what_you_watch: list[WatchItem] = Field(default_factory=list, max_length=12)
    who_you_work_with: list[Colleague] = Field(default_factory=list, max_length=12)
    current_open_items: list[str] = Field(default_factory=list, max_length=30)
    first_week_checklist: list[str] = Field(default_factory=list, max_length=15)
    disclaimer: str = ONBOARDING_DISCLAIMER


class OnboardingRequest(BaseModel):
    persona: str = Field(..., min_length=1, max_length=64)


class OnboardingBrief(BaseModel):
    brief_id: str
    persona: str
    created_at_utc: str
    mode: Literal["meta_live", "offline_fallback"]
    meta_used: bool
    meta_model: Optional[str] = None
    meta_calls: int = 0
    rewrite_used: bool = False
    fallback_reason: Optional[str] = None
    validation_errors: list[str] = Field(default_factory=list)
    source_label: str
    badge: str = ONBOARDING_BADGE
    brief: OnboardingBriefBody
    latency_ms: Optional[int] = None
    tokens: dict[str, int] = Field(default_factory=dict)


class OnboardingLatest(BaseModel):
    persona: str
    brief: Optional[OnboardingBrief] = None
