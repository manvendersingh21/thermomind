"""Deliberation for watchdog proposals.

Order of preference:
1. ``app.features.deliberation`` (the shared deliberation feature, built concurrently) when importable: its propose
   function is called with ``origin="watchdog"`` and the intent/magnitude (guarded; any failure falls through).
2. Built-in compact deliberation: ONE Muse Spark call (MetaClient, max_tokens 6000, JSON object) with the detection
   evidence and the subsystem list, asking for {recommendation, summary, harms_elsewhere, conditions,
   who_must_approve}. Output is validated (Pydantic + the investigation validator's UNSAFE_PATTERNS scan). Text must
   be phrased as options and conditions; a failing answer is NOT used to auto-execute anything (recommendation is
   forced to hold_for_human and the deterministic text is shown, labelled).
3. Offline fallback (no key / Meta error): a deterministic rule, labelled ``offline (no Meta call)``.
"""
from __future__ import annotations

import importlib
import json
import logging
from typing import Any, Callable, Literal, Optional

from pydantic import BaseModel, Field, ValidationError

log = logging.getLogger("thermomind.watchdog.deliberation")

MAX_TOKENS = 6000
Recommendation = Literal["proceed_with_conditions", "hold_for_human", "do_not_proceed"]


class Harm(BaseModel):
    subsystem: str = Field(..., max_length=120)
    effect: str = Field(..., max_length=600)


class DeliberationAnswer(BaseModel):
    recommendation: Recommendation
    summary: str = Field(..., max_length=1500)
    harms_elsewhere: list[Harm] = Field(default_factory=list, max_length=8)
    conditions: list[str] = Field(default_factory=list, max_length=10)
    who_must_approve: list[str] = Field(default_factory=list, max_length=6)


def _unsafe_patterns() -> list:
    try:
        from app.agent.report_validator import UNSAFE_PATTERNS
        return list(UNSAFE_PATTERNS)
    except Exception:  # noqa: BLE001
        return []


def unsafe_hits(texts: list[str]) -> list[str]:
    hits = []
    for t in texts:
        for label, pat in _unsafe_patterns():
            m = pat.search(t or "")
            if m:
                hits.append(f"{label}: '{m.group(0)[:60]}'")
    return hits


def answer_texts(a: DeliberationAnswer) -> list[str]:
    return [a.summary, *a.conditions, *(h.effect for h in a.harms_elsewhere), *(h.subsystem for h in a.harms_elsewhere)]


def subsystem_list() -> list[dict[str, str]]:
    out = [
        {"key": "aux_cooling_water", "name": "Cooling-water pumps A/B (SIMULATED, 2×100 %)",
         "note": "carry condenser heat rejection; losing both curtails the steam cycle"},
        {"key": "aux_feedwater", "name": "Boiler feedwater pumps A/B (SIMULATED, 2×100 %)",
         "note": "carry steam-cycle feedwater; losing both curtails the steam cycle"},
        {"key": "aux_ct_fans", "name": "Cooling-tower fans 1–3 (SIMULATED, 3×33 %)", "note": "airflow sets cooling capacity"},
        {"key": "aux_lube_oil", "name": "Lube-oil pump (SIMULATED, single)", "note": "unit cannot run without it"},
    ]
    try:
        from app.plant.subsystems import SUBSYSTEM_REGISTRY
        out += [{"key": s["key"], "name": s["name"], "note": s.get("description", "")} for s in SUBSYSTEM_REGISTRY]
    except Exception:  # noqa: BLE001
        pass
    return out


def persona_ids() -> list[str]:
    try:
        from app.plant.personas import PERSONAS
        return list(PERSONAS)
    except Exception:  # noqa: BLE001
        return ["control_room_operator", "shift_supervisor", "mechanical_maintenance_engineer", "electrical_engineer",
                "plant_manager"]


