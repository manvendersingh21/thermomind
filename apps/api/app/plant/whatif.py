""""Ask the plant": parallel per-subsystem Muse Spark agents + one aggregator, over deterministic tools.

Flow: deterministic ``simulate_change`` preview -> N subsystem agents IN PARALLEL (each: one tool round with
simulate_change / get_sensor_window / lookup_reference, then a JSON-only answer) -> one aggregator call that
writes "what your test could affect elsewhere" + "recommended fix / next steps" -> validation (pydantic +
the report validator's UNSAFE_PATTERNS / DATE_PATTERNS) with one bounded rewrite -> persisted session.
"How this part works" and the change spec are filled deterministically from the registry / tools.

Offline (no key): deterministic sensitivity only, labelled "offline (no Meta call)". Read-only throughout.
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
from types import SimpleNamespace
from typing import Any, Callable, Optional

from pydantic import ValidationError

from app.agent.report_validator import DATE_PATTERNS, UNSAFE_PATTERNS, extract_json
from app.plant import store
from app.plant.personas import label as persona_label
from app.plant.personas import resolve_persona
from app.plant.schemas import (ASSOCIATION_LABEL, HOW_IT_WORKS_SOURCE, NEXT_STEPS_NOTE, WHATIF_DISCLAIMER,
                               AgentRun, ChangeSpec, CrossImpact, EffectElsewhere, HowItWorks, NextStep,
                               SubsystemAssessment, WhatIfAnswer, WhatIfRequest, WhatIfSession)
from app.plant.sensitivity import BaseWindow, resolve_base, simulate_change
from app.plant.subsystems import SUBSYSTEM_REGISTRY
from app.schemas import MEASUREMENTS, AgentEvent

log = logging.getLogger("thermomind.plant.whatif")

MAX_TOKENS = int(os.getenv("PLANT_MAX_TOKENS", "3000"))
RETRY_MAX_TOKENS = int(os.getenv("PLANT_RETRY_MAX_TOKENS", "5000"))
AGGREGATOR_MAX_TOKENS = int(os.getenv("PLANT_AGGREGATOR_MAX_TOKENS", "5000"))  # reasoning tokens count too
AGENT_BUDGET_S = float(os.getenv("PLANT_AGENT_BUDGET_S", "55"))
MAX_TOOL_ROUNDS = 2
OFFLINE_LABEL = "offline (no Meta call)"
LIVE_LABEL = "meta_live (Muse Spark subsystem agents + aggregator over deterministic tools)"
MAX_TOOL_CHARS = 12000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# ----------------------------------------------------------------------------- live session registry
_LIVE: dict[str, WhatIfSession] = {}
_LIVE_LOCK = threading.RLock()


def get_live(session_id: str) -> Optional[WhatIfSession]:
    with _LIVE_LOCK:
        s = _LIVE.get(session_id)
        return s.model_copy(deep=True) if s is not None else None


def get_session(session_id: str) -> WhatIfSession:
    live = get_live(session_id)
    return live if live is not None else store.get_session(session_id)


# ----------------------------------------------------------------------------- safety scan
def scan_texts(texts: list[tuple[str, str]]) -> list[str]:
    errors = []
    for where, text in texts:
        for lbl, pat in UNSAFE_PATTERNS:
            if pat.search(text or ""):
                errors.append(f"unsafe_instruction: '{lbl}' pattern found in {where}: control actions are forbidden; "
                              f"rephrase as an inspection / verification step requiring supervisor approval")
                break
        for pat in DATE_PATTERNS:
            m = pat.search(text or "")
            if m:
                errors.append(f"fabricated_date: '{m.group(0)}' in {where}: the data has no timestamps")
                break
    return errors


def _assessment_texts(a: SubsystemAssessment, where: str) -> list[tuple[str, str]]:
    out = [(f"{where}.impact_summary", a.impact_summary), (f"{where}.magnitude_hint", a.magnitude_hint)]
    out += [(f"{where}.caveats[{i}]", c) for i, c in enumerate(a.caveats)]
    return out


def answer_texts(ans: WhatIfAnswer) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for i, a in enumerate(ans.subsystem_assessments):
        out += _assessment_texts(a, f"subsystem_assessments[{i}]")
    for i, e in enumerate(ans.effects_elsewhere):
        out += [(f"effects_elsewhere[{i}].description", e.description),
                (f"effects_elsewhere[{i}].magnitude_hint", e.magnitude_hint)]
    for i, s in enumerate(ans.recommended_next_steps):
        out += [(f"recommended_next_steps[{i}].action", s.action), (f"recommended_next_steps[{i}].rationale", s.rationale)]
    out += [(f"cross_impacts[{i}]", c.description) for i, c in enumerate(ans.cross_impacts)]
    out += [(f"what_to_check_before_acting[{i}]", c) for i, c in enumerate(ans.what_to_check_before_acting)]
    return out


# ----------------------------------------------------------------------------- tools for subsystem agents
REFERENCE_TOPICS = ["intake_filter_fouling", "compressor_discharge_pressure", "sensor_validation", "ambient_effects"]


def tool_specs(meas_keys: list[str]) -> list[dict]:
    return [
        {"type": "function", "function": {
            "name": "simulate_change",
            "description": ("Deterministic what-if on the pre-bound base window (real rows): shift ONE measurement by "
                            "delta, re-run the production baseline model (expected TEY, MWh) and report the model "
                            "effect, a training-range (OOD) check, and historical co-movement of every other "
                            "measurement (" + ASSOCIATION_LABEL + ")."),
            "parameters": {"type": "object", "properties": {
                "measurement": {"type": "string", "enum": meas_keys},
                "delta": {"type": "number", "description": "Change in the measurement's published unit."}},
                "required": ["measurement", "delta"]}}},
        {"type": "function", "function": {
            "name": "get_sensor_window",
            "description": ("Summary statistics for measurements over a row range of the base window or its "
                            "240-row real reference before it. Rows are hourly samples without timestamps."),
            "parameters": {"type": "object", "properties": {
                "measurements": {"type": "array", "items": {"type": "string", "enum": meas_keys}},
                "start_index": {"type": "integer"}, "end_index": {"type": "integer"}},
                "required": ["measurements", "start_index", "end_index"]}}},
        {"type": "function", "function": {
            "name": "lookup_reference",
            "description": "Short bundled generic engineering background notes (not plant-specific).",
            "parameters": {"type": "object", "properties": {"topic": {"type": "string", "enum": REFERENCE_TOPICS}},
                           "required": ["topic"]}}},
    ]


class PlantTools:
    """Dispatches the subsystem agents' tools. simulate_change is pre-bound to the base window."""

    def __init__(self, base: BaseWindow, model: Any = None):
        self.base = base
        self.model = model
        self._runner = None
        self._runner_error: Optional[str] = None

    def _tool_runner(self) -> Any:
        if self._runner is not None or self._runner_error:
            return self._runner
        try:
            from app import services
            from app.agent.tools import ToolRunner
            from app.schemas import SampleRange

            b = self.base
            bundle = services.get_repo().get(b.dataset_id)
            ref_start = max(0, b.start - 240)
            window_frame = bundle.window(b.year, b.start, b.end)
            scenario = SimpleNamespace(synthetic=False, affected_measurements=[])
            if b.case_id:  # reproduce the case's labelled overlay so get_sensor_window matches the case
                inv = services.get_store().get(b.case_id)
                from app.analytics.scenarios import apply_scenario

                res = apply_scenario(window_frame, inv.request.scenario_id, inv.request.seed
                                     if inv.request.seed is not None else inv.scenario.default_seed)
                window_frame, scenario = res.frame, res
            analysis = SimpleNamespace(
                case_id=b.case_id or "whatif_default_window",
                window=SampleRange(source_year=b.year, start=b.start, end=b.end),
                reference=SampleRange(source_year=b.year, start=ref_start, end=b.start),
                window_frame=window_frame, reference_frame=bundle.window(b.year, ref_start, b.start),
                scenario=scenario, evidence=[], data_quality=None, baseline=None, hypothesis_evals={})
            self._runner = ToolRunner(analysis)
        except Exception as exc:  # noqa: BLE001
            self._runner_error = f"sensor window unavailable ({type(exc).__name__})"
        return self._runner

    def run(self, name: str, args: dict) -> dict:
        if name == "simulate_change":
            extra = set(args) - {"measurement", "delta"}
            if extra:
                raise ValueError(f"unexpected arguments {sorted(extra)}")
            return simulate_change(args.get("measurement"), args.get("delta"), self.base, self.model)
        if name in ("get_sensor_window", "lookup_reference"):
            runner = self._tool_runner()
            if runner is None:
                raise ValueError(self._runner_error or "tool unavailable")
            return runner.run(name, args)[0]
        raise ValueError(f"unknown tool '{name}'")


