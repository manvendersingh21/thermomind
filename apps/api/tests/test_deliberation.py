""""Propose an action" (advisory deliberation) tests: intents, pre-checks, scripted parallel fake Meta, safety
rewrite/fallback, 429, human-decision routing, endpoints (test-local FastAPI app), rehearsal. No network."""
from __future__ import annotations

import json
import re
import sys
import threading
import time
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import services
from app.agent.meta_client import ChatResult
from app.features.deliberation import decisions, deliberate, intents, rehearsal
from app.features.deliberation import router as delib_router
from app.features.deliberation.prechecks import resolve_window, run_prechecks
from app.features.deliberation.schemas import DecisionRequest, ProposeRequest
from app.plant import store as plant_store
from app.plant.sensitivity import training_stats
from app.plant.subsystems import SUBSYSTEM_REGISTRY
from app.schemas import InvestigationRequest

DS = "ds_uci_551"
START, END = 100, 220  # fixture has 300 rows per year
ALL_AGENTS = [s["key"] for s in SUBSYSTEM_REGISTRY] + [deliberate.CONSTRAINTS_AGENT]


@pytest.fixture(scope="module")
def case(client):
    req = InvestigationRequest(dataset_id=DS, scenario_id="S02_INTAKE_RESTRICTION", year=2014,
                               start_index=START, end_index=END, use_meta=False)
    return services.run_investigation_pipeline(req)


@pytest.fixture(scope="module")
def api(client):
    app = FastAPI()
    app.include_router(delib_router.router, prefix="/api")
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setattr(delib_router, "_client", lambda: None)


# ----------------------------------------------------------------------------- fake Meta
GOOD_AGG = {
    "recommendation": "proceed_with_conditions",
    "summary": "Most agents see manageable effects provided the TIT envelope finding is resolved first.",
    "dissent": [{"subsystem": "combustion_turbine", "why": "TIT would sit above the historical p99 (finding #5)."},
                {"subsystem": "not_an_agent", "why": "dropped"}],
    "conditions": ["TIT margin confirmed with the OEM before a person decides.",
                   "Emissions screening reviewed by the environmental engineer."],
    "what_could_go_wrong": ["TIT above the historical envelope (finding #5)", "faster hot-gas-path life consumption"],
    "rehearsal_suggestion": "A rehearsal should look at TIT and TAT over the window.",
    "who_must_approve": ["shift_supervisor", "reliability_engineer", "nobody_real"],
}
UNSAFE_AGG = dict(GOOD_AGG, conditions=["Increase output by 5 MW and open the fuel valve."])


class FakeMeta:
    """Thread-safe scripted client routed by the system prompt; records peak concurrency."""
    model = "fake-muse"
    configured = True

    def __init__(self, verdicts: dict[str, str], agg: list[dict], agent_texts: dict[str, list[str]] | None = None,
                 delay: float = 0.05):
        self.verdicts, self.agg, self.texts, self.delay = verdicts, list(agg), agent_texts or {}, delay
        self.lock = threading.Lock()
        self.active = self.peak = 0
        self.calls: list[str] = []

    def _key(self, system: str) -> str:
        if "CONSTRAINTS & SAFETY" in system:
            return deliberate.CONSTRAINTS_AGENT
        return re.search(r"\(([a-z_]+)\) agent", system).group(1)

    def chat(self, messages, tools, max_tokens, response_format=None):
        system = messages[0]["content"]
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            time.sleep(self.delay)
            if "deliberation chair" in system:
                with self.lock:
                    self.calls.append("aggregator")
                    reply = self.agg.pop(0) if len(self.agg) > 1 else self.agg[0]
                return ChatResult(message={"role": "assistant", "content": json.dumps(reply)}, usage=usage,
                                  latency_ms=3, model=self.model, finish_reason="stop")
            key = self._key(system)
            with self.lock:
                self.calls.append(key)
            if tools:
                return ChatResult(message={"role": "assistant", "content": None, "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "simulate_change", "arguments": json.dumps(
                        {"measurement": "TIT", "delta": 4.0})}}]}, usage=usage, latency_ms=3, model=self.model,
                    finish_reason="tool_calls")
            with self.lock:
                queue = self.texts.get(key) or []
                text = queue.pop(0) if len(queue) > 1 else (queue[0] if queue else
                                                            f"From the {key} view the proposed change looks manageable.")
            return ChatResult(message={"role": "assistant", "content": json.dumps({
                "subsystem": key, "verdict": self.verdicts.get(key, "neutral"), "confidence": "medium",
                "reasons": [text], "harms": ["TIT closer to its historical ceiling (finding #5)."],
                "prerequisites": ["Verify the TIT instrumentation before a person decides."],
                "tool_numbers_cited": ["finding #5 tit_envelope"]})}, usage=usage, latency_ms=3, model=self.model,
                finish_reason="stop")
        finally:
            with self.lock:
                self.active -= 1


