"""Advisory deliberation: "should we, or would it do more harm?" — parallel Muse Spark agents over pre-checks.

Flow (POST /api/deliberation/propose, background thread, at most MAX_CONCURRENT sessions -> else 429):
  1. intent -> modelled measurement deltas (``intents.build_change``)
  2. deterministic pre-checks -> numbered constraint findings with provenance (``prechecks.run_prechecks``)
  3. one Muse Spark agent per plant subsystem + one "constraints & safety" agent, IN PARALLEL; each returns
     {verdict: support|oppose|neutral|insufficient_evidence, confidence, reasons, harms, prerequisites}.
     Subsystem agents get one tool round (simulate_change / get_sensor_window via ``app.plant.whatif.PlantTools``,
     pre-bound to the window); the constraints agent reviews the findings only.
  4. one aggregator call -> recommendation, dissent, conditions, domino chain, who must approve. Consensus counts
     are computed deterministically from the verdicts, never by the model.
  5. every model-written field: pydantic + UNSAFE_PATTERNS (incl. grid patterns) + DATE_PATTERNS from the report
     validator; one rewrite; then a labelled deterministic fallback built from the pre-checks.
  6. optional rehearsal on ``app.simulator`` (guarded), then persist (table ``deliberations``).
The human decides (``record_decision``); ThermoMind executes nothing.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import ValidationError

from app.agent.report_validator import DATE_PATTERNS, UNSAFE_PATTERNS, extract_json
from app.features.deliberation import store
from app.features.deliberation.intents import MEAS_SUBSYSTEM, build_change
from app.features.deliberation.prechecks import STATUS_RANK, resolve_window, run_prechecks, worst_status
from app.features.deliberation.rehearsal import try_rehearsal
from app.features.deliberation.schemas import (DISCLAIMER, FALLBACK_LABEL, LIVE_LABEL, OFFLINE_LABEL, AgentVerdict,
                                               ConstraintFinding, Consensus, DeliberationSession, DelibAgentRun,
                                               Dissent, ModelledChange, Outcome, ProposeRequest)
from app.plant.personas import PERSONAS, resolve_persona
from app.plant.personas import label as persona_label
from app.plant.schemas import ASSOCIATION_LABEL
from app.plant.sensitivity import BaseWindow
from app.plant.subsystems import SUBSYSTEM_REGISTRY
from app.schemas import AgentEvent

log = logging.getLogger("thermomind.deliberation")

MAX_TOKENS = int(os.getenv("DELIB_MAX_TOKENS", "3000"))
RETRY_MAX_TOKENS = int(os.getenv("DELIB_RETRY_MAX_TOKENS", "6000"))  # one rewrite (e.g. after truncation)
AGGREGATOR_MAX_TOKENS = int(os.getenv("DELIB_AGGREGATOR_MAX_TOKENS", "8000"))  # reasoning tokens count too
AGENT_BUDGET_S = float(os.getenv("DELIB_AGENT_BUDGET_S", "150"))
MAX_TOOL_CALLS = 4
MAX_TOOL_CHARS = 9000
MAX_ITEMS = 6
MAX_ITEM_CHARS = 400
MAX_CONCURRENT = 2
CONSTRAINTS_AGENT = "constraints_safety"
SUPERVISOR_DEFAULT = "shift_supervisor"

_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT)
_POOL = ThreadPoolExecutor(max_workers=MAX_CONCURRENT * (len(SUBSYSTEM_REGISTRY) + 1),
                           thread_name_prefix="delib-agent")
BUSY_DETAIL = "deliberation capacity busy (2 running); retry shortly"


class DeliberationBusy(RuntimeError):
    """All deliberation slots are in use (API -> 429)."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# ----------------------------------------------------------------------------- live registry (for polling)
_LIVE: dict[str, DeliberationSession] = {}
_LOCK = threading.RLock()


def get_session(deliberation_id: str) -> DeliberationSession:
    with _LOCK:
        s = _LIVE.get(deliberation_id)
        if s is not None:
            return s.model_copy(deep=True)
    return store.get(deliberation_id)


def list_sessions(case_id: Optional[str] = None, limit: int = 20) -> list[DeliberationSession]:
    with _LOCK:
        live = [s.model_copy(deep=True) for s in _LIVE.values() if not case_id or s.case_id == case_id]
    ids = {s.deliberation_id for s in live}
    return (live + [s for s in store.list_(case_id, limit) if s.deliberation_id not in ids])[:limit]


