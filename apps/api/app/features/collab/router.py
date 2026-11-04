"""FastAPI router for the collaboration layer (prefix ``/collab``; main.py mounts it under ``/api``).

GET  /collab/policy · GET /collab/decisions?case_id=&limit= · POST /collab/decisions/{id}/reopen
POST /collab/policy/apply-existing · GET /collab/cases/{case_id}/activity
GET  /collab/dependency-graph?case_id=&measurement=&delta= · POST /collab/onboarding · GET /collab/onboarding?persona=
Writes only the ``collab_decisions`` / ``onboarding_briefs`` tables (+ one simulated operator notification per
auto-triage). Never touches the plant, the investigations or their reports.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from app import services
from app.features.collab import activity, autonomy, db, dependencies, onboarding
from app.features.collab.schemas import (ActivityResponse, ApplyExistingResponse, AutoDecision, DecisionCounts,
                                         DecisionsResponse, DependencyGraph, OnboardingBrief, OnboardingLatest,
                                         OnboardingRequest, PolicyResponse, ReopenRequest)

router = APIRouter(prefix="/collab", tags=["collab"])
log = logging.getLogger("thermomind.collab.router")
_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


# ----------------------------------------------------------------------------- providers (patched in tests)
def get_investigation(case_id: str) -> Any:
    return services.get_store().get(case_id)  # KeyError -> 404


def get_investigations() -> list[Any]:
    return services.get_store().list()


def get_meta_client() -> Any:
    return onboarding.get_meta_client()


def _check_id(value: str, what: str) -> str:
    if not _ID_RE.match(value or ""):
        raise HTTPException(status_code=422, detail=f"invalid {what}")
    return value


def _not_found(exc: KeyError) -> HTTPException:
    msg = exc.args[0] if exc.args and isinstance(exc.args[0], str) else "not found"
    return HTTPException(status_code=404, detail=msg)


# ----------------------------------------------------------------------------- autonomy policy
@router.get("/policy", response_model=PolicyResponse)
def get_policy() -> PolicyResponse:
    return autonomy.policy_response()


@router.get("/decisions", response_model=DecisionsResponse)
def list_decisions(case_id: Optional[str] = Query(None, max_length=64),
                   limit: int = Query(50, ge=1, le=500)) -> DecisionsResponse:
    if case_id:
        _check_id(case_id, "case_id")
    return DecisionsResponse(decisions=db.list_decisions(case_id=case_id, limit=limit),
                             counts=DecisionCounts(**db.decision_counts()))


@router.post("/decisions/{decision_id}/reopen", response_model=AutoDecision)
def reopen_decision(decision_id: str, body: Optional[ReopenRequest] = None,
                    x_persona: Optional[str] = Header(None, max_length=64)) -> AutoDecision:
    _check_id(decision_id, "decision_id")
    body = body or ReopenRequest()
    try:
        return autonomy.reopen(decision_id, body.persona or x_persona, body.comment)
    except KeyError as exc:
        raise _not_found(exc) from None
    except autonomy.ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.post("/policy/apply-existing", response_model=ApplyExistingResponse)
def apply_existing() -> ApplyExistingResponse:
    """Apply P-01 to stored cases that have no decision yet (logging only; idempotent)."""
    decided = {d.case_id for d in db.list_decisions(limit=100000)}
    applied: list[AutoDecision] = []
    already = 0
    for inv in get_investigations():
        if inv.case_id in decided:
            already += 1
            continue
        d = autonomy.apply_autonomy_policy(inv)
        if d is not None:
            applied.append(d)
    return ApplyExistingResponse(applied=len(applied), already_decided=already, decisions=applied)


# ----------------------------------------------------------------------------- activity feed
@router.get("/cases/{case_id}/activity", response_model=ActivityResponse)
def case_activity(case_id: str) -> ActivityResponse:
    _check_id(case_id, "case_id")
    try:
        return activity.case_activity(case_id, get_investigation)
    except KeyError as exc:
        raise _not_found(exc) from None


# ----------------------------------------------------------------------------- domino map
@router.get("/dependency-graph", response_model=DependencyGraph)
def dependency_graph(case_id: Optional[str] = Query(None, max_length=64),
                     measurement: Optional[str] = Query(None, max_length=32),
                     delta: Optional[float] = Query(None, ge=-1e6, le=1e6)) -> DependencyGraph:
    if case_id:
        _check_id(case_id, "case_id")
    try:
        return dependencies.build_graph(case_id or None, measurement or None, delta, get_investigation)
    except KeyError as exc:
        raise _not_found(exc) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)[:500]) from None


# ----------------------------------------------------------------------------- onboarding
@router.post("/onboarding", response_model=OnboardingBrief)
async def create_onboarding(body: OnboardingRequest) -> OnboardingBrief:
    _check_id(body.persona, "persona")
    client = get_meta_client()
    try:
        return await run_in_threadpool(onboarding.generate_brief, body.persona, client=client,
                                       investigations=get_investigations())
    except KeyError as exc:
        raise _not_found(exc) from None


@router.get("/onboarding", response_model=OnboardingLatest)
def latest_onboarding(persona: str = Query(..., min_length=1, max_length=64)) -> OnboardingLatest:
    _check_id(persona, "persona")
    from app.plant.personas import PERSONAS

    if persona not in PERSONAS:
        raise HTTPException(status_code=404, detail=f"unknown persona '{persona}'")
    return OnboardingLatest(persona=persona, brief=db.latest_brief(persona))