VERDICTS = {"intake": "support", "compressor": "support", "combustion_turbine": "oppose",
            "exhaust_emissions": "neutral", "generator_output": "insufficient_evidence",
            deliberate.CONSTRAINTS_AGENT: "oppose"}


# ----------------------------------------------------------------------------- A. intents
def test_raise_output_deltas_use_training_slopes_with_provenance(client):
    st = training_stats(DS)
    ch = intents.build_change("raise_output", 5.0)
    d = {x.measurement: x for x in ch.deltas}
    assert d["TEY"].role == "primary" and d["TEY"].delta == 5.0 and d["TEY"].provenance == "operator_intent"
    expected_tit = st["cov"]["TEY"]["TIT"] / st["cov"]["TEY"]["TEY"] * 5.0
    assert d["TIT"].role == "implied" and d["TIT"].provenance == "statistical_association"
    assert d["TIT"].delta == pytest.approx(expected_tit, abs=1e-3) and d["TIT"].slope_of == "TEY"
    assert d["CDP"].pearson_r is not None and "least-squares" in d["CDP"].basis
    assert "not causation" in ch.slope_label and ch.training_years == st["years"]
    assert any("Fuel flow is not measured" in n for n in ch.qualitative_notes)
    low = intents.build_change("lower_output", 5.0)
    assert {x.measurement: x.delta for x in low.deltas}["TEY"] == -5.0


def test_intent_validation_and_catalogue(client):
    ids = [i.intent_id for i in intents.list_intents()]
    assert {"raise_output", "lower_output", "open_igv_airflow", "raise_firing_temperature",
            "run_with_higher_filter_dp", "reduce_cooling_water", "custom"} <= set(ids)
    with pytest.raises(ValueError):
        intents.build_change("raise_output", 500.0)
    with pytest.raises(KeyError):
        intents.build_change("make_it_go_faster", 1.0)
    with pytest.raises(ValueError):
        intents.build_change(None, None, None)
    tit = intents.build_change("raise_firing_temperature", 5.0)
    assert tit.deltas[0].measurement == "TIT" and any(x.measurement == "TEY" for x in tit.deltas)


def test_cooling_water_is_not_observable_and_custom_uses_explicit_deltas(client):
    cw = intents.build_change("reduce_cooling_water", 10.0)
    assert cw.observable is False and cw.deltas == []
    assert any("not observable in this data; qualitative only" in n for n in cw.qualitative_notes)
    from app.features.deliberation.schemas import CustomIntent

    cu = intents.build_change("custom", None, CustomIntent(text="nudge the compressor", deltas={"CDP": 0.2, "AT": 0}))
    assert [(x.measurement, x.delta, x.role) for x in cu.deltas] == [("CDP", 0.2, "primary")]
    assert cu.subsystems == ["compressor"]
    with pytest.raises(ValueError):
        intents.build_change("custom", None, CustomIntent(text="bad", deltas={"FUEL": 1.0}))


# ----------------------------------------------------------------------------- B1. pre-checks
def test_prechecks_numbered_with_provenance(case):
    base = resolve_window(ProposeRequest(case_id=case.case_id))
    f = run_prechecks(intents.build_change("raise_output", 5.0), base)
    assert [x.n for x in f] == list(range(1, len(f) + 1))
    keys = {x.key for x in f}
    assert {"basis", "sensitivity_TEY", "joint_model", "implied_range", "tit_envelope", "emissions",
            "thermal_margins", "grid_headroom"} <= keys
    by = {x.key: x for x in f}
    assert by["thermal_margins"].provenance == "simulated" and by["grid_headroom"].provenance == "assumption"
    assert by["joint_model"].provenance == "model_derived" and "delta_tey_mean" in by["joint_model"].numbers
    assert by["tit_envelope"].numbers["delta_tit_c"] > 0 and "p99_c" in by["tit_envelope"].numbers
    assert by["thermal_margins"].numbers["demand_multiplier"] > 1.0
    assert set(by["emissions"].numbers) >= {"CO", "NOX"}
    assert all(x.source and x.status in ("ok", "info", "watch", "concern", "exceeds", "unavailable") for x in f)
    cw = run_prechecks(intents.build_change("reduce_cooling_water", 10.0), base)
    assert any(x.key == "observability" and x.provenance == "not_observable" for x in cw)


