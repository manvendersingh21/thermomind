"""Human decision on a deliberation: recorded and routed (simulated in-app notification). Never any plant effect.

Every decision (approve_plan / reject / defer) -> a stored record + ONE simulated in-app notification to the
decider's supervisor (the decider when none). Nothing else is created or triggered; nothing is executed.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from app.features.deliberation import deliberate, store
from app.features.deliberation.schemas import DecisionRequest, DeliberationSession, HumanDecision
from app.plant import store as plant_store
from app.plant.personas import PERSONAS, resolve_persona
from app.plant.personas import label as persona_label
from app.plant.schemas import DELIVERY_NOTE, Notification

WR_CREATE_CANDIDATES = ("create_work_request", "create_manual", "create_standalone", "create_plan_request")


class DecisionConflict(ValueError):
    status_code = 409


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def work_request_creator() -> Optional[Callable[..., Any]]:
    """A work-request create function that does not need an investigation, if plant.work_requests offers one."""
    try:
        from app.plant import work_requests
    except Exception:  # noqa: BLE001
        return None
    for name in WR_CREATE_CANDIDATES:
        fn = getattr(work_requests, name, None)
        if callable(fn):
            return fn
    return None


def record_decision(deliberation_id: str, req: DecisionRequest, persona: Optional[str] = None) -> DeliberationSession:
    s = deliberate.get_session(deliberation_id)  # KeyError -> 404
    if s.status == "running":
        raise DecisionConflict("deliberation is still running; a decision can be recorded once it has finished")
    if s.status == "failed":
        raise DecisionConflict("deliberation failed; start a new one before recording a decision")
    p = resolve_persona(req.persona or persona)  # KeyError -> 404
    sup = p.supervisor or SUPERVISOR_FALLBACK(p.persona_id)
    now = _now()
    comment = req.comment.strip()[:2000] if req.comment and req.comment.strip() else None
    intent = s.change.text
    verb = {"approve_plan": "approved the plan", "reject": "rejected the plan", "defer": "deferred the decision"}[
        req.decision]
    rec = s.outcome.recommendation if s.outcome else "n/a"
    msg = (f"Human decision on deliberation {s.deliberation_id}: {persona_label(p.persona_id)} {verb} for "
           f"'{intent}' (agents' advisory recommendation: {rec}). "
           + (f"Comment: {comment[:300]}. " if comment else "")
           + "Recorded only; ThermoMind executed nothing. " + DELIVERY_NOTE)
    ntf = plant_store.save_notification(Notification(
        id=f"ntf_{secrets.token_hex(5)}", persona=sup, kind="info", created_at_utc=now, case_id=s.case_id,
        message=msg[:1000]))
    wr_id, note = None, f"Notification to {persona_label(sup)} (simulated in-app)."
    # By design a decision is a record + one simulated notification, nothing else: no work request, no task, no
    # call into any other module (even if app.plant.work_requests later offers a standalone create function).
    note += " Record + notification only; no work request or any other action is created by this endpoint."
    d = HumanDecision(decision=req.decision, persona=p.persona_id, persona_label=persona_label(p.persona_id),
                      comment=comment, recorded_at_utc=now, routed_to=sup, routed_to_label=persona_label(sup),
                      notification_id=ntf.id, work_request_id=wr_id, routing_note=note,
                      message=f"Recorded; routed to {persona_label(sup)}; nothing was executed")
    updated = s.model_copy(update={"decisions": [*s.decisions, d]})
    return store.save(updated)


def SUPERVISOR_FALLBACK(persona_id: str) -> str:  # noqa: N802 - small policy helper
    """Personas without a supervisor (plant manager) route the record to themselves; otherwise shift supervisor."""
    return persona_id if persona_id in PERSONAS and PERSONAS[persona_id].supervisor is None else \
        deliberate.SUPERVISOR_DEFAULT