# ----------------------------------------------------------------------------- safety scan
def scan_texts(texts: list[tuple[str, str]]) -> list[str]:
    """UNSAFE_PATTERNS (control + grid actions) and DATE_PATTERNS over model-written text."""
    errors = []
    for where, text in texts:
        for lbl, pat in UNSAFE_PATTERNS:
            if pat.search(text or ""):
                errors.append(f"unsafe_instruction: '{lbl}' pattern in {where}: phrase it as an observation, a "
                              f"condition or an option for people to evaluate, never as a command or control action")
                break
        for pat in DATE_PATTERNS:
            m = pat.search(text or "")
            if m:
                errors.append(f"fabricated_date: '{m.group(0)}' in {where}: the data has no timestamps")
                break
    return errors


def verdict_texts(v: AgentVerdict, where: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for f in ("reasons", "harms", "prerequisites"):
        out += [(f"{where}.{f}[{i}]", t) for i, t in enumerate(getattr(v, f))]
    return out


def outcome_texts(o: Outcome) -> list[tuple[str, str]]:
    out = [("summary", o.summary), ("rehearsal_suggestion", o.rehearsal_suggestion)]
    out += [(f"dissent[{i}].why", d.why) for i, d in enumerate(o.dissent)]
    out += [(f"conditions[{i}]", c) for i, c in enumerate(o.conditions)]
    out += [(f"what_could_go_wrong[{i}]", c) for i, c in enumerate(o.what_could_go_wrong)]
    return out


# ----------------------------------------------------------------------------- participants
def participants() -> list[dict[str, Any]]:
    subs = [dict(s, role="subsystem") for s in SUBSYSTEM_REGISTRY]
    subs.append({"key": CONSTRAINTS_AGENT, "name": "Constraints & safety reviewer", "role": "constraints",
                 "measurements": [], "owner_persona": "shift_supervisor",
                 "description": "Reviews the numbered deterministic constraint findings only."})
    return subs


RELEVANT_FINDINGS = {
    "intake": ("sensitivity_AFDP", "implied_range", "observability"),
    "compressor": ("sensitivity_CDP", "implied_range", "observability"),
    "combustion_turbine": ("sensitivity_TIT", "tit_envelope", "implied_range", "observability"),
    "exhaust_emissions": ("emissions", "observability"),
    "generator_output": ("sensitivity_TEY", "joint_model", "thermal_margins", "grid_headroom", "observability"),
}


def relevant(sub_key: str, findings: list[ConstraintFinding]) -> list[ConstraintFinding]:
    if sub_key == CONSTRAINTS_AGENT:
        return [f for f in findings if f.key != "basis"]
    keys = RELEVANT_FINDINGS.get(sub_key, ())
    return [f for f in findings if f.key in keys]


# ----------------------------------------------------------------------------- deterministic fallbacks
def _short(text: str, n: int = 260) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def fallback_verdict(sub: dict, change: ModelledChange, findings: list[ConstraintFinding]) -> AgentVerdict:
    """Conservative stand-in from the pre-checks: never 'support' without model reasoning."""
    rel = [f for f in relevant(sub["key"], findings) if f.status != "unavailable" or f.key == "observability"]
    cited = [f"finding #{f.n} {f.key}={f.status}" for f in rel]
    if not change.observable or not change.deltas:
        verdict, reasons = "insufficient_evidence", ["The proposed change is not observable in this data "
                                                     "(qualitative only); no number can be checked."]
    elif not rel:
        verdict, reasons = "insufficient_evidence", ["No pre-check covers this subsystem for the proposed change."]
    else:
        bad = [f for f in rel if STATUS_RANK[f.status] >= 2]
        verdict = "oppose" if bad else "neutral"
        reasons = [f"Finding #{f.n} ({f.title}) is '{f.status}': {_short(f.detail, 220)}" for f in (bad or rel)[:4]]
    harms = [f"Finding #{f.n}: {f.title} at status '{f.status}'." for f in rel if STATUS_RANK[f.status] >= 1][:4]
    prereq = ([f"Review finding #{f.n} ({f.title}) with {persona_label(sub['owner_persona'])} before any decision."
               for f in rel if STATUS_RANK[f.status] >= 1][:3]
              or [f"Confirm the {sub['name']} readings are valid (I&C check) before relying on the numbers."])
    return AgentVerdict(subsystem=sub["key"], verdict=verdict, confidence="low", reasons=reasons, harms=harms,
                        prerequisites=prereq, tool_numbers_cited=cited, owner_persona=sub["owner_persona"],
                        fallback=True)


def consensus(verdicts: list[AgentVerdict]) -> Consensus:
    c = Consensus()
    for v in verdicts:
        if v.verdict == "support":
            c.support += 1
        elif v.verdict == "oppose":
            c.oppose += 1
        elif v.verdict == "neutral":
            c.neutral += 1
        else:
            c.insufficient += 1
    return c


def _domino(change: ModelledChange, findings: list[ConstraintFinding]) -> list[str]:
    order = ["implied_range", "tit_envelope", "emissions", "thermal_margins", "grid_headroom", "joint_model"]
    by = {f.key: f for f in findings}
    chain = []
    for k in order:
        f = by.get(k)
        if f is not None and STATUS_RANK[f.status] >= 1:
            chain.append(f"Finding #{f.n} ({f.title}, {f.status}) — {_short(f.detail, 200)}")
    if any(d.measurement == "TIT" for d in change.deltas):
        chain.append("A hotter hot-gas path consumes component life faster (qualitative, not quantified by this "
                     "data); the OEM life model is not available here.")
    return chain or ["No pre-check flagged a knock-on effect; the domino chain cannot be quantified from this data."]


def approvers(change: ModelledChange, findings: list[ConstraintFinding]) -> list[str]:
    out = [SUPERVISOR_DEFAULT]
    for sub in SUBSYSTEM_REGISTRY:
        if sub["key"] in change.subsystems and sub["owner_persona"] not in out:
            out.append(sub["owner_persona"])
    st = {f.key: f.status for f in findings}
    if STATUS_RANK.get(st.get("emissions", "ok"), 0) >= 1 and "environmental_engineer" not in out:
        out.append("environmental_engineer")
    if any(STATUS_RANK.get(st.get(k, "ok"), 0) >= 1 for k in ("thermal_margins", "grid_headroom")) \
            and "electrical_engineer" not in out:
        out.append("electrical_engineer")
    if worst_status(findings) == "exceeds" and "plant_manager" not in out:
        out.append("plant_manager")
    return out


def fallback_outcome(change: ModelledChange, findings: list[ConstraintFinding],
                     verdicts: list[AgentVerdict]) -> Outcome:
    c = consensus(verdicts)
    worst = worst_status(findings)
    if not change.observable or not change.deltas or c.insufficient == len(verdicts):
        rec = "insufficient_evidence"
    elif worst == "exceeds" or c.oppose > c.support:
        rec = "do_not_proceed"
    else:
        rec = "proceed_with_conditions"
    flagged = [f for f in findings if STATUS_RANK[f.status] >= 1]
    conditions = [f"Finding #{f.n} ({f.title}, {f.status}) is reviewed and accepted by the responsible engineer "
                  f"before any decision." for f in flagged][:6]
    conditions.append("Any field work follows a permit to work and site procedures; the shift supervisor decides.")
    dissent = [Dissent(subsystem=v.subsystem, why=_short(v.reasons[0] if v.reasons else v.verdict, 300))
               for v in verdicts if (rec == "proceed_with_conditions" and v.verdict == "oppose")
               or (rec == "do_not_proceed" and v.verdict == "support")]
    summary = {"proceed_with_conditions": "No pre-check exceeds its envelope; the option could be considered "
                                          "only under the listed conditions.",
               "do_not_proceed": f"The pre-checks flag the proposed change (worst finding status '{worst}'); the "
                                 f"deterministic reading is that it would likely do more harm than good as modelled.",
               "insufficient_evidence": "The data cannot answer this question; a decision would rest on "
                                        "information outside ThermoMind."}[rec]
    return Outcome(recommendation=rec, summary=summary, consensus=c, dissent=dissent, conditions=conditions,
                   what_could_go_wrong=_domino(change, findings),
                   rehearsal_suggestion=("Rehearse the proposed change on a physics simulator (when available) and "
                                         "compare with the pre-checks before a human decision."),
                   who_must_approve=approvers(change, findings), source="deterministic_fallback",
                   source_label=FALLBACK_LABEL)


# ----------------------------------------------------------------------------- prompts
RULES = (
    "Rules: (1) Every number you write must come from the modelled change, the constraint findings or a tool result; "
    "cite them in tool_numbers_cited (e.g. 'finding #5 tit_envelope', 'simulate_change.model_effect.delta_tey_mean="
    "-0.02 MWh'). (2) Implied deltas are " + ASSOCIATION_LABEL + "; model effects are ceteris-paribus sensitivities "
    "of a statistical baseline (tree model, flat outside the training range), not physics. Thresholds are historical "
    "envelopes or screening levels, not OEM or permit limits. (3) If the data cannot tell, use verdict "
    "'insufficient_evidence'. (4) You are advising humans: write reasons, harms and prerequisites as observations, "
    "conditions or options for people to evaluate. Never write an instruction to operate the plant: no imperatives "
    "about output, load, firing, fuel, valves, vanes, setpoints, breakers, trips, shutdowns, bypasses or overrides. "
    "Refer to the change only as 'the proposed change'. Prerequisites are things to verify, confirm, inspect or "
    "review before a person decides. (5) No dates or clock times; rows are hourly samples without timestamps. "
    "(6) At most 4 items per list, each under 250 characters. Think briefly: your token budget is small and "
    "reasoning counts against it.\n"
)
VERDICT_SCHEMA = ('{"subsystem": "<key>", "verdict": "support|oppose|neutral|insufficient_evidence", '
                  '"confidence": "low|medium|high", "reasons": [str], "harms": [str], "prerequisites": [str], '
                  '"tool_numbers_cited": [str]}')


def agent_system_prompt(sub: dict) -> str:
    head = ("You are one participant in an ADVISORY deliberation inside ThermoMind, a READ-ONLY decision-support "
            "system for a gas turbine (UCI dataset 551: real hourly aggregates 2011-2015 from an undisclosed plant, "
            "no timestamps). An operator is CONSIDERING a change. Several agents judge independently whether it "
            "should be considered or would do more harm; a human decides; the software executes nothing.\n")
    if sub["role"] == "constraints":
        who = ("You are the CONSTRAINTS & SAFETY reviewer. Review ONLY the numbered deterministic constraint findings "
               "(you have no tools). Weigh statuses exceeds > concern > watch > ok, and say which findings would "
               "need to be resolved before a person could responsibly consider the proposed change.\n")
    else:
        who = (f"You are the {sub['name']} ({sub['key']}) agent. Your subsystem's measurements: "
               f"{', '.join(sub['measurements'])}; responsible persona: {persona_label(sub['owner_persona'])}. Judge "
               f"ONLY from your subsystem's point of view. You may call simulate_change (one measurement + delta, on "
               f"the real rows of the window) and get_sensor_window once to check numbers.\n")
    return head + who + RULES + "Final answer: ONE JSON object, no prose, no markdown: " + \
        VERDICT_SCHEMA.replace("<key>", sub["key"])


def _manifest(change: ModelledChange, base: BaseWindow, findings: list[ConstraintFinding], sub: dict) -> dict:
    return {
        "proposed_change": {"description": change.text, "observable_in_data": change.observable,
                            "deltas": [d.model_dump(exclude={"slope_of"}) for d in change.deltas],
                            "qualitative_notes": change.qualitative_notes, "slope_label": change.slope_label},
        "base_window": base.as_dict(),
        "constraint_findings": [{"n": f.n, "key": f.key, "title": f.title, "status": f.status,
                                 "provenance": f.provenance, "detail": f.detail}
                                for f in (relevant(sub["key"], findings) if sub["role"] == "subsystem" else findings)],
        "your_role": sub["key"],
    }


def agent_user_prompt(change: ModelledChange, base: BaseWindow, findings: list[ConstraintFinding], sub: dict) -> str:
    tail = ("\n\nIf useful, call simulate_change / get_sensor_window now; afterwards you will be asked for the JSON "
            "verdict." if sub["role"] == "subsystem" else "\n\nReturn your JSON verdict now.")
    return "DELIBERATION INPUT (JSON):\n" + json.dumps(_manifest(change, base, findings, sub), indent=1,
                                                         default=str) + tail


FINAL_TURN = ("Now return your verdict as ONE JSON object only (subsystem, verdict, confidence, reasons, harms, "
              "prerequisites, tool_numbers_cited). No prose, no markdown.")

AGGREGATOR_SYSTEM = (
    "You are the ThermoMind deliberation chair. Agents of a READ-ONLY gas-turbine decision-support system judged a "
    "change an operator is considering. Combine their verdicts and the deterministic constraint findings into advice "
    "for the HUMAN who decides. The software executes nothing.\n"
    "Return ONE JSON object only (no prose, no markdown) with keys:\n"
    " recommendation: 'proceed_with_conditions' | 'do_not_proceed' | 'insufficient_evidence';\n"
    " summary: str (2-3 sentences, why);\n"
    " dissent: [{subsystem, why}] — agents whose verdict disagrees with the recommendation;\n"
    " conditions: [str] — conditions that would have to hold before a person could consider the proposed change "
    "(phrased as conditions, e.g. 'TIT margin confirmed with the OEM ...', never as commands);\n"
    " what_could_go_wrong: [str] — the domino chain in order (first effect -> knock-on effects), citing finding "
    "numbers;\n"
    " rehearsal_suggestion: str — what a software rehearsal should look at;\n"
    " who_must_approve: [persona ids from: " + ", ".join(PERSONAS) + "].\n"
    + RULES +
    "The consensus counts are computed by software; do not restate different counts. Prefer 'do_not_proceed' when a "
    "finding is 'exceeds' and no condition can credibly resolve it; prefer 'insufficient_evidence' when the change is "
    "not observable in the data."
)


# ----------------------------------------------------------------------------- live agents
class _Recorder:
    def __init__(self, run: DelibAgentRun):
        self.run = run

    def add(self, kind: str, summary: str, **kw: Any) -> None:
        with _LOCK:
            self.run.events.append(AgentEvent(seq=len(self.run.events) + 1, ts_utc=_now(), kind=kind,
                                              summary=summary[:500], **kw))

    def tokens(self, usage: dict) -> dict[str, int]:
        step = {k: int(usage.get(k, 0) or 0) for k in ("prompt_tokens", "completion_tokens", "total_tokens",
                                                        "reasoning_tokens")}
        with _LOCK:
            for k, v in step.items():
                self.run.tokens[k] = self.run.tokens.get(k, 0) + v
        return step


def _chat(client: Any, rec: _Recorder, messages: list[dict], tools: Optional[list], label: str, max_tokens: int,
          json_mode: bool) -> Any:
    rec.add("model_request", f"{label}: {len(messages)} messages -> {getattr(client, 'model', '?')}")
    res = client.chat(messages, tools, max_tokens, response_format={"type": "json_object"} if json_mode else None)
    step = rec.tokens(res.usage or {})
    with _LOCK:
        rec.run.latency_ms += int(res.latency_ms or 0)
    rec.add("model_response", f"finish={res.finish_reason}; tool_calls={len(res.message.get('tool_calls') or [])}; "
                              f"content_chars={len(res.message.get('content') or '')}",
            latency_ms=res.latency_ms, tokens=step)
    if res.message.get("content") or res.message.get("tool_calls"):
        messages.append(res.message)
    return res


def _clean_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, list):
        return [str(v)[:MAX_ITEM_CHARS]]
    return [str(x).strip()[:MAX_ITEM_CHARS] for x in v if str(x).strip()][:MAX_ITEMS]