# ----------------------------------------------------------------------------- prompts
def agent_system_prompt(sub: dict) -> str:
    return (
        f"You are the {sub['name']} ({sub['key']}) agent of ThermoMind, a READ-ONLY decision-support system for a "
        f"gas turbine (UCI dataset 551: real hourly aggregates 2011-2015 from an undisclosed plant, no timestamps). "
        f"Your subsystem's measurements: {', '.join(sub['measurements'])}. Responsible persona: "
        f"{persona_label(sub['owner_persona'])}.\n"
        "A technician asks what would happen if a measurement changed. Answer ONLY about impacts on YOUR subsystem.\n"
        "Rules: (1) First call simulate_change (and get_sensor_window if useful); every number must come from a tool "
        "result — cite them in tool_numbers_cited like 'simulate_change.model_effect.delta_tey_mean=-0.12 MWh' or "
        "'co_movement CDP r=0.67'. (2) Model effects are MODEL-DERIVED sensitivities of a statistical baseline "
        "(ceteris paribus); co-movement is " + ASSOCIATION_LABEL + ". Say so. (3) If the tools cannot tell, say "
        "'cannot tell from available data' and use direction 'unknown' and confidence 'low'. (4) No control "
        "recommendations: never propose setpoint changes, valve operations, trips, shutdowns, fuel adjustments, "
        "bypasses, overrides or commands. (5) No dates; units as published (TEY MWh, CDP 'mbar' under validation).\n"
        "Final answer: ONE JSON object, no prose, no markdown: {\"subsystem\": \"" + sub["key"] + "\", "
        "\"impact_summary\": str (1-3 sentences), \"direction\": \"increase|decrease|no_clear_change|mixed|unknown\", "
        "\"magnitude_hint\": str, \"confidence\": \"low|medium|high\", \"caveats\": [str], "
        "\"tool_numbers_cited\": [str]}"
    )