def test_window_resolution_rules(client):
    assert resolve_window(ProposeRequest()).case_id is None
    w = resolve_window(ProposeRequest(year=2014, start=10, end=60))
    assert (w.year, w.start, w.end) == (2014, 10, 60)
    with pytest.raises(ValueError):
        resolve_window(ProposeRequest(year=2014, start=10))
    with pytest.raises(ValueError):
        resolve_window(ProposeRequest(year=2014, start=10, end=20))  # < 24 rows
    with pytest.raises(ValueError):
        resolve_window(ProposeRequest(year=2014, start=200, end=900))  # beyond the 300 fixture rows


# ----------------------------------------------------------------------------- B2/B3. agents
def test_fake_meta_parallel_deliberation_consensus_math(case):
    fake = FakeMeta(VERDICTS, [GOOD_AGG])
    s = deliberate.propose(ProposeRequest(case_id=case.case_id, intent_id="raise_output", magnitude=5),
                           fake, background=False)
    assert s.status == "completed" and s.mode == "meta_live", s.validation_errors
    assert fake.peak >= 2  # agents really ran in parallel
    runs = {a.agent: a for a in s.agents}
    assert set(runs) == {*ALL_AGENTS, "aggregator"}
    assert all(runs[k].ok and runs[k].verdict.verdict == VERDICTS[k] for k in ALL_AGENTS)
    assert runs["intake"].used_tools and not runs[deliberate.CONSTRAINTS_AGENT].used_tools
    assert any(e.kind == "tool_call" and e.tool_name == "simulate_change" for e in runs["intake"].events)
    assert runs["aggregator"].tokens["total_tokens"] > 0
    o = s.outcome
    assert o.consensus.model_dump() == {"support": 2, "oppose": 2, "neutral": 1, "insufficient": 1}
    assert o.source == "model" and o.recommendation == "proceed_with_conditions"
    assert [d.subsystem for d in o.dissent] == ["combustion_turbine"]  # unknown subsystem dropped
    assert o.who_must_approve[0] == "shift_supervisor" and "nobody_real" not in o.who_must_approve
    assert o.disclaimer == "Advisory deliberation; the human decides; this software executes nothing"
    assert any("exceed" in g for g in o.guard_notes) == any(f.status == "exceeds" for f in s.constraint_findings)
    stored = deliberate.get_session(s.deliberation_id)
    assert stored.outcome.consensus == o.consensus


def test_command_like_text_rejected_then_rewritten(case):
    texts = {"intake": ["Increase output by 5 MW now.", "An output rise of this size looks manageable for the intake."]}
    fake = FakeMeta(VERDICTS, [GOOD_AGG], agent_texts=texts)
    s = deliberate.propose(ProposeRequest(case_id=case.case_id, intent_id="raise_output"), fake, background=False)
    intake = next(a for a in s.agents if a.agent == "intake")
    assert any(e.kind == "rewrite_requested" and "unsafe_instruction" in e.summary for e in intake.events)
    assert intake.ok and intake.verdict.fallback is False
    assert "manageable" in intake.verdict.reasons[0]


def test_command_like_text_twice_falls_back_labelled(case):
    texts = {k: ["Open the fuel valve and raise firing temperature."] for k in ALL_AGENTS}
    fake = FakeMeta(VERDICTS, [UNSAFE_AGG])
    fake.texts = texts
    s = deliberate.propose(ProposeRequest(case_id=case.case_id, intent_id="raise_output"), fake, background=False)
    assert all(a.verdict.fallback and not a.ok for a in s.agents if a.agent in ALL_AGENTS)
    assert all(any(e.kind == "fallback" for e in a.events) for a in s.agents if a.agent in ALL_AGENTS)
    # no agent valid -> aggregator not called; deterministic outcome, labelled
    assert "aggregator" not in fake.calls
    assert s.status == "needs_review" and s.outcome.source == "deterministic_fallback"
    assert "deterministic fallback" in s.outcome.source_label