def validate_verdict(content: str, sub: dict) -> tuple[Optional[AgentVerdict], list[str]]:
    data = extract_json(content) if content else None
    if data is None:
        return None, ["response is not a JSON object"]
    data = dict(data)
    for k in ("reasons", "harms", "prerequisites", "tool_numbers_cited"):
        data[k] = _clean_list(data.get(k))
    if isinstance(data.get("verdict"), str):
        data["verdict"] = data["verdict"].strip().lower().replace(" ", "_")
        if data["verdict"] == "insufficient":
            data["verdict"] = "insufficient_evidence"
    if isinstance(data.get("confidence"), str):
        data["confidence"] = data["confidence"].strip().lower()
    data.update(subsystem=sub["key"], owner_persona=sub["owner_persona"], fallback=False)
    try:
        v = AgentVerdict.model_validate(data)
    except ValidationError as exc:
        return None, [f"schema: {'.'.join(str(p) for p in e.get('loc', ()))}: {e.get('msg')}" for e in exc.errors()]
    errs = [] if v.reasons else ["reasons must not be empty"]
    errs += scan_texts(verdict_texts(v, sub["key"]))
    return (v if not errs else None), errs


def run_agent(client: Any, sub: dict, change: ModelledChange, base: BaseWindow, findings: list[ConstraintFinding],
              tools: Any, run: DelibAgentRun) -> None:
    rec = _Recorder(run)
    with _LOCK:
        run.status = "running"
    specs = None
    if sub["role"] == "subsystem" and tools is not None:
        from app.plant.whatif import tool_specs

        specs = [t for t in tool_specs(list(MEAS_SUBSYSTEM)) if t["function"]["name"] != "lookup_reference"]
    messages = [{"role": "system", "content": agent_system_prompt(sub)},
                {"role": "user", "content": agent_user_prompt(change, base, findings, sub)}]
    try:
        res = _chat(client, rec, messages, specs, "round 1" + (" (tools)" if specs else " (answer)"), MAX_TOKENS,
                    specs is None)
        calls = res.message.get("tool_calls") or []
        content = res.message.get("content") or ""
        if calls and specs:
            for tc in calls[:MAX_TOOL_CALLS]:
                fn = tc.get("function") or {}
                name = fn.get("name") or "?"
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                    if not isinstance(args, dict):
                        raise ValueError("arguments must be a JSON object")
                    if name not in ("simulate_change", "get_sensor_window"):
                        raise ValueError(f"unknown tool '{name}'")
                    result = tools.run(name, args)
                    with _LOCK:
                        run.used_tools = True
                    rec.add("tool_call", f"{name}({json.dumps(args, default=str)[:160]})", tool_name=name, args=args)
                    me = result.get("model_effect", {}) if name == "simulate_change" else {}
                    rec.add("tool_result", (f"ΔTEY mean={me.get('delta_tey_mean')} MWh; in_range="
                                            f"{result.get('train_range_check', {}).get('within_training_range')}")
                            if name == "simulate_change" else "ok", tool_name=name)
                    payload = json.dumps(result, default=str)[:MAX_TOOL_CHARS]
                except Exception as exc:  # noqa: BLE001 - tool errors go back to the model
                    rec.add("tool_call", f"{name}: rejected ({str(exc)[:200]})", tool_name=name, ok=False)
                    payload = json.dumps({"error": str(exc)[:300]})
                messages.append({"role": "tool", "tool_call_id": tc.get("id") or "call", "content": payload})
            messages.append({"role": "user", "content": FINAL_TURN})
            res = _chat(client, rec, messages, None, "round 2 (answer)", MAX_TOKENS, True)
            content = res.message.get("content") or ""
        elif specs and not content:
            messages.append({"role": "user", "content": FINAL_TURN})
            res = _chat(client, rec, messages, None, "round 2 (answer)", MAX_TOKENS, True)
            content = res.message.get("content") or ""
        verdict, errs = validate_verdict(content, sub)
        if verdict is None:
            truncated = res.finish_reason == "length"
            rec.add("rewrite_requested", ("truncated (token limit); " if truncated else "") + " | ".join(errs)[:400])
            messages.append({"role": "user", "content": ("Your previous answer was cut off by the token limit. "
                                                         "Answer briefly. " if truncated else "") +
                             "Your previous answer was rejected:\n" +
                             "\n".join(f"- {e}" for e in errs) + "\n" + FINAL_TURN})
            res = _chat(client, rec, messages, None, "rewrite", RETRY_MAX_TOKENS, True)
            verdict, errs = validate_verdict(res.message.get("content") or "", sub)
        rec.add("validation", "verdict accepted" if verdict else f"rejected after rewrite: {len(errs)} error(s)",
                ok=verdict is not None)
        if verdict is None:
            verdict = fallback_verdict(sub, change, findings)
            rec.add("fallback", "deterministic stand-in verdict from the pre-checks (labelled)", ok=False)
        with _LOCK:
            run.verdict = verdict
            run.ok = not verdict.fallback
            run.error = None if run.ok else "; ".join(errs)[:400]
            run.status = "done" if run.ok else "failed"
    except Exception as exc:  # noqa: BLE001 - MetaClientError is already redacted
        msg = str(exc)[:300] if type(exc).__name__ == "MetaClientError" else f"agent error ({type(exc).__name__})"
        rec.add("error", msg, ok=False)
        rec.add("fallback", "deterministic stand-in verdict from the pre-checks (labelled)", ok=False)
        with _LOCK:
            run.ok, run.error, run.status = False, msg, "failed"
            run.verdict = fallback_verdict(sub, change, findings)