def agent_user_prompt(req: WhatIfRequest, base: BaseWindow, unit: str, sub: dict) -> str:
    manifest = {"question": req.question or f"What if {req.measurement} changes by {req.delta:+g} {unit}?",
                "change": {"measurement": req.measurement, "delta": req.delta, "unit": unit},
                "base_window": base.as_dict(), "your_subsystem": sub["key"],
                "your_measurements": sub["measurements"],
                "reference_rows_available": [max(0, base.start - 240), base.start]}
    return ("WHAT-IF REQUEST (JSON):\n" + json.dumps(manifest, indent=1) +
            "\n\nCall simulate_change for this change now (you may also call get_sensor_window for your "
            "measurements). After the tool results you will be asked for the JSON answer.")


FINAL_TURN = ("Now return your assessment as ONE JSON object only (subsystem, impact_summary, direction, "
              "magnitude_hint, confidence, caveats, tool_numbers_cited). No prose, no markdown.")

AGGREGATOR_SYSTEM = (
    "You are the ThermoMind aggregator. Several subsystem agents of a READ-ONLY gas-turbine decision-support system "
    "assessed a technician's what-if question using deterministic tools. Combine them for a technician who works in "
    "ONE area and cannot see the whole plant.\n"
    "Return ONE JSON object only (no prose, no markdown) with keys:\n"
    " effects_elsewhere: [{subsystem, description, direction (increase|decrease|no_clear_change|mixed|unknown), "
    "magnitude_hint, confidence (low|medium|high), tool_numbers_cited: [str], basis ('model sensitivity' | "
    "'historical association' | 'generic background')}] — what the tested change could affect in OTHER subsystems;\n"
    " recommended_next_steps: [{action, kind (inspect|verify|calibrate|schedule|isolate_per_procedure|collect_data|"
    "review), subsystem, rationale}] — maintenance / diagnostic steps only, each requiring supervisor approval and "
    "site procedures (inspect, verify, calibrate, schedule, isolation per procedure);\n"
    " cross_impacts: [{subsystems: [str], description, basis}];\n"
    " what_to_check_before_acting: [str].\n"
    "Rules: use only numbers present in the input; association is not causation; the model effect is a ceteris "
    "paribus sensitivity of a statistical baseline, not physics; never propose control actions (no setpoint "
    "changes, valve operations, trips, shutdowns, fuel adjustments, bypasses, overrides, commands); no dates; "
    "say when agents could not tell."
)


