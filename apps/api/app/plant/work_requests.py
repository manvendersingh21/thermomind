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
from app.plant.personas import (ALWAYS_INFO, EMISSIONS_PERSONA, HOT_GAS_PATH_PERSONA, URGENT_ALSO_NOTIFY,
                                 label, route)
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


NOTABLE_Z = 2.0


def _evidence_z(inv: Any, ids: tuple[str, ...]) -> dict[str, float]:
    out = {}
    for e in inv.evidence or []:
        if e.evidence_id in ids and e.z_score is not None and abs(e.z_score) >= NOTABLE_Z:
            out[e.evidence_id] = float(e.z_score)
    return out


def emissions_z(inv: Any) -> dict[str, float]:
    """Window-vs-reference z for CO/NOX on REAL rows (the evidence engine has no CO/NOx items).

    z = (mean_window - mean_reference) / std_reference, computed at routing time; {} if data unavailable."""
    try:
        from app import services

        bundle = services.get_repo().get(inv.request.dataset_id)
        w = bundle.window(inv.window.source_year, inv.window.start, inv.window.end)
        r = bundle.window(inv.reference.source_year, inv.reference.start, inv.reference.end)
    except Exception:  # noqa: BLE001 - optional escalation signal
        return {}
    out = {}
    for m in ("CO", "NOX"):
        if m in w.columns and m in r.columns:
            sd = float(r[m].std(ddof=0))
            if sd > 0:
                out[m] = round((float(w[m].mean()) - float(r[m].mean())) / sd, 3)
    return out


def recipients(inv: Any, key: str, severity: str) -> tuple[dict[str, Any], dict[str, str]]:
    """(routing rule, {persona_id: reason}) — ordered: assignee, supervisor, cc, escalations, operator."""
    rule = route(key)
    reasons: dict[str, str] = {rule["assignee"]: f"assignee (rule:{key})"}
    sup = rule.get("supervisor")
    if sup and sup not in reasons:
        reasons[sup] = f"supervisor of {label(rule['assignee'])}"
    for pid in rule.get("cc", []):
        if pid not in reasons:
            reasons[pid] = ("cc: field inspection needs permit / isolation per procedure" if pid == "hse_officer"
                            else f"cc (rule:{key})")
    if severity == "urgent_review":
        for pid in URGENT_ALSO_NOTIFY:
            reasons.setdefault(pid, "escalation: severity urgent_review")
    em = {m: z for m, z in emissions_z(inv).items() if abs(z) >= NOTABLE_Z}
    if em:
        reasons.setdefault(EMISSIONS_PERSONA, "escalation: notable " + ", ".join(f"{m} z={z:+.2f}" for m, z in em.items())
                           + " (real rows, window vs reference)")
    hgp = _evidence_z(inv, ("ev_tit_01", "ev_tat_01"))
    if hgp:
        reasons.setdefault(HOT_GAS_PATH_PERSONA, "escalation (external, simulated): notable hot-gas-path evidence "
                           + ", ".join(f"{k} z={v:+.2f}" for k, v in hgp.items()))
    for pid in ALWAYS_INFO:
        reasons.setdefault(pid, "info: control room sees every alert (read-only acknowledgement)")
    return rule, reasons


def create_for_investigation(inv: Any) -> Optional[WorkRequest]:
    if inv.status not in ("completed", "needs_review"):
        return None
    existing = store.list_work_requests(case_id=inv.case_id)
    if existing:  # idempotent per case
        return existing[0]
    key = rank1_hypothesis(inv) or "unknown"
    report = inv.report
    severity = report.severity if report is not None else "review"
    rule, reasons = recipients(inv, key, severity)
    persona, supervisor = rule["assignee"], rule.get("supervisor")
    checks = list(report.engineer_review_checks) if report is not None else [
        "Report needs human review (no validated report); inspect the deterministic summary and evidence."]
    synthetic = bool(inv.scenario.synthetic)
    tag = "SYNTHETIC OVERLAY" if synthetic else "REAL DATA"
    title = (f"[{severity}] {inv.scenario.title} — review '{key}' "
             f"({inv.window.source_year} • samples {inv.window.start}–{inv.window.end - 1}, {tag})")
    assignment = (f"Assigned to {label(persona)} · Supervisor {label(supervisor)} · simulated notification")
    now = _now()
    wr = WorkRequest(
        id=_new_id("wr"), case_id=inv.case_id, assigned_persona=persona, title=title[:300], status="open",
        created_at_utc=now, updated_at_utc=now, checks=checks, routed_by=f"rule:{key}", hypothesis_key=key,
        severity=severity, scenario_id=inv.scenario.scenario_id, scenario_label=inv.scenario_label,
        synthetic=synthetic, investigation_status=inv.status, supervisor_persona=supervisor,
        cc_personas=[p for p in reasons if p not in (persona, supervisor)],
        notified_personas=list(reasons), notification_reasons=reasons, assignment_label=assignment,
        history=[WorkRequestComment(ts_utc=now, persona="system", status="open",
                                    comment=f"Routed by rule:{key}. {assignment}. Notified: "
                                            f"{', '.join(reasons)}. {DELIVERY_NOTE}")],
    )
    store.save_work_request(wr)
    for pid, why in reasons.items():
        is_assignee = pid == persona
        msg = (f"New work request: {title[:200]} · {len(checks)} review check(s). {assignment}. "
               f"Draft requires human review." if is_assignee else
               f"[{why}] Work request {wr.id} for case {inv.case_id} ({tag}) assigned to {label(persona)}: "
               f"{title[:160]}")
        store.save_notification(Notification(
            id=_new_id("ntf"), persona=pid, kind="work_request" if pid in (persona, supervisor) else "info",
            created_at_utc=now, case_id=inv.case_id, work_request_id=wr.id, message=msg))
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
