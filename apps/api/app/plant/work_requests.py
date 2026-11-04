"""Rule-based routing of completed investigations to demo personas (simulated in-app delivery).

``on_investigation_completed(inv)`` is called by ``services.run_investigation_pipeline`` right after the
investigation is persisted. It never raises: plant-ops routing must not break an investigation.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import Any, Optional

from app.plant import store
from app.plant.personas import PERSONAS, URGENT_ALSO_NOTIFY, route
from app.plant.schemas import DELIVERY_NOTE, Notification, WorkRequest, WorkRequestComment

log = logging.getLogger("thermomind.plant.work_requests")

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "open": {"acknowledged", "done", "dismissed"},
    "acknowledged": {"done", "dismissed"},
    "done": set(),
    "dismissed": set(),
}


class TransitionError(ValueError):
    status_code = 409


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(5)}"


def rank1_hypothesis(inv: Any) -> Optional[str]:
    """Rank-1 hypothesis key from the report; falls back to the deterministic summary's top hypothesis."""
    report = getattr(inv, "report", None)
    if report is not None and report.hypotheses:
        top = sorted(report.hypotheses, key=lambda h: h.rank)[0]
        if top.key:
            return top.key
    tops = (getattr(inv, "deterministic_summary", None) or {}).get("top_hypotheses") or []
    if tops and isinstance(tops[0], dict):
        return tops[0].get("hypothesis_key")
    return None


def create_for_investigation(inv: Any) -> Optional[WorkRequest]:
    if inv.status not in ("completed", "needs_review"):
        return None
    existing = store.list_work_requests(case_id=inv.case_id)
    if existing:  # idempotent per case
        return existing[0]
    key = rank1_hypothesis(inv) or "unknown"
    persona = route(key)
    report = inv.report
    severity = report.severity if report is not None else "review"
    checks = list(report.engineer_review_checks) if report is not None else [
        "Report needs human review (no validated report); inspect the deterministic summary and evidence."]
    synthetic = bool(inv.scenario.synthetic)
    tag = "SYNTHETIC OVERLAY" if synthetic else "REAL DATA"
    title = (f"[{severity}] {inv.scenario.title} — review '{key}' "
             f"({inv.window.source_year} • samples {inv.window.start}–{inv.window.end - 1}, {tag})")
    now = _now()
    wr = WorkRequest(
        id=_new_id("wr"), case_id=inv.case_id, assigned_persona=persona, title=title[:300], status="open",
        created_at_utc=now, updated_at_utc=now, checks=checks, routed_by=f"rule:{key}", hypothesis_key=key,
        severity=severity, scenario_id=inv.scenario.scenario_id, scenario_label=inv.scenario_label,
        synthetic=synthetic, investigation_status=inv.status,
        history=[WorkRequestComment(ts_utc=now, persona="system", status="open",
                                    comment=f"Routed by rule:{key} -> {persona}. {DELIVERY_NOTE}")],
    )
    store.save_work_request(wr)
    store.save_notification(Notification(
        id=_new_id("ntf"), persona=persona, kind="work_request", created_at_utc=now, case_id=inv.case_id,
        work_request_id=wr.id,
        message=f"New work request for {PERSONAS[persona].role}: {title[:200]}. {len(checks)} review check(s). "
                f"Draft requires human review."))
    if severity == "urgent_review":
        for pid in URGENT_ALSO_NOTIFY:
            if pid == persona:
                continue
            store.save_notification(Notification(
                id=_new_id("ntf"), persona=pid, kind="info", created_at_utc=now, case_id=inv.case_id,
                work_request_id=wr.id,
                message=f"FYI urgent_review case {inv.case_id} routed to {PERSONAS[persona].name} "
                        f"(rule:{key}). {tag}."))
    return wr


def on_investigation_completed(inv: Any) -> None:
    """Hook called after an investigation is saved. Never raises."""
    try:
        wr = create_for_investigation(inv)
        if wr is not None:
            log.info("work request %s -> %s (%s) for %s", wr.id, wr.assigned_persona, wr.routed_by, inv.case_id)
    except Exception as exc:  # noqa: BLE001 - routing must never break the investigation pipeline
        log.warning("plant routing failed for %s: %s", getattr(inv, "case_id", "?"), type(exc).__name__)


def update_status(wr_id: str, status: str, comment: Optional[str], persona: str) -> WorkRequest:
    wr = store.get_work_request(wr_id)  # KeyError -> 404
    if status not in ALLOWED_TRANSITIONS.get(wr.status, set()):
        raise TransitionError(f"cannot move work request from '{wr.status}' to '{status}' "
                              f"(allowed: {sorted(ALLOWED_TRANSITIONS.get(wr.status, set())) or 'none, final'})")
    now = _now()
    text = comment.strip()[:2000] if comment and comment.strip() else None
    updated = wr.model_copy(update={
        "status": status, "updated_at_utc": now,
        "history": [*wr.history, WorkRequestComment(ts_utc=now, persona=persona, status=status, comment=text)],
    })
    return store.save_work_request(updated)


def mark_read(n_id: str) -> Notification:
    n = store.get_notification(n_id)
    return store.save_notification(n.model_copy(update={"read": True}))