# ----------------------------------------------------------------------------- deterministic builders
def _owner(sub: dict) -> tuple[str, str]:
    return sub["owner_persona"], f"owner: {persona_label(sub['owner_persona'])}"


def how_it_works(measurement: str) -> list[HowItWorks]:
    subs = sorted(SUBSYSTEM_REGISTRY, key=lambda s: measurement not in s["measurements"])
    return [HowItWorks(subsystem=s["key"], name=s["name"], explanation=s.get("how_it_works") or s["description"],
                       source=HOW_IT_WORKS_SOURCE) for s in subs]


def _co_items(sens: dict, min_r: float = 0.3) -> list[dict]:
    return [i for i in sens["co_movement"]["items"] if i["pearson_r"] is not None and abs(i["pearson_r"]) >= min_r]


def offline_assessment(sub: dict, sens: dict) -> SubsystemAssessment:
    m, unit = sens["measurement"], sens["unit"]
    me = sens["model_effect"]
    items = {i["measurement"]: i for i in sens["co_movement"]["items"]}
    parts, cited, direction = [], [], "unknown"
    if m in sub["measurements"]:
        parts.append(f"{m} is measured in this subsystem; the what-if shifts it by {sens['delta']:+g} {unit}.")
    if "TEY" in sub["measurements"] and me.get("applicable"):
        d = me["delta_tey_mean"]
        rel = abs(me.get("delta_tey_pct_of_base") or 0)
        direction = "no_clear_change" if rel < 0.1 else ("increase" if d > 0 else "decrease")
        parts.append(f"Model-derived expected TEY changes by {d:+.3f} MWh on average "
                     f"(row range {me['delta_tey_min']:+.3f}..{me['delta_tey_max']:+.3f}).")
        cited.append(f"simulate_change.model_effect.delta_tey_mean={d} MWh")
    assoc = [items[k] for k in sub["measurements"] if k in items and items[k]["pearson_r"] is not None
             and abs(items[k]["pearson_r"]) >= 0.3]
    for i in assoc:
        parts.append(f"Historically {i['measurement']} moved {i['implied_change_for_delta']:+.3g} {i['unit']} per "
                     f"{sens['delta']:+g} {unit} of {m} (r={i['pearson_r']:+.2f}; association, not causation).")
        cited.append(f"co_movement {i['measurement']} r={i['pearson_r']} slope={i['slope_per_unit']}")
    if not parts:
        parts.append("Cannot tell from available data: no model effect and no notable historical association "
                     "(|r| >= 0.3) for this subsystem's measurements.")
    owner, owner_lbl = _owner(sub)
    return SubsystemAssessment(
        subsystem=sub["key"], owner_persona=owner, owner_label=owner_lbl, impact_summary=" ".join(parts)[:900],
        direction=direction, magnitude_hint=(cited[0] if cited else "n/a"), confidence="low",
        caveats=["Offline deterministic summary; no Meta model reasoning applied.", ASSOCIATION_LABEL],
        tool_numbers_cited=cited)