def test_unsafe_aggregator_twice_uses_deterministic_outcome(case):
    fake = FakeMeta(VERDICTS, [UNSAFE_AGG])
    s = deliberate.propose(ProposeRequest(case_id=case.case_id, intent_id="raise_output"), fake, background=False)
    agg = next(a for a in s.agents if a.agent == "aggregator")
    assert fake.calls.count("aggregator") == 2 and not agg.ok
    assert any(e.kind == "rewrite_requested" for e in agg.events)
    assert s.status == "needs_review" and s.outcome.source == "deterministic_fallback"
    assert any("unsafe_instruction" in e for e in s.validation_errors)
    assert s.outcome.consensus.model_dump() == {"support": 2, "oppose": 2, "neutral": 1, "insufficient": 1}


@pytest.mark.parametrize("intent_id", ["raise_output", "lower_output", "open_igv_airflow",
                                       "raise_firing_temperature", "run_with_higher_filter_dp",
                                       "reduce_cooling_water"])
def test_offline_fallback_is_scanner_clean_and_never_supports(case, intent_id):
    s = deliberate.propose(ProposeRequest(case_id=case.case_id, intent_id=intent_id), None, background=False)
    assert s.mode == "offline" and s.status == "completed"
    errs = deliberate.scan_texts(deliberate.outcome_texts(s.outcome))
    for a in s.agents:
        errs += deliberate.scan_texts(deliberate.verdict_texts(a.verdict, a.agent))
        assert a.verdict.fallback and a.verdict.verdict != "support"
    assert errs == []
    if intent_id == "reduce_cooling_water":
        assert s.outcome.recommendation == "insufficient_evidence"


def test_guard_forces_insufficient_for_unobservable_change(case):
    fake = FakeMeta(VERDICTS, [GOOD_AGG])
    s = deliberate.propose(ProposeRequest(case_id=case.case_id, intent_id="reduce_cooling_water"), fake,
                           background=False)
    assert s.outcome.recommendation == "insufficient_evidence"
    assert any("not observable" in g for g in s.outcome.guard_notes)


# ----------------------------------------------------------------------------- concurrency
def test_429_when_saturated(api, offline, case):
    got = [deliberate._SLOTS.acquire(blocking=False) for _ in range(deliberate.MAX_CONCURRENT)]
    try:
        assert all(got)
        r = api.post("/api/deliberation/propose", json={"case_id": case.case_id, "intent_id": "raise_output"})
        assert r.status_code == 429 and "busy" in r.json()["detail"]
    finally:
        for _ in got:
            deliberate._SLOTS.release()
    r = api.post("/api/deliberation/propose?wait=true", json={"case_id": case.case_id, "intent_id": "raise_output"})
    assert r.status_code == 200


def test_background_run_is_pollable(case):
    fake = FakeMeta(VERDICTS, [GOOD_AGG], delay=0.2)
    snap = deliberate.propose(ProposeRequest(case_id=case.case_id, intent_id="raise_output"), fake, background=True)
    assert snap.status == "running"
    assert deliberate.get_session(snap.deliberation_id).status in ("running", "completed")
    for _ in range(100):
        s = deliberate.get_session(snap.deliberation_id)
        if s.status != "running":
            break
        time.sleep(0.1)
    assert s.status == "completed" and s.outcome is not None


# ----------------------------------------------------------------------------- B4. human decision
def test_decision_recorded_and_routed_never_executed(case):
    s = deliberate.propose(ProposeRequest(case_id=case.case_id, intent_id="raise_output"), None, background=False)
    out = decisions.record_decision(s.deliberation_id, DecisionRequest(
        decision="approve_plan", persona="mechanical_maintenance_engineer", comment="ok under the conditions"))
    d = out.decisions[-1]
    assert d.routed_to == "shift_supervisor" and d.executed is False
    assert d.message.startswith("Recorded; routed to") and "nothing was executed" in d.message
    assert d.work_request_id is None and "Record + notification only" in d.routing_note
    inbox = plant_store.list_notifications("shift_supervisor")
    n = next(x for x in inbox if x.id == d.notification_id)
    assert s.deliberation_id in n.message and "executed nothing" in n.message and n.case_id == case.case_id
    pm = decisions.record_decision(s.deliberation_id, DecisionRequest(decision="defer", persona="plant_manager"))
    assert pm.decisions[-1].routed_to == "plant_manager" and len(pm.decisions) == 2


def test_decision_never_creates_work_request_even_when_creator_offered(case, monkeypatch):
    called = []
    monkeypatch.setattr(decisions, "work_request_creator", lambda: (lambda **kw: called.append(kw)))
    s = deliberate.propose(ProposeRequest(case_id=case.case_id, intent_id="raise_output"), None, background=False)
    for dec in ("approve_plan", "reject", "defer"):
        out = decisions.record_decision(s.deliberation_id, DecisionRequest(decision=dec, persona="electrical_engineer"))
        d = out.decisions[-1]
        assert d.work_request_id is None and d.executed is False and d.notification_id
    assert called == []  # the decision endpoint triggers a record + notification and nothing else