def validate_outcome(content: str, change: ModelledChange, findings: list[ConstraintFinding],
                     verdicts: list[AgentVerdict]) -> tuple[Optional[Outcome], list[str]]:
    data = extract_json(content) if content else None
    if data is None:
        return None, ["response is not a JSON object"]
    known = {v.subsystem for v in verdicts}
    try:
        rec = str(data.get("recommendation") or "").strip().lower()
        dissent = []
        for d in (data.get("dissent") or [])[:MAX_ITEMS]:
            if isinstance(d, dict) and d.get("subsystem") in known and str(d.get("why") or "").strip():
                dissent.append(Dissent(subsystem=d["subsystem"], why=str(d["why"])[:MAX_ITEM_CHARS]))
        approve = [p for p in _clean_list(data.get("who_must_approve")) if p in PERSONAS]
        out = Outcome(recommendation=rec, summary=str(data.get("summary") or "")[:900],
                      consensus=consensus(verdicts), dissent=dissent,
                      conditions=_clean_list(data.get("conditions")),
                      what_could_go_wrong=_clean_list(data.get("what_could_go_wrong")),
                      rehearsal_suggestion=str(data.get("rehearsal_suggestion") or "")[:600],
                      who_must_approve=approve, source="model", disclaimer=DISCLAIMER,
                      source_label="Muse Spark aggregator over the agents' verdicts and the pre-checks")
    except (ValidationError, TypeError, AttributeError) as exc:
        return None, [f"schema: {str(exc)[:300]}"]
    errs = []
    if not out.summary:
        errs.append("summary must not be empty")
    if out.recommendation == "proceed_with_conditions" and not out.conditions:
        errs.append("proceed_with_conditions needs at least one condition")
    if not out.what_could_go_wrong:
        errs.append("what_could_go_wrong must not be empty (say what cannot be quantified if unsure)")
    errs += scan_texts(outcome_texts(out))
    return (out if not errs else None), errs