def offline_effects(sens: dict) -> list[EffectElsewhere]:
    m, unit = sens["measurement"], sens["unit"]
    out = []
    for sub in SUBSYSTEM_REGISTRY:
        if m in sub["measurements"]:
            continue
        for i in _co_items(sens):
            if i["measurement"] in sub["measurements"]:
                out.append(EffectElsewhere(
                    subsystem=sub["key"],
                    description=(f"{i['measurement']} historically moved {i['implied_change_for_delta']:+.3g} {i['unit']} "
                                 f"per {sens['delta']:+g} {unit} of {m} (r={i['pearson_r']:+.2f})."),
                    direction="increase" if (i["implied_change_for_delta"] or 0) > 0 else "decrease",
                    magnitude_hint=f"{i['implied_change_for_delta']:+.3g} {i['unit']}", confidence="low",
                    tool_numbers_cited=[f"co_movement {i['measurement']} r={i['pearson_r']}"],
                    basis="historical association"))
    me = sens["model_effect"]
    if me.get("applicable"):
        out.insert(0, EffectElsewhere(
            subsystem="generator_output",
            description=f"Baseline model: expected TEY {me['delta_tey_mean']:+.3f} MWh on average (ceteris paribus).",
            direction="no_clear_change" if abs(me.get("delta_tey_pct_of_base") or 0) < 0.1 else
            ("increase" if me["delta_tey_mean"] > 0 else "decrease"),
            magnitude_hint=f"{me['delta_tey_min']:+.3f}..{me['delta_tey_max']:+.3f} MWh", confidence="low",
            tool_numbers_cited=[f"simulate_change.model_effect.delta_tey_mean={me['delta_tey_mean']} MWh"],
            basis="model sensitivity"))
    return out


def offline_steps(sens: dict) -> list[NextStep]:
    m = sens["measurement"]
    steps = [
        NextStep(action=f"Verify the {m} reading against a redundant channel or a portable reference before "
                        f"relying on it (I&C engineer).", kind="verify", subsystem="instrumentation",
                 rationale="A measured change may be an instrument effect rather than a process change."),
        NextStep(action=f"Review the {m} trend and the coupled measurements listed above with the shift supervisor.",
                 kind="review", subsystem="",
                 rationale="Coupled channels show whether the change is real and how far it propagates."),
        NextStep(action="Any field inspection is scheduled with a permit to work and isolation per site procedure "
                        "(HSE officer).", kind="isolate_per_procedure", subsystem="",
                 rationale="Field work must follow approved site procedures."),
    ]
    if not sens["train_range_check"]["within_training_range"]:
        steps.insert(0, NextStep(action=f"Treat the modelled numbers as unreliable: the perturbed {m} leaves the "
                                        f"training range; collect plant-specific data first.", kind="collect_data",
                                 rationale="Out-of-training-range what-ifs are extrapolation."))
    return steps


def checks_before_acting(sens: dict) -> list[str]:
    out = [f"Confirm with the shift supervisor and site procedures before any work related to {sens['measurement']}.",
           "Remember the model effect is ceteris paribus and co-movement is association, not causation."]
    trc = sens["train_range_check"]
    if trc["ood_flag"]:
        out.insert(0, f"OUT OF TRAINING RANGE: {trc['rows_outside']}/{trc['rows']} perturbed rows outside "
                      f"[{trc['train_min']}, {trc['train_max']}] — model numbers are extrapolation.")
    return out


def change_spec(sens: dict) -> ChangeSpec:
    return ChangeSpec(measurement=sens["measurement"], delta=sens["delta"], unit=sens["unit"],
                      within_training_range=bool(sens["train_range_check"]["within_training_range"]))


def offline_answer(req: WhatIfRequest, sens: dict) -> WhatIfAnswer:
    return WhatIfAnswer(
        question=req.question or "", change=change_spec(sens), how_it_works=how_it_works(sens["measurement"]),
        effects_elsewhere=offline_effects(sens), recommended_next_steps=offline_steps(sens),
        subsystem_assessments=[offline_assessment(s, sens) for s in SUBSYSTEM_REGISTRY],
        cross_impacts=[], what_to_check_before_acting=checks_before_acting(sens), disclaimer=WHATIF_DISCLAIMER)


# ----------------------------------------------------------------------------- live agents
class _Recorder:
    def __init__(self, run: AgentRun):
        self.run = run

    def add(self, kind: str, summary: str, **kw: Any) -> None:
        with _LIVE_LOCK:
            self.run.events.append(AgentEvent(seq=len(self.run.events) + 1, ts_utc=_now(), kind=kind,
                                              summary=summary[:500], **kw))

    def tokens(self, usage: dict) -> dict[str, int]:
        step = {k: int(usage.get(k, 0) or 0) for k in ("prompt_tokens", "completion_tokens", "total_tokens",
                                                        "reasoning_tokens")}
        with _LIVE_LOCK:
            for k, v in step.items():
                self.run.tokens[k] = self.run.tokens.get(k, 0) + v
        return step