# --------------------------------------------------------------------------- deterministic fallback
def offline_answer(detection: dict, proposal: dict) -> DeliberationAnswer:
    cls = proposal.get("action_class")
    asset = detection.get("asset", "?")
    if cls == "simulated_auxiliary_switchover":
        p = proposal.get("params", {})
        return DeliberationAnswer(
            recommendation="proceed_with_conditions",
            summary=(f"Rule-based assessment: the evidence on {asset} matches an auxiliary motor overheating "
                     f"signature and a 2×100 % standby ({p.get('start')}) exists, so the proposed switchover is "
                     "reversible and low risk inside the simulated auxiliaries model, subject to the conditions."),
            harms_elsewhere=[
                Harm(subsystem=p.get("group", "auxiliaries"),
                     effect="Brief parallel running during the changeover raises header flow and motor current; "
                            "the standby start draws direct-on-line inrush for a few seconds."),
                Harm(subsystem="redundancy", effect=f"While {asset} is out of service there is no standby in this group "
                                                    "(N+0) until it is returned."),
            ],
            conditions=[f"{p.get('start')} is not tagged out and has no protection trip (start interlock)",
                        f"{p.get('start')} proves running before {p.get('stop')} leaves service (minimum-flow interlock)",
                        "Shift supervisor is notified; maintenance inspects the removed motor under a permit"],
            who_must_approve=["shift_supervisor"],
        )
    return DeliberationAnswer(
        recommendation="hold_for_human",
        summary=(f"Rule-based assessment: class '{cls}' affects the real plant or dispatch and is never executed by "
                 "ThermoMind; the responsible persona and supervisor decide."),
        harms_elsewhere=[Harm(subsystem="unit output", effect="Dispatch and unit-commitment choices change grid "
                                                              "obligations and fuel use; evaluate with dispatch.")],
        conditions=["Human decision through plant procedures", "Confirm the evidence against field readings"],
        who_must_approve=["shift_supervisor", "plant_manager"],
    )


# --------------------------------------------------------------------------- built-in Meta call
SYSTEM_PROMPT = (
    "You are the deliberation step of ThermoMind's watchdog, a read-only decision-support tool for a combined-cycle "
    "plant. A detector has fired and an automatically generated proposal exists. Assess it and return ONLY a JSON "
    "object with keys: recommendation (one of proceed_with_conditions, hold_for_human, do_not_proceed), summary "
    "(<= 4 sentences), harms_elsewhere (list of {subsystem, effect}: what the proposal could harm in OTHER "
    "subsystems), conditions (list of short conditions that must hold), who_must_approve (persona ids from the "
    "given list).\n"
    "Rules: (1) The auxiliaries are a SIMULATED model; the only thing that can ever execute automatically is a "
    "reversible switchover inside that simulation. Anything touching the real plant, unit commitment or dispatch "
    "must be hold_for_human. (2) Write options and conditions, never instructions: refer to the action only as "
    "'the proposed switchover' or 'the proposed action'. Do not write operating verbs followed by equipment "
    "(e.g. never 'start pump B', 'stop the unit', 'open the valve', 'take the unit offline'). (3) Use only the "
    "numbers given in the evidence; do not invent readings, dates or test results. (4) Prefer "
    "proceed_with_conditions for a reversible simulated switchover when the evidence supports it and a standby "
    "is available; otherwise hold_for_human."
)


def build_messages(detection: dict, proposal: dict, aux_summary: dict) -> list[dict]:
    user = {
        "detection": {k: detection.get(k) for k in ("kind", "asset", "severity", "evidence", "rationale")},
        "proposal": {k: proposal.get(k) for k in ("intent", "action_class", "magnitude", "params")},
        "auxiliaries_now": aux_summary,
        "subsystems": subsystem_list(),
        "personas": persona_ids(),
    }
    return [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user, default=str)[:12000]}]