def apply_guards(out: Outcome, change: ModelledChange, findings: list[ConstraintFinding]) -> Outcome:
    """Deterministic guard rails on the aggregator's outcome (recorded in guard_notes)."""
    notes = list(out.guard_notes)
    rec = out.recommendation
    if (not change.observable or not change.deltas) and rec != "insufficient_evidence":
        notes.append(f"Recommendation '{rec}' replaced by 'insufficient_evidence': the change is not observable in "
                     f"this data.")
        rec = "insufficient_evidence"
    exceeded = [f for f in findings if f.status == "exceeds"]
    if exceeded and rec == "proceed_with_conditions":
        notes.append("Pre-check(s) " + ", ".join(f"#{f.n} {f.key}" for f in exceeded) + " exceed the historical "
                     "envelope; the aggregator still proposed conditions — the human should weigh this explicitly.")
    approve = list(dict.fromkeys([SUPERVISOR_DEFAULT, *out.who_must_approve,
                                  *[p for p in approvers(change, findings) if p != SUPERVISOR_DEFAULT]]))
    return out.model_copy(update={"recommendation": rec, "guard_notes": notes, "who_must_approve": approve,
                                  "disclaimer": DISCLAIMER})


def run_aggregator(client: Any, change: ModelledChange, findings: list[ConstraintFinding],
                   verdicts: list[AgentVerdict], run: DelibAgentRun) -> tuple[Optional[Outcome], list[str]]:
    rec = _Recorder(run)
    with _LOCK:
        run.status = "running"
    payload = {
        "proposed_change": {"description": change.text, "observable_in_data": change.observable,
                            "deltas": [d.model_dump(include={"measurement", "delta", "unit", "role", "provenance",
                                                             "pearson_r"}) for d in change.deltas],
                            "qualitative_notes": change.qualitative_notes},
        "constraint_findings": [{"n": f.n, "key": f.key, "status": f.status, "provenance": f.provenance,
                                 "detail": _short(f.detail, 320)} for f in findings if f.key != "basis"],
        "verdicts": [{"subsystem": v.subsystem, "verdict": v.verdict, "confidence": v.confidence,
                      "deterministic_stand_in": v.fallback, "reasons": [_short(x, 220) for x in v.reasons[:3]],
                      "harms": [_short(x, 220) for x in v.harms[:3]],
                      "prerequisites": [_short(x, 200) for x in v.prerequisites[:3]]} for v in verdicts],
        "consensus_computed_by_software": consensus(verdicts).model_dump(),
    }
    messages = [{"role": "system", "content": AGGREGATOR_SYSTEM},
                {"role": "user", "content": "INPUT (JSON):\n" + json.dumps(payload, indent=1, default=str)}]
    try:
        res = _chat(client, rec, messages, None, "aggregate", AGGREGATOR_MAX_TOKENS, True)
        out, errs = validate_outcome(res.message.get("content") or "", change, findings, verdicts)
        if out is None:
            truncated = res.finish_reason == "length"
            rec.add("rewrite_requested", ("truncated (token limit); " if truncated else "") + " | ".join(errs)[:400])
            messages.append({"role": "user", "content": ("Your previous answer was cut off by the token limit; "
                                                         "think briefly. " if truncated else "") +
                             "Your previous answer was rejected:\n" +
                             "\n".join(f"- {e}" for e in errs) + "\nReturn the corrected JSON object only."})
            res = _chat(client, rec, messages, None, "aggregate rewrite", AGGREGATOR_MAX_TOKENS, True)
            out, errs = validate_outcome(res.message.get("content") or "", change, findings, verdicts)
        rec.add("validation", "outcome accepted" if out else f"rejected after rewrite: {len(errs)} error(s)",
                ok=out is not None)
        with _LOCK:
            run.ok, run.error = out is not None, (None if out else "; ".join(errs)[:400])
            run.status = "done" if out else "failed"
        return out, errs
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)[:300] if type(exc).__name__ == "MetaClientError" else f"aggregator error ({type(exc).__name__})"
        rec.add("error", msg, ok=False)
        with _LOCK:
            run.ok, run.error, run.status = False, msg, "failed"
        return None, [msg]