def _chat(client: Any, rec: _Recorder, messages: list[dict], tools: Optional[list], label: str,
          max_tokens: int, json_mode: bool) -> Any:
    rec.add("model_request", f"{label}: {len(messages)} messages -> {getattr(client, 'model', '?')}")
    res = client.chat(messages, tools, max_tokens, response_format={"type": "json_object"} if json_mode else None)
    step = rec.tokens(res.usage or {})
    with _LIVE_LOCK:
        rec.run.latency_ms += int(res.latency_ms or 0)
    rec.add("model_response", f"finish={res.finish_reason}; tool_calls={len(res.message.get('tool_calls') or [])}; "
                              f"content_chars={len(res.message.get('content') or '')}",
            latency_ms=res.latency_ms, tokens=step)
    if res.message.get("content") or res.message.get("tool_calls"):
        messages.append(res.message)  # the API rejects echoed assistant turns with neither (reasoning truncation)
    return res


def _validate_assessment(content: str, sub: dict) -> tuple[Optional[SubsystemAssessment], list[str]]:
    data = extract_json(content) if content else None
    if data is None:
        return None, ["response is not a JSON object"]
    data = dict(data)
    owner, owner_lbl = _owner(sub)
    data.update(subsystem=sub["key"], owner_persona=owner, owner_label=owner_lbl)
    for k in ("caveats", "tool_numbers_cited"):
        if isinstance(data.get(k), str):
            data[k] = [data[k]]
    try:
        a = SubsystemAssessment.model_validate(data)
    except ValidationError as exc:
        return None, [f"schema: {'.'.join(str(p) for p in e.get('loc', ()))}: {e.get('msg')}" for e in exc.errors()]
    errs = scan_texts(_assessment_texts(a, sub["key"]))
    return (a if not errs else None), errs


def run_subsystem_agent(client: Any, sub: dict, req: WhatIfRequest, base: BaseWindow, unit: str,
                        tools: PlantTools, run: AgentRun) -> None:
    rec = _Recorder(run)
    specs = tool_specs(list(MEASUREMENTS))
    messages = [{"role": "system", "content": agent_system_prompt(sub)},
                {"role": "user", "content": agent_user_prompt(req, base, unit, sub)}]
    try:
        res = _chat(client, rec, messages, specs, "round 1 (tools)", MAX_TOKENS, False)
        calls = res.message.get("tool_calls") or []
        content = res.message.get("content") or ""
        if calls:
            for tc in calls[:6]:
                fn = tc.get("function") or {}
                name = fn.get("name") or "?"
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                    if not isinstance(args, dict):
                        raise ValueError("arguments must be a JSON object")
                    result = tools.run(name, args)
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
        assessment, errs = _validate_assessment(content, sub)
        if assessment is None:
            truncated = res.finish_reason == "length" and not content
            rec.add("rewrite_requested", ("truncated; " if truncated else "") + " | ".join(errs)[:400])
            messages.append({"role": "user", "content": "Your previous answer was rejected:\n" +
                             "\n".join(f"- {e}" for e in errs) + "\n" + FINAL_TURN})
            res = _chat(client, rec, messages, None, "rewrite", RETRY_MAX_TOKENS, True)
            assessment, errs = _validate_assessment(res.message.get("content") or "", sub)
        if assessment is not None and not run.used_tools:
            assessment = assessment.model_copy(update={
                "confidence": "low", "caveats": [*assessment.caveats, "Agent answered without calling tools; "
                                                 "numbers not tool-verified."]})
        with _LIVE_LOCK:
            run.assessment = assessment
            run.ok = assessment is not None
            run.error = None if assessment is not None else "; ".join(errs)[:400]
        rec.add("validation", "assessment accepted" if assessment else f"rejected: {len(errs)} error(s)",
                ok=assessment is not None)
    except Exception as exc:  # noqa: BLE001 - MetaClientError is already redacted
        msg = str(exc)[:300] if type(exc).__name__ == "MetaClientError" else f"agent error ({type(exc).__name__})"
        with _LIVE_LOCK:
            run.ok, run.error = False, msg
        rec.add("error", msg, ok=False)