def _builtin(detection: dict, proposal: dict, aux_summary: dict, client: Any) -> dict[str, Any]:
    from app.agent.report_validator import extract_json

    try:
        res = client.chat(build_messages(detection, proposal, aux_summary), tools=None, max_tokens=MAX_TOKENS,
                          response_format={"type": "json_object"})
    except Exception as exc:  # noqa: BLE001 - MetaClientError or anything else -> offline fallback
        ans = offline_answer(detection, proposal)
        return {"mode": "offline_fallback", "mode_label": f"offline fallback after Meta error ({str(exc)[:120]})",
                "validated": True, "answer": ans.model_dump(), "errors": [str(exc)[:200]], "latency_ms": 0}
    raw = (res.message or {}).get("content") or ""
    errors: list[str] = []
    ans: Optional[DeliberationAnswer] = None
    data = extract_json(raw) if raw else None
    if data is None:
        errors.append(f"no JSON object in the model answer (finish_reason={res.finish_reason})")
    else:
        try:
            ans = DeliberationAnswer.model_validate(data)
        except ValidationError as exc:
            errors.append(f"schema: {exc.error_count()} error(s): " + "; ".join(
                f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()[:4]))
    if ans is not None:
        hits = unsafe_hits(answer_texts(ans))
        if hits:
            errors.append("unsafe-pattern scan: " + "; ".join(hits[:4]))
            ans = None
    meta = {"latency_ms": res.latency_ms, "model": res.model, "usage": res.usage}
    if ans is None:
        fb = offline_answer(detection, proposal)
        fb = fb.model_copy(update={"recommendation": "hold_for_human",
                                   "summary": "Model answer failed validation; deterministic text shown and the "
                                              "proposal is held for a human. " + fb.summary})
        return {"mode": "meta_live_rejected", "mode_label": "Muse Spark answer rejected by validation → held for human",
                "validated": False, "answer": fb.model_dump(), "errors": errors, **meta}
    return {"mode": "meta_live", "mode_label": f"META LIVE ({res.model or 'muse-spark'}, one call)",
            "validated": True, "answer": ans.model_dump(), "errors": [], **meta}


# --------------------------------------------------------------------------- shared deliberation feature (guarded)
def _find(mod_names: list[str], fn_names: tuple[str, ...]) -> Optional[Callable]:
    for mn in mod_names:
        try:
            mod = importlib.import_module(mn)
        except Exception:  # noqa: BLE001
            continue
        for fn in fn_names:
            f = getattr(mod, fn, None)
            if callable(f):
                return f
    return None


def _to_dict(obj: Any) -> dict:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return dict(getattr(obj, "__dict__", {}) or {})


def normalise_recommendation(value: Any) -> str:
    v = str(value or "").lower().replace("-", "_").replace(" ", "_")
    if "proceed" in v and "condition" in v:
        return "proceed_with_conditions"
    if v in ("proceed", "approve", "go") or v.startswith("proceed"):
        return "proceed_with_conditions"
    if "insufficient" in v:
        return "hold_for_human"
    if "not" in v or "reject" in v or "no_go" in v:
        return "do_not_proceed"
    return "hold_for_human"


def external_available() -> bool:
    try:
        importlib.import_module("app.features.deliberation")
        return True
    except Exception:  # noqa: BLE001
        return False