# ----------------------------------------------------------------------------- entry points
def prepare(req: ProposeRequest, persona: Optional[str], client: Any) -> tuple[DeliberationSession, BaseWindow]:
    """Validates input (ValueError -> 422, KeyError -> 404) and builds the modelled change. Cheap."""
    pid = resolve_persona(req.persona or persona).persona_id
    base = resolve_window(req)
    change = build_change(req.intent_id, req.magnitude, req.custom, dataset_id=base.dataset_id)
    live = client is not None and getattr(client, "configured", False)
    session = DeliberationSession(
        deliberation_id=f"dl_{secrets.token_hex(6)}", created_at_utc=_now(), status="running", persona=pid,
        request=req.model_copy(update={"persona": pid}), case_id=base.case_id, base_window=base.as_dict(),
        change=change, mode="meta_live" if live else "offline", mode_label=LIVE_LABEL if live else OFFLINE_LABEL)
    return session, base


def execute(session: DeliberationSession, base: BaseWindow, client: Any) -> DeliberationSession:
    t0 = time.perf_counter()
    with _LOCK:
        _LIVE[session.deliberation_id] = session
    try:
        change = session.change
        findings = run_prechecks(change, base)
        parts = participants()
        with _LOCK:
            session.constraint_findings = findings
            session.agents = [DelibAgentRun(agent=p["key"], role=p["role"], name=p["name"]) for p in parts]
        runs = {r.agent: r for r in session.agents}
        if session.mode == "offline":
            verdicts = [fallback_verdict(p, change, findings) for p in parts]
            with _LOCK:
                for p, v in zip(parts, verdicts):
                    runs[p["key"]].verdict, runs[p["key"]].status = v, "done"
                    runs[p["key"]].events.append(AgentEvent(seq=1, ts_utc=_now(), kind="fallback", summary=(
                        "offline (no Meta call): deterministic stand-in verdict from the pre-checks")))
                session.outcome = fallback_outcome(change, findings, verdicts)
        else:
            from app.plant.whatif import PlantTools

            tools = PlantTools(base)
            futures = [_POOL.submit(run_agent, client, p, change, base, findings, tools, runs[p["key"]]) for p in parts]
            _, pending = wait(futures, timeout=AGENT_BUDGET_S)
            for f in pending:
                f.cancel()
            verdicts = []
            with _LOCK:
                for p in parts:
                    r = runs[p["key"]]
                    if r.verdict is None:
                        r.verdict = fallback_verdict(p, change, findings)
                        r.ok, r.status = False, "failed"
                        r.error = r.error or f"timed out after {AGENT_BUDGET_S:.0f}s budget; deterministic stand-in"
                    verdicts.append(r.verdict)
            n_ok = sum(1 for r in runs.values() if r.ok)
            agg = DelibAgentRun(agent="aggregator", role="aggregator", name="Deliberation chair (aggregator)")
            with _LOCK:
                session.agents.append(agg)
            out, errs = (run_aggregator(client, change, findings, verdicts, agg) if n_ok else
                         (None, ["no agent returned a valid verdict"]))
            with _LOCK:
                session.meta_model = getattr(client, "model", None)
                session.validation_errors = [f"{r.agent}: {r.error}" for r in runs.values() if r.error]
                if out is None:
                    session.validation_errors += [f"aggregator: {e}" for e in errs]
                    out = fallback_outcome(change, findings, verdicts)
                    session.status = "needs_review"
                session.outcome = apply_guards(out, change, findings)
        rehearsal = try_rehearsal(change)
        with _LOCK:
            if session.mode == "offline":
                session.outcome = apply_guards(session.outcome, change, findings)
            session.rehearsal = rehearsal
            if session.status == "running":
                session.status = "completed"
    except Exception as exc:  # noqa: BLE001
        log.exception("deliberation %s failed", session.deliberation_id)
        with _LOCK:
            session.status, session.error = "failed", f"deliberation failed ({type(exc).__name__})"
    finally:
        with _LOCK:
            session.completed_at_utc = _now()
            session.wall_ms = int((time.perf_counter() - t0) * 1000)
            final = session.model_copy(deep=True)
        try:
            store.save(final)
        finally:
            with _LOCK:
                _LIVE.pop(session.deliberation_id, None)
    return final


def propose(req: ProposeRequest, client: Any, persona: Optional[str] = None,
            background: bool = True) -> DeliberationSession:
    session, base = prepare(req, persona, client)
    if not _SLOTS.acquire(blocking=False):
        raise DeliberationBusy(BUSY_DETAIL)

    def _run() -> DeliberationSession:
        try:
            return execute(session, base, client)
        finally:
            _SLOTS.release()

    if not background:
        return _run()
    snapshot = session.model_copy(deep=True)
    with _LOCK:
        _LIVE[session.deliberation_id] = session  # visible to GET before the thread starts
    try:
        threading.Thread(target=_run, daemon=True, name=f"delib-{session.deliberation_id}").start()
    except BaseException:
        with _LOCK:
            _LIVE.pop(session.deliberation_id, None)
        _SLOTS.release()
        raise
    return snapshot