def _validate_aggregate(content: str, base_answer: WhatIfAnswer) -> tuple[Optional[WhatIfAnswer], list[str]]:
    data = extract_json(content) if content else None
    if data is None:
        return None, ["response is not a JSON object"]
    try:
        steps = []
        for s in data.get("recommended_next_steps") or []:
            if isinstance(s, str):
                s = {"action": s}
            s = dict(s)
            s["requires_supervisor_approval"] = True  # forced
            if s.get("kind") not in NextStep.model_fields["kind"].annotation.__args__:
                s["kind"] = "review"
            steps.append(NextStep.model_validate(s))
        effects = [EffectElsewhere.model_validate(e) for e in data.get("effects_elsewhere") or []]
        cross = [CrossImpact.model_validate(c if isinstance(c, dict) else {"description": str(c)})
                 for c in data.get("cross_impacts") or []]
        checks = [str(c) for c in data.get("what_to_check_before_acting") or []]
    except (ValidationError, TypeError, AttributeError) as exc:
        return None, [f"schema: {str(exc)[:300]}"]
    errs = []
    if not effects:
        errs.append("effects_elsewhere must not be empty (say 'cannot tell' with confidence low if unsure)")
    if not steps:
        errs.append("recommended_next_steps must not be empty")
    ans = base_answer.model_copy(update={
        "effects_elsewhere": effects, "recommended_next_steps": steps, "cross_impacts": cross,
        "what_to_check_before_acting": (base_answer.what_to_check_before_acting[:1]
                                        if not base_answer.change.within_training_range else [])
        + (checks or base_answer.what_to_check_before_acting)})
    errs += scan_texts(answer_texts(ans))
    return (ans if not errs else None), errs


def run_aggregator(client: Any, req: WhatIfRequest, sens: dict, base_answer: WhatIfAnswer,
                   run: AgentRun) -> tuple[Optional[WhatIfAnswer], list[str]]:
    rec = _Recorder(run)
    me = sens["model_effect"]
    payload = {
        "question": base_answer.question, "change": base_answer.change.model_dump(),
        "deterministic_tool_summary": {
            "model_effect": {k: me.get(k) for k in ("applicable", "delta_tey_mean", "delta_tey_min",
                                                    "delta_tey_max", "delta_tey_pct_of_base", "note")},
            "train_range_check": sens["train_range_check"],
            "co_movement_top": sens["co_movement"]["items"][:6], "co_movement_label": ASSOCIATION_LABEL},
        "subsystem_assessments": [a.model_dump() for a in base_answer.subsystem_assessments],
    }
    messages = [{"role": "system", "content": AGGREGATOR_SYSTEM},
                {"role": "user", "content": "INPUT (JSON):\n" + json.dumps(payload, indent=1, default=str)}]
    try:
        res = _chat(client, rec, messages, None, "aggregate", AGGREGATOR_MAX_TOKENS, True)
        ans, errs = _validate_aggregate(res.message.get("content") or "", base_answer)
        if ans is None:
            rec.add("rewrite_requested", " | ".join(errs)[:400])
            messages.append({"role": "user", "content": "Your previous answer was rejected:\n" +
                             "\n".join(f"- {e}" for e in errs) + "\nReturn the corrected JSON object only."})
            res = _chat(client, rec, messages, None, "aggregate rewrite", RETRY_MAX_TOKENS, True)
            ans, errs = _validate_aggregate(res.message.get("content") or "", base_answer)
        rec.add("validation", "aggregate accepted" if ans else f"rejected: {len(errs)} error(s)", ok=ans is not None)
        with _LIVE_LOCK:
            run.ok, run.error = ans is not None, (None if ans else "; ".join(errs)[:400])
        return ans, errs
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)[:300] if type(exc).__name__ == "MetaClientError" else f"aggregator error ({type(exc).__name__})"
        rec.add("error", msg, ok=False)
        with _LIVE_LOCK:
            run.ok, run.error = False, msg
        return None, [msg]