def _external(detection: dict, proposal: dict) -> Optional[dict[str, Any]]:
    """Call the shared deliberation feature synchronously (we already run in a watchdog worker thread).

    Contract (apps/api/app/features/deliberation): ``deliberate.propose(ProposeRequest, client, persona,
    background=False) -> DeliberationSession`` with ``outcome.recommendation`` in {proceed_with_conditions,
    do_not_proceed, insufficient_evidence}. The watchdog proposal is sent as a CUSTOM intent (free text, no
    measurement deltas) with origin="watchdog"; a generic best-effort adapter is used if that API changes."""
    base = "app.features.deliberation"
    window = proposal.get("window") or {}
    persona = (proposal.get("responsible") or ["shift_supervisor"])[0]
    text = (f"[watchdog, SIMULATED auxiliaries] {proposal['intent']}. Evidence: {detection.get('rationale', '')}")[:500]
    payload: dict[str, Any] = {"custom": {"text": text, "deltas": {}}, "magnitude": proposal.get("magnitude"),
                               "persona": persona, "origin": "watchdog"}
    if window:
        payload.update({"year": window["source_year"], "start": window["start"], "end": window["end"]})
    try:
        D = importlib.import_module(f"{base}.deliberate")
        S = importlib.import_module(f"{base}.schemas")
        req = S.ProposeRequest.model_validate(payload)
        client = None
        try:
            from app import config, services
            if config.meta_configured():
                c = services.get_meta_client()
                client = c if getattr(c, "configured", False) else None
        except Exception:  # noqa: BLE001
            client = None
        session = _to_dict(D.propose(req, client, persona, background=False))
    except (ImportError, AttributeError):
        propose = _find([f"{base}.service", f"{base}.engine", base], ("propose", "create_proposal"))
        if propose is None:
            return None
        session = _to_dict(propose(payload))
    outcome = session.get("outcome") or {}
    status = str(session.get("status", ""))
    rec = normalise_recommendation(outcome.get("recommendation")) if outcome else "hold_for_human"
    if status != "completed":  # needs_review / failed never authorises anything
        rec = "hold_for_human" if rec == "proceed_with_conditions" else rec
    rid = session.get("deliberation_id") or session.get("id")
    answer = {"recommendation": rec,
              "summary": str(outcome.get("summary") or "Shared deliberation finished without a summary.")[:1500],
              "harms_elsewhere": [{"subsystem": "domino chain", "effect": str(x)[:600]}
                                  for x in (outcome.get("what_could_go_wrong") or [])[:8]],
              "conditions": [str(x)[:300] for x in (outcome.get("conditions") or [])[:10]],
              "who_must_approve": [str(x) for x in (outcome.get("who_must_approve") or [])[:6]]}
    hits = unsafe_hits([answer["summary"], *answer["conditions"], *(h["effect"] for h in answer["harms_elsewhere"])])
    if hits:  # belt and braces: the shared feature scans too
        answer["recommendation"] = "hold_for_human"
    return {"mode": "deliberation_module",
            "mode_label": f"shared deliberation feature ({session.get('mode_label') or session.get('mode')}; "
                          f"id {rid}; status {status}; original recommendation "
                          f"{outcome.get('recommendation') if outcome else 'none'})",
            "validated": not hits and status == "completed", "external_id": rid, "answer": answer,
            "errors": [*(session.get("validation_errors") or [])[:5], *hits]}


# --------------------------------------------------------------------------- entry point
SHARED_CLASSES_IN_AUTO = ("unit_commitment", "redispatch_request", "investigation_request", "auxiliary_maintenance",
                          "real_plant_action")


def choose_backend(backend: str, action_class: str) -> str:
    """Pick the deliberation path BEFORE seeing any answer (no opinion shopping).

    auto: plant-level classes go to the shared deliberation feature (when importable); the simulated auxiliary
          switchover uses the built-in auxiliaries-aware deliberation, because the shared feature's agents read only
          the UCI gas-turbine measurements, which contain no auxiliary-motor signals.
    builtin / shared: force one path (shared falls back to built-in if the package is missing)."""
    if backend == "builtin":
        return "builtin"
    if backend == "shared":
        return "shared" if external_available() else "builtin"
    return "shared" if action_class in SHARED_CLASSES_IN_AUTO and external_available() else "builtin"


def deliberate(detection: dict, proposal: dict, aux_summary: dict, client: Any = None,
               backend: str = "auto") -> dict[str, Any]:
    """Never raises. Returns {mode, mode_label, validated, answer{recommendation,...}, errors, ...}."""
    path = choose_backend(backend, proposal.get("action_class", ""))
    if path == "shared":
        try:
            res = _external(detection, proposal)
            if res is not None:
                return res
        except Exception as exc:  # noqa: BLE001 - e.g. capacity busy (429) -> built-in path, labelled
            log.info("shared deliberation unavailable (%s); using built-in", type(exc).__name__)
            fallback_note = f"shared deliberation unavailable ({type(exc).__name__}); built-in used"
            res = deliberate(detection, proposal, aux_summary, client, backend="builtin")
            res["mode_label"] = f"{res['mode_label']} — {fallback_note}"
            return res
    if client is None:
        try:
            from app import services
            client = services.get_meta_client()
        except Exception:  # noqa: BLE001
            client = None
    if client is None or not getattr(client, "configured", False):
        ans = offline_answer(detection, proposal)
        return {"mode": "offline_fallback", "mode_label": "offline (no Meta call) — deterministic rule",
                "validated": True, "answer": ans.model_dump(), "errors": [], "latency_ms": 0}
    return _builtin(detection, proposal, aux_summary, client)
