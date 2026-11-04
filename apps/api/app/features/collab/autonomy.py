"""Autonomy policy: "who decides what".

Three levels:
* ``agent_auto``   — read-only work agents do on their own and log (screening, evidence computation, routing,
                     precedent recall, drafts, and auto-triage of informational real-only cases).
* ``human_review`` — an agent drafts or proposes, a named human persona decides.
* ``human_only``   — maintenance, switching or any plant control. ThermoMind has NO software path for these.

``apply_autonomy_policy(inv)`` is called by ``services.run_investigation_pipeline`` right after the plant routing
hook. It never raises. It only writes a decision row (``collab_decisions``) and, for an auto-triage, one simulated
in-app info notification to the control-room operator. It never changes the investigation, its report, the
work request or anything in the plant.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import Any, Optional

from app.features.collab import db
from app.features.collab.schemas import AutoDecision, PolicyAction, PolicyCondition, PolicyResponse

log = logging.getLogger("thermomind.collab.autonomy")

POLICY_ID = "P-01"
NOTABLE_Z = 2.0
NOTABLE_FLAGS = {"notable_deviation", "isolated_single_sensor", "out_of_training_range"}
# z-scores checked for "no notable evidence" (same signature list as precedent memory)
SIGNAL_IDS = ("ev_afdp_01", "ev_afdp_02", "ev_tey_residual_01", "ev_tey_residual_02", "ev_cdp_01", "ev_tit_01",
              "ev_tat_01", "ev_gtep_01", "ev_at_01", "ev_ah_01", "ev_ap_01")
OPERATOR = "control_room_operator"

LEVELS = {
    "agent_auto": "Agent does it automatically — read-only computation, routing, logging or drafting; always logged.",
    "human_review": "Agent drafts or proposes; a named human persona decides.",
    "human_only": "Humans only, outside ThermoMind. The software has no path to do this.",
}

ACTIONS: list[PolicyAction] = [
    # --- agent_auto (read-only)
    PolicyAction(action_id="screen_window", action="Screen a data window and compute evidence (z-scores, baseline "
                 "residuals, data quality)", level="agent_auto", actor="agent:investigator", reversible=True,
                 why="Deterministic, read-only computation on stored rows; numbers are recomputable.",
                 link="/investigations"),
    PolicyAction(action_id="draft_case_report", action="Draft the diagnostic case report (Muse Spark, validated)",
                 level="agent_auto", actor="agent:investigator", reversible=True,
                 why="Report is always draft_requires_human_review; the validator rejects control wording.",
                 link="/investigations"),
    PolicyAction(action_id="route_case", action="Route a case to the responsible persona + their supervisor "
                 "(simulated in-app notification)", level="agent_auto", actor="agent:router", reversible=True,
                 why="Fixed rule table over the rank-1 hypothesis; only creates an inbox item.", link="/inbox"),
    PolicyAction(action_id="recall_precedents", action="Recall reviewed precedents (similar past cases)",
                 level="agent_auto", actor="agent:investigator", reversible=True,
                 why="Read-only retrieval of past human review decisions; context, not ground truth.",
                 link="/investigations"),
    PolicyAction(action_id="draft_handover", action="Draft a shift handover note", level="agent_auto",
                 actor="agent:handover", reversible=True,
                 why="A draft; the shift supervisor signs it off.", link="/ops"),
    PolicyAction(action_id="draft_onboarding", action="Draft an onboarding brief for a new joiner",
                 level="agent_auto", actor="agent:onboarding", reversible=True,
                 why="A reading guide; the new joiner verifies it with their supervisor.", link="/onboarding"),
    PolicyAction(action_id="auto_triage", action=f"Auto-triage an informational, real-data, non-notable case as "
                 f"'no human action needed; logged' (policy {POLICY_ID})", level="agent_auto",
                 actor="agent:autonomy_policy", reversible=True,
                 why="Only when every condition holds; the case, report and work request are left untouched and "
                     "any persona can reopen it for human review.", link="/autonomy"),
    # --- human_review
    PolicyAction(action_id="review_case_report", action="Accept / reject a case report or request more data",
                 level="human_review", actor="reliability_engineer (or the reviewing engineer)", reversible=False,
                 why="Engineering judgement on a draft; recorded with reviewer name and becomes a precedent.",
                 link="/investigations"),
    PolicyAction(action_id="work_request_status", action="Acknowledge / mark done / dismiss a work request",
                 level="human_review", actor="assigned persona (supervisor oversight)", reversible=False,
                 why="Only the people doing the work know whether it is done.", link="/inbox"),
    PolicyAction(action_id="approve_next_steps", action="Approve the what-if 'recommended next steps' before "
                 "anyone acts on them", level="human_review", actor="supervisor of the asking technician",
                 reversible=True, why="Every next step carries requires_supervisor_approval = true.", link="/ask"),
    PolicyAction(action_id="sign_off_handover", action="Sign off the shift handover note", level="human_review",
                 actor="shift_supervisor", reversible=True, why="The handover is a draft until signed.",
                 link="/ops"),
    PolicyAction(action_id="reopen_auto_triage", action="Reopen an auto-triaged case for human review",
                 level="human_review", actor="any persona", reversible=True,
                 why="Auto-triage is reversible by design.", link="/autonomy"),
    # --- human_only
    PolicyAction(action_id="maintenance_work", action="Perform maintenance / inspections / calibration in the field",
                 level="human_only", actor="maintenance & I&C technicians under permit (hse_officer)",
                 reversible=False, why="Physical work under the plant's own permit-to-work system; not in ThermoMind.",
                 link=None),
    PolicyAction(action_id="switching", action="Electrical switching or isolation", level="human_only",
                 actor="authorised plant staff per procedure", reversible=False,
                 why="Safety-critical; done per plant procedure only. No software path exists.", link=None),
    PolicyAction(action_id="plant_control", action="Any plant control: setpoints, load, fuel, valves, trips",
                 level="human_only", actor="control-room operator on the plant DCS (outside ThermoMind)",
                 reversible=False, why="ThermoMind is read-only decision support; it has no control interface.",
                 link=None),
]

AUTO_TRIAGE_CONDITIONS = [
    "investigation status is 'completed' with a validated report (not needs_review / failed)",
    "report severity is 'informational'",
    "real data only: scenario_label 'real_only', scenario not synthetic, no synthetic evidence",
    "no evidence with flags notable_deviation / isolated_single_sensor / out_of_training_range, and every "
    "evidence item has data_quality 'pass'",
    f"no main signal evidence (AFDP, TEY residual, CDP, TIT, TAT, GTEP, AT, AH, AP) with |z| ≥ {NOTABLE_Z:g}",
    f"no notable CO / NOx deviation (|z| ≥ {NOTABLE_Z:g}, real rows, window vs reference) when it can be computed",
]


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _new_id() -> str:
    return f"dec_{secrets.token_hex(6)}"


# ----------------------------------------------------------------------------- evaluation
def _emissions_z(inv: Any) -> Optional[dict[str, float]]:
    try:
        from app.plant.work_requests import emissions_z  # guarded: plant-ops workstream

        return emissions_z(inv)
    except Exception:  # noqa: BLE001
        return None


def evaluate(inv: Any, emissions: Optional[dict[str, float]] = None) -> list[PolicyCondition]:
    """Evaluate the P-01 auto-triage conditions. ``emissions`` may be injected (tests); else computed if possible."""
    conds: list[PolicyCondition] = []
    report = getattr(inv, "report", None)
    conds.append(PolicyCondition(
        name="completed_with_report", passed=inv.status == "completed" and report is not None,
        detail=f"status={inv.status}, report={'present' if report is not None else 'none'}"))
    sev = report.severity if report is not None else None
    conds.append(PolicyCondition(name="informational", passed=sev == "informational", detail=f"severity={sev}"))
    syn_ev = [e.evidence_id for e in inv.evidence or [] if getattr(e, "is_synthetic", False)]
    real = inv.scenario_label == "real_only" and not inv.scenario.synthetic and not syn_ev
    conds.append(PolicyCondition(name="real_data_only", passed=real, detail=(
        f"scenario_label={inv.scenario_label}, synthetic={inv.scenario.synthetic}"
        + (f", synthetic evidence {syn_ev[:4]}" if syn_ev else ""))))
    flagged = [e.evidence_id for e in inv.evidence or []
               if (NOTABLE_FLAGS & set(e.flags or [])) or e.data_quality != "pass"]
    conds.append(PolicyCondition(name="no_notable_flags", passed=not flagged,
                                 detail=("none" if not flagged else "flagged: " + ", ".join(flagged[:6]))))
    high = [f"{e.evidence_id} z={e.z_score:+.2f}" for e in inv.evidence or []
            if e.evidence_id in SIGNAL_IDS and e.z_score is not None and abs(e.z_score) >= NOTABLE_Z]
    conds.append(PolicyCondition(name="no_notable_signal_z", passed=not high,
                                 detail=("max |z| below threshold" if not high else ", ".join(high[:6]))))
    em = emissions if emissions is not None else _emissions_z(inv)
    if em is None:
        conds.append(PolicyCondition(name="no_notable_emissions", passed=True,
                                     detail="CO/NOx z not computable here (data unavailable); not used"))
    else:
        bad = {m: z for m, z in em.items() if abs(z) >= NOTABLE_Z}
        conds.append(PolicyCondition(name="no_notable_emissions", passed=not bad, detail=(
            "none" if not bad else ", ".join(f"{m} z={z:+.2f}" for m, z in bad.items()))))
    return conds


def _routed_personas(case_id: str) -> list[str]:
    try:
        from app.plant import store as plant_store  # guarded

        wrs = plant_store.list_work_requests(case_id=case_id)
        return list(wrs[0].notified_personas) if wrs else []
    except Exception:  # noqa: BLE001
        return []


def _notify_operator(inv: Any, decision: AutoDecision) -> None:
    try:
        from app.plant import store as plant_store  # guarded
        from app.plant.schemas import Notification

        plant_store.save_notification(Notification(
            id=f"ntf_{secrets.token_hex(5)}", persona=OPERATOR, kind="info", created_at_utc=decision.ts_utc,
            case_id=inv.case_id, message=(
                f"Case {inv.case_id} (REAL DATA, informational) auto-triaged by policy {POLICY_ID}; no human action "
                f"required; reversible — any persona can reopen it on /autonomy. Decision {decision.decision_id}.")))
    except Exception as exc:  # noqa: BLE001
        log.info("operator notification skipped: %s", type(exc).__name__)


def decide(inv: Any, emissions: Optional[dict[str, float]] = None, notify: bool = True) -> AutoDecision:
    """Evaluate, persist and return the decision for one investigation (idempotent per case)."""
    existing = db.list_decisions(case_id=inv.case_id, limit=1)
    if existing:
        return existing[0]
    conds = evaluate(inv, emissions)
    failed = [c for c in conds if not c.passed]
    sev = inv.report.severity if inv.report is not None else None
    routed = _routed_personas(inv.case_id)
    synthetic = bool(inv.scenario.synthetic) or inv.scenario_label != "real_only"
    if not failed:
        d = AutoDecision(
            decision_id=_new_id(), case_id=inv.case_id, decision="auto_triaged_no_action", policy_id=POLICY_ID,
            ts_utc=now_utc(), reversible=True, routed_personas=routed, conditions=conds, synthetic=False,
            severity=sev, reason=(f"All {len(conds)} conditions of {POLICY_ID} hold (informational, real data only, "
                                  "no notable evidence): no human action needed; logged. Investigation, report and "
                                  "work request are unchanged; reversible."))
    else:
        d = AutoDecision(
            decision_id=_new_id(), case_id=inv.case_id, decision="requires_human", policy_id=POLICY_ID,
            ts_utc=now_utc(), reversible=True, routed_personas=routed, conditions=conds, synthetic=synthetic,
            severity=sev, reason=("Human review required: " + "; ".join(f"{c.name} ({c.detail})" for c in failed[:4])
                                  + (f". Routed to {', '.join(routed)}." if routed else ".")))
    db.save_decision(d)
    if d.decision == "auto_triaged_no_action" and notify:
        _notify_operator(inv, d)
    return d


def apply_autonomy_policy(inv: Any) -> Optional[AutoDecision]:
    """Hook called after an investigation is saved and routed. Never raises."""
    try:
        d = decide(inv)
        log.info("policy %s -> %s for %s", POLICY_ID, d.decision, inv.case_id)
        return d
    except Exception as exc:  # noqa: BLE001 - the policy log must never break the investigation pipeline
        log.warning("autonomy policy failed for %s: %s", getattr(inv, "case_id", "?"), type(exc).__name__)
        return None


def reopen(decision_id: str, persona: Optional[str], comment: Optional[str]) -> AutoDecision:
    """Human override: record that an auto-triaged case needs human review. KeyError -> 404, ConflictError -> 409."""
    d = db.get_decision(decision_id)
    if d.decision != "auto_triaged_no_action":
        raise ConflictError(f"decision '{decision_id}' is '{d.decision}'; only auto_triaged_no_action can be reopened")
    latest = db.list_decisions(case_id=d.case_id, limit=1)
    if latest and latest[0].decision_id != d.decision_id:
        raise ConflictError(f"decision '{decision_id}' was already superseded by '{latest[0].decision_id}'")
    who = (persona or "").strip() or "unknown_persona"
    new = AutoDecision(
        decision_id=_new_id(), case_id=d.case_id, decision="human_override_reopened", policy_id=d.policy_id,
        ts_utc=now_utc(), reversible=True, actor=who, routed_personas=d.routed_personas, conditions=d.conditions,
        synthetic=d.synthetic, severity=d.severity, supersedes=d.decision_id,
        comment=(comment or "").strip()[:2000] or None,
        reason=f"Reopened for human review by {who} (overrides auto-triage {d.decision_id}).")
    return db.save_decision(new)


class ConflictError(ValueError):
    status_code = 409


def policy_response() -> PolicyResponse:
    return PolicyResponse(
        policy_id=POLICY_ID, title="Who decides what", levels=LEVELS, actions=ACTIONS,
        auto_triage_conditions=AUTO_TRIAGE_CONDITIONS, counts=db.decision_counts(),
        note=("'Automatic' covers only read-only computation, routing, logging and drafts. Nothing in ThermoMind "
              "operates the plant: no PLC/SCADA/DCS writes, no setpoints, no control commands. Personas are demo "
              "accounts without authentication."))