# ----------------------------------------------------------------------------- entry points
def prepare(req: WhatIfRequest, persona: Optional[str], client: Any) -> tuple[WhatIfSession, dict, BaseWindow]:
    """Validates input (ValueError/KeyError -> 422/404) and computes the deterministic sensitivity."""
    pid = resolve_persona(req.persona or persona).persona_id
    base = resolve_base(req.case_id)
    sens = simulate_change(req.measurement, req.delta, base)
    req = req.model_copy(update={"persona": pid, "question": (req.question or "").strip()[:2000]})
    live = client is not None and getattr(client, "configured", False)
    session = WhatIfSession(
        session_id=f"wi_{secrets.token_hex(6)}", created_at_utc=_now(), status="running", persona=pid, request=req,
        mode="meta_live" if live else "offline", mode_label=LIVE_LABEL if live else OFFLINE_LABEL,
        meta_used=False, base_window=sens["base"], sensitivity=sens)
    return session, sens, base


def execute(session: WhatIfSession, sens: dict, base: BaseWindow, client: Any) -> WhatIfSession:
    """Runs the agents (or the offline path), validates, persists and returns the final session."""
    t0 = time.perf_counter()
    req = session.request
    with _LIVE_LOCK:
        _LIVE[session.session_id] = session
    try:
        base_answer = offline_answer(req, sens)
        if session.mode == "offline":
            with _LIVE_LOCK:
                session.answer = base_answer
                session.status = "completed"
            return session
        tools = PlantTools(base)
        runs = {s["key"]: AgentRun(agent=s["key"], ok=False, used_tools=False, latency_ms=0)
                for s in SUBSYSTEM_REGISTRY}
        with _LIVE_LOCK:
            session.agents = list(runs.values())
        pool = ThreadPoolExecutor(max_workers=len(runs), thread_name_prefix="whatif")
        futures = [pool.submit(run_subsystem_agent, client, s, req, base, sens["unit"], tools, runs[s["key"]])
                   for s in SUBSYSTEM_REGISTRY]
        _, pending = wait(futures, timeout=AGENT_BUDGET_S)
        pool.shutdown(wait=False, cancel_futures=True)
        with _LIVE_LOCK:
            for key, run in runs.items():
                if run.assessment is None and not run.error and pending:
                    run.ok, run.error = False, f"timed out after {AGENT_BUDGET_S:.0f}s budget"
        assessments = []
        for s in SUBSYSTEM_REGISTRY:
            a = runs[s["key"]].assessment
            if a is None:  # deterministic stand-in, clearly labelled
                a = offline_assessment(s, sens).model_copy(update={"caveats": [
                    "Agent did not return a valid assessment (see validation_errors); deterministic stand-in "
                    "shown.", ASSOCIATION_LABEL]})
            assessments.append(a)
        base_answer = base_answer.model_copy(update={"subsystem_assessments": assessments})
        n_ok = sum(1 for r in runs.values() if r.ok)
        agg = AgentRun(agent="aggregator", ok=False, used_tools=False, latency_ms=0)
        with _LIVE_LOCK:
            session.agents.append(agg)
        ans, errs = (run_aggregator(client, req, sens, base_answer, agg) if n_ok else
                     (None, ["no subsystem agent returned a valid assessment"]))
        with _LIVE_LOCK:
            session.meta_used = n_ok > 0
            session.meta_model = getattr(client, "model", None)
            if ans is not None:
                session.answer, session.status = ans, "completed"
            else:
                session.answer, session.status = base_answer, "needs_review"
                session.validation_errors = list(errs)
            session.validation_errors += [f"{r.agent}: {r.error}" for r in runs.values() if r.error]
    except Exception as exc:  # noqa: BLE001
        log.exception("what-if %s failed", session.session_id)
        with _LIVE_LOCK:
            session.status, session.error = "failed", f"what-if failed ({type(exc).__name__})"
    finally:
        with _LIVE_LOCK:
            session.completed_at_utc = _now()
            session.wall_ms = int((time.perf_counter() - t0) * 1000)
            final = session.model_copy(deep=True)
        store.save_session(final)
        with _LIVE_LOCK:
            _LIVE.pop(session.session_id, None)
    return final


def run_whatif(req: WhatIfRequest, client: Any, persona: Optional[str] = None,
               background: bool = False, on_done: Optional[Callable[[WhatIfSession], None]] = None) -> WhatIfSession:
    session, sens, base = prepare(req, persona, client)
    if not background:
        return execute(session, sens, base, client)
    snapshot = session.model_copy(deep=True)
    threading.Thread(target=execute, args=(session, sens, base, client), daemon=True,
                     name=f"whatif-{session.session_id}").start()
    return snapshot