# ----------------------------------------------------------------------------- endpoints
def test_endpoints_roundtrip_and_errors(api, offline, case):
    r = api.get("/api/deliberation/intents")
    assert r.status_code == 200 and any(i["intent_id"] == "raise_output" for i in r.json())
    r = api.post("/api/deliberation/propose?wait=true", headers={"X-Persona": "performance_engineer"},
                 json={"case_id": case.case_id, "intent_id": "raise_output", "magnitude": 5})
    assert r.status_code == 200, r.text
    body = r.json()
    did = body["deliberation_id"]
    assert body["persona"] == "performance_engineer" and body["status"] == "completed"
    assert body["banner"].startswith("Advisory deliberation between software agents")
    assert api.get(f"/api/deliberation/{did}").json()["deliberation_id"] == did
    assert did in [x["deliberation_id"] for x in api.get(f"/api/deliberation?case_id={case.case_id}").json()]
    r = api.post(f"/api/deliberation/{did}/decision", json={"decision": "reject", "persona": "shift_supervisor"})
    assert r.status_code == 200 and r.json()["decisions"][-1]["routed_to"] == "plant_manager"
    # errors
    assert api.get("/api/deliberation/dl_doesnotexist").status_code == 404
    assert api.post("/api/deliberation/dl_doesnotexist/decision", json={"decision": "defer"}).status_code == 404
    assert api.post(f"/api/deliberation/{did}/decision", json={"decision": "execute_it"}).status_code == 422
    assert api.post(f"/api/deliberation/{did}/decision",
                    json={"decision": "defer", "persona": "nobody"}).status_code == 404
    assert api.post("/api/deliberation/propose", json={"case_id": case.case_id}).status_code == 422
    assert api.post("/api/deliberation/propose",
                    json={"case_id": case.case_id, "intent_id": "raise_output", "magnitude": 999}).status_code == 422
    assert api.post("/api/deliberation/propose", json={"case_id": "case_missing", "intent_id": "raise_output"}
                    ).status_code == 404
    assert api.post("/api/deliberation/propose", json={"intent_id": "nope"}).status_code == 404
    assert api.post("/api/deliberation/propose", json={"year": 2014, "start": 5, "intent_id": "raise_output"}
                    ).status_code == 422


def test_decision_conflict_while_running(api, case):
    fake = FakeMeta(VERDICTS, [GOOD_AGG], delay=0.3)
    snap = deliberate.propose(ProposeRequest(case_id=case.case_id, intent_id="raise_output"), fake, background=True)
    r = api.post(f"/api/deliberation/{snap.deliberation_id}/decision", json={"decision": "approve_plan"})
    assert r.status_code == 409
    for _ in range(100):
        if deliberate.get_session(snap.deliberation_id).status != "running":
            break
        time.sleep(0.1)


# ----------------------------------------------------------------------------- B5. rehearsal
def test_rehearsal_unavailable_and_available_paths(monkeypatch):
    ch = intents.build_change("raise_output", 5.0, stats={"years": [2011], "cov": {}, "corr": {}})
    monkeypatch.setitem(sys.modules, "app.simulator", None)  # import -> ImportError
    r = rehearsal.try_rehearsal(ch)
    assert r.status == "unavailable" and "not importable" in r.reason
    cw = intents.build_change("reduce_cooling_water", 10.0, stats={"years": [], "cov": {}, "corr": {}})
    assert rehearsal.try_rehearsal(cw).status == "unavailable"

    class Engine:
        def rehearse(self, deltas, steps):
            return {"summary": f"{steps} steps with {sorted(deltas)}", "max_tit": 1101.0}

    fake = types.ModuleType("app.simulator")
    fake.service = types.SimpleNamespace(engine=Engine())
    monkeypatch.setitem(sys.modules, "app.simulator", fake)
    r = rehearsal.try_rehearsal(ch, steps=10_000)
    assert r.status == "available" and r.steps == rehearsal.MAX_STEPS
    assert r.outcome_summary == f"{rehearsal.MAX_STEPS} steps with ['TEY']" and r.details["max_tit"] == 1101.0
    fake.service = types.SimpleNamespace(engine=object())
    assert "no recognised entry point" in rehearsal.try_rehearsal(ch).reason
