"""Tests for app.features.collab (autonomy policy, activity feed, domino map, onboarding). No network."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import config
from app.agent.meta_client import ChatResult, MetaClientError
from app.agent.report_validator import UNSAFE_PATTERNS
from app.features.collab import autonomy, db, dependencies, onboarding
from app.features.collab import router as collab_router
from app.features.collab.schemas import ONBOARDING_BADGE, ONBOARDING_DISCLAIMER
from app.schemas import (AgentEvent, DiagnosticReport, Evidence, Hypothesis, Investigation, InvestigationRequest,
                         Observation, ReviewRecord, SampleRange, ScenarioInfo)

WIN = SampleRange(source_year=2014, start=1200, end=1320)
REF = SampleRange(source_year=2014, start=960, end=1200)
T0 = datetime(2026, 11, 4, 10, 0, 0, tzinfo=timezone.utc)


def ts(minutes: float) -> str:
    return (T0 + timedelta(minutes=minutes)).isoformat(timespec="seconds").replace("+00:00", "Z")


def ev(eid: str, metric: str, z: float | None, flags=(), dq="pass", synthetic=False) -> Evidence:
    return Evidence(evidence_id=eid, case_id="x", kind="real_observation", metric=metric, unit="u", title=eid,
                    sample_range=WIN, reference_range=REF, observed_stat=1.0, comparison_stat=1.0, z_score=z,
                    method="m", computation="c", flags=list(flags), data_quality=dq, is_synthetic=synthetic)


def make_inv(case_id="case_real01", *, synthetic=False, severity="informational", status="completed",
             hypothesis="operating_condition", evidence=None, report=True, review=None) -> Investigation:
    scen = ScenarioInfo(scenario_id="S02_INTAKE_RESTRICTION" if synthetic else "S01_NORMAL",
                        title="Intake restriction (synthetic)" if synthetic else "Normal operation (real)",
                        synthetic=synthetic, description="d", rationale="r", affected_measurements=[],
                        expected_behavior="x")
    label = "synthetic_overlay" if synthetic else "real_only"
    evidence = evidence if evidence is not None else [
        ev("ev_afdp_01", "AFDP", 0.1), ev("ev_tey_residual_01", "TEY_residual", 0.9), ev("ev_at_01", "AT", 1.2),
        ev("ev_cdp_02", "CDP_segments", -6.9, flags=["coincident_with_other_sensors"])]
    rep = DiagnosticReport(
        case_id=case_id, title="t", summary="s", severity=severity, scenario_label=label,
        observations=[Observation(statement="o", evidence_ids=["ev_afdp_01"])],
        hypotheses=[Hypothesis(name="h", key=hypothesis, rank=1, status="possible")],
        additional_data_needed=[], engineer_review_checks=["Compare AFDP with reference"], limitations=[]) if report else None
    events = [AgentEvent(seq=1, ts_utc=ts(0), kind="case_opened", summary="opened"),
              AgentEvent(seq=2, ts_utc=ts(1), kind="tool_call", tool_name="list_evidence", summary="t"),
              AgentEvent(seq=3, ts_utc=ts(1.5), kind="tool_call", tool_name="recall_similar_cases", summary="k=3"),
              AgentEvent(seq=4, ts_utc=ts(2), kind="validation", summary="report invalid", ok=False),
              AgentEvent(seq=5, ts_utc=ts(2.5), kind="rewrite_requested", summary="one rewrite"),
              AgentEvent(seq=6, ts_utc=ts(3), kind="validation", summary="ok"),
              AgentEvent(seq=7, ts_utc=ts(3), kind="report_accepted", summary="accepted")]
    return Investigation(
        case_id=case_id, status=status, created_at_utc=ts(0), completed_at_utc=ts(4),
        request=InvestigationRequest(dataset_id="ds_uci_551", scenario_id=scen.scenario_id), scenario=scen,
        scenario_label=label, window=WIN, reference=REF, model_version="v1", meta_model="muse-spark-1.3",
        meta_used=True, mode="meta_live", report=rep, evidence=evidence, events=events,
        review=ReviewRecord(decision=review, reviewer="demo-engineer", comment="looks fine", ts_utc=ts(30))
        if review else None)


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "collab_test.db")
    yield tmp_path / "collab_test.db"


NO_EM = {"CO": 0.1, "NOX": -0.3}


# ----------------------------------------------------------------------------- A. autonomy policy
def test_policy_matrix_shape():
    p = autonomy.policy_response()
    assert p.policy_id == "P-01" and set(p.levels) == {"agent_auto", "human_review", "human_only"}
    by_level = {lvl: [a for a in p.actions if a.level == lvl] for lvl in p.levels}
    assert all(by_level.values())
    assert len({a.action_id for a in p.actions}) == len(p.actions)
    assert all(a.reversible for a in by_level["agent_auto"])
    assert {"plant_control", "switching", "maintenance_work"} <= {a.action_id for a in by_level["human_only"]}
    assert all(a.link is None for a in by_level["human_only"])  # no software path
    assert {"review_case_report", "work_request_status", "approve_next_steps"} <= {a.action_id for a in by_level["human_review"]}
    assert p.counts.total == 0 and len(p.auto_triage_conditions) >= 5


def test_auto_triage_only_informational_real_non_notable(tmp_db):
    inv = make_inv()
    d = autonomy.decide(inv, emissions=NO_EM)
    assert d.decision == "auto_triaged_no_action" and d.reversible and d.policy_id == "P-01"
    assert all(c.passed for c in d.conditions)
    # coincident_with_other_sensors on CDP_segments is not a notable flag; the case/report are untouched
    assert inv.status == "completed" and inv.report.severity == "informational"
    from app.plant import store as plant_store

    notes = plant_store.list_notifications("control_room_operator")
    assert len(notes) == 1 and "auto-triaged by policy P-01" in notes[0].message and "reversible" in notes[0].message


@pytest.mark.parametrize("inv,emissions,failed", [
    (make_inv("case_syn", synthetic=True), NO_EM, "real_data_only"),
    (make_inv("case_rev", severity="review"), NO_EM, "informational"),
    (make_inv("case_urg", severity="urgent_review"), NO_EM, "informational"),
    (make_inv("case_nr", status="needs_review"), NO_EM, "completed_with_report"),
    (make_inv("case_norep", report=False), NO_EM, "completed_with_report"),
    (make_inv("case_flag", evidence=[ev("ev_at_02", "AT_trend", 3.6, flags=["notable_deviation"])]), NO_EM,
     "no_notable_flags"),
    (make_inv("case_dq", evidence=[ev("ev_afdp_01", "AFDP", 0.1, dq="warn")]), NO_EM, "no_notable_flags"),
    (make_inv("case_z", evidence=[ev("ev_tit_01", "TIT", 2.4)]), NO_EM, "no_notable_signal_z"),
    (make_inv("case_synev", evidence=[ev("ev_afdp_01", "AFDP", 0.1, synthetic=True)]), NO_EM, "real_data_only"),
    (make_inv("case_em"), {"CO": 2.5, "NOX": 0.0}, "no_notable_emissions"),
])
def test_requires_human_otherwise(inv, emissions, failed):
    d = autonomy.decide(inv, emissions=emissions)
    assert d.decision == "requires_human"
    assert failed in {c.name for c in d.conditions if not c.passed}
    assert "Human review required" in d.reason


def test_decisions_persisted_idempotent_counts_and_reopen():
    a = autonomy.decide(make_inv("case_a"), emissions=NO_EM)
    b = autonomy.decide(make_inv("case_b", synthetic=True), emissions=NO_EM)
    assert autonomy.decide(make_inv("case_a"), emissions=NO_EM).decision_id == a.decision_id  # idempotent
    assert {d.decision_id for d in db.list_decisions()} == {a.decision_id, b.decision_id}
    assert db.decision_counts() == {"auto_triaged_no_action": 1, "requires_human": 1, "human_override_reopened": 0,
                                    "total": 2}
    r = autonomy.reopen(a.decision_id, "shift_supervisor", "want a second look")
    assert r.decision == "human_override_reopened" and r.supersedes == a.decision_id and r.actor == "shift_supervisor"
    assert db.decision_counts()["auto_triaged_no_action"] == 0 and db.decision_counts()["human_override_reopened"] == 1
    with pytest.raises(autonomy.ConflictError):
        autonomy.reopen(a.decision_id, "x", None)  # already superseded
    with pytest.raises(autonomy.ConflictError):
        autonomy.reopen(b.decision_id, "x", None)  # requires_human cannot be "reopened"
    with pytest.raises(KeyError):
        autonomy.reopen("dec_missing", "x", None)


def test_apply_autonomy_policy_never_raises():
    assert autonomy.apply_autonomy_policy(object()) is None


# ----------------------------------------------------------------------------- B. activity feed
def test_activity_feed_aggregates_and_orders(tmp_db):
    from app.features.collab import activity
    from app.features.ops.handover import HandoverStore, generate_handover
    from app.plant import store as plant_store
    from app.plant import work_requests
    from app.plant.schemas import WhatIfRequest, WhatIfSession

    inv = make_inv("case_feed1", severity="review", review="accepted")
    wr = work_requests.create_for_investigation(inv)
    assert wr is not None
    work_requests.update_status(wr.id, "acknowledged", "on it", "performance_engineer")
    autonomy.decide(inv, emissions=NO_EM)
    plant_store.save_session(WhatIfSession(
        session_id="wi_test1", created_at_utc=ts(40), status="completed", persona="performance_engineer",
        request=WhatIfRequest(case_id="case_feed1", question="what if AT rises?", measurement="AT", delta=1.0),
        mode="offline", mode_label="offline (no Meta call)", meta_used=False, base_window={}))
    plant_store.save_session(WhatIfSession(
        session_id="wi_other", created_at_utc=ts(41), status="completed", persona="ic_engineer",
        request=WhatIfRequest(case_id="case_other", measurement="AT", delta=1.0),
        mode="offline", mode_label="offline", meta_used=False, base_window={}))
    generate_handover(hours=24, persona="shift_supervisor", investigations=[inv], client=None, store=HandoverStore(),
                      now=T0 + timedelta(hours=1))
    res = activity.case_activity("case_feed1", lambda cid: {"case_feed1": inv}[cid])
    kinds = [i.kind for i in res.items]
    for k in ("investigation_created", "agent_tool_calls", "validator", "precedents_recalled", "report_accepted",
              "investigation_completed", "review_decision", "work_request_created", "work_request_status",
              "notification", "auto_decision", "whatif_session", "handover_note"):
        assert k in kinds, k
    stamps = [datetime.fromisoformat(i.ts_utc.replace("Z", "+00:00")) for i in res.items]
    assert stamps == sorted(stamps)
    assert all(s for s in res.sources.values())
    assert not any("wi_other" in i.summary for i in res.items)
    actors = {i.kind: (i.actor, i.actor_kind) for i in res.items}
    assert actors["work_request_status"] == ("performance_engineer", "persona")
    assert actors["review_decision"] == ("demo-engineer", "human")
    assert actors["work_request_created"][1] == "agent"
    with pytest.raises(KeyError):
        activity.case_activity("case_nope", lambda cid: {}[cid])


def test_activity_feed_missing_tables_is_empty_not_error(tmp_db):
    from app.features.collab import activity

    res = activity.case_activity("case_solo", lambda cid: make_inv("case_solo"))
    assert res.sources["notifications"] is False and res.sources["whatif_sessions"] is False
    assert res.sources["handover_notes"] is False
    assert res.sources["work_requests"] is False
    assert {i.kind for i in res.items} >= {"investigation_created", "investigation_completed"}


# ----------------------------------------------------------------------------- C. dependency graph
FAKE_STATS = {
    "years": [2011, 2012, 2013],
    "corr": {a: {b: (1.0 if a == b else 0.0) for b in ("AT", "AP", "AH", "AFDP", "GTEP", "TIT", "TAT", "TEY", "CDP",
                                                         "CO", "NOX")}
             for a in ("AT", "AP", "AH", "AFDP", "GTEP", "TIT", "TAT", "TEY", "CDP", "CO", "NOX")},
}
FAKE_STATS["corr"]["AFDP"]["TEY"] = FAKE_STATS["corr"]["TEY"]["AFDP"] = 0.65
FAKE_STATS["corr"]["AT"]["AP"] = FAKE_STATS["corr"]["AP"]["AT"] = -0.41
FAKE_STATS["corr"]["AT"]["AH"] = FAKE_STATS["corr"]["AH"]["AT"] = 0.39  # below threshold
FAKE_STATS["cov"] = {a: {b: (4.0 if a == b else FAKE_STATS["corr"][a][b] * 4.0) for b in FAKE_STATS["corr"][a]}
                     for a in FAKE_STATS["corr"]}


@pytest.fixture
def fake_stats(monkeypatch):
    monkeypatch.setattr(dependencies, "get_training_stats", lambda: FAKE_STATS)


def test_dependency_graph_nodes_edges_and_domino_path(fake_stats):
    inv = make_inv("case_intake", synthetic=True, severity="review", hypothesis="intake_restriction",
                   evidence=[ev("ev_afdp_01", "AFDP", 4.2), ev("ev_tey_residual_01", "TEY_residual", -2.5)])
    g = dependencies.build_graph("case_intake", None, None, lambda cid: inv)
    ids = {n.id for n in g.nodes}
    assert {"s:intake", "s:compressor", "s:combustion_turbine", "s:exhaust_emissions", "s:generator_output"} <= ids
    assert {f"m:{m}" for m in ("AT", "AP", "AH", "AFDP", "CDP", "TIT", "TAT", "TEY", "GTEP", "CO", "NOX")} <= ids
    phys = [(e.source, e.target) for e in g.edges if e.kind == "physical"]
    assert ("s:intake", "s:compressor") in phys and ("s:combustion_turbine", "s:generator_output") in phys
    stat = {frozenset((e.source, e.target)): e for e in g.edges if e.kind == "statistical"}
    assert set(stat) == {frozenset(("m:AFDP", "m:TEY")), frozenset(("m:AT", "m:AP"))}  # |r| >= 0.4 only
    e = stat[frozenset(("m:AFDP", "m:TEY"))]
    assert e.r == 0.65 and e.slope == 0.65 and "not causation" in e.label
    assert g.implicated.measurement == "AFDP" and g.implicated.subsystem == "intake"
    assert g.domino_path[:4] == ["m:AFDP", "s:intake", "s:compressor", "s:combustion_turbine"]
    assert set(g.domino_path[4:]) == {"s:exhaust_emissions", "s:generator_output"}
    nodes = {n.id: n for n in g.nodes}
    assert nodes["m:AFDP"].implicated and nodes["s:intake"].implicated and nodes["m:TEY"].stat_neighbour
    assert not nodes["m:AT"].on_path and nodes["s:compressor"].on_path
    assert {(e.source, e.target) for e in g.edges if e.on_path} >= {("m:AFDP", "s:intake"), ("s:intake", "s:compressor")}
    assert g.synthetic is True and "not causation" in g.caveat and g.training_years == [2011, 2012, 2013]
    assert nodes["s:intake"].owner_persona == "mechanical_maintenance_engineer" and nodes["s:intake"].what_to_check


def test_dependency_graph_whatif_annotation_and_errors(fake_stats, monkeypatch):
    calls = []

    def fake_sim(m, d, case_id):
        calls.append((m, d, case_id))
        return {"delta": d, "unit": "mbar", "model_effect": {"applicable": True, "delta_tey_mean": -0.12345,
                                                             "delta_tey_min": -0.3, "delta_tey_max": 0.0,
                                                             "note": "MODEL-DERIVED"},
                "train_range_check": {"ood_flag": False}}

    monkeypatch.setattr(dependencies, "simulate", fake_sim)
    g = dependencies.build_graph(None, "AFDP", 1.0)
    assert calls == [("AFDP", 1.0, None)]
    assert g.whatif.delta_tey_mean == -0.1235 and g.whatif.applicable and "MODEL-DERIVED" in g.whatif.label
    assert g.implicated.measurement == "AFDP" and g.domino_path[0] == "m:AFDP"
    plain = dependencies.build_graph()
    assert plain.implicated is None and plain.domino_path == [] and plain.whatif is None
    with pytest.raises(ValueError):
        dependencies.build_graph(None, "XYZ", None)
    with pytest.raises(ValueError):
        dependencies.build_graph(None, None, 1.0)


def test_what_to_check_wording_is_read_only():
    texts = [t for items in dependencies.WHAT_TO_CHECK.values() for t in items]
    texts += [a.action + " " + a.why for a in autonomy.ACTIONS if a.level != "human_only"]
    for t in texts:
        hits = [label for label, pat in UNSAFE_PATTERNS if pat.search(t)]
        assert not hits, (t, hits)


# ----------------------------------------------------------------------------- D. onboarding
class FakeMetaClient:
    configured = True
    model = "muse-spark-1.3"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages, tools, max_tokens, response_format=None):
        self.calls.append({"messages": [dict(m) for m in messages], "max_tokens": max_tokens})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return ChatResult(message={"role": "assistant", "content": r if isinstance(r, str) else json.dumps(r)},
                          usage={"total_tokens": 50}, latency_ms=5, model=self.model, finish_reason="stop")


def good_brief(**over) -> dict:
    d = {"role_summary": "You keep CDP, AFDP and TIT readings trustworthy for the ic_engineer role.",
         "how_the_plant_works": [{"subsystem": "compressor", "explanation": "Raises air pressure; CDP measured."}],
         "what_you_watch": [{"measurement": "CDP", "why": "Unit under validation; transmitter checks."}],
         "who_you_work_with": [{"persona": "shift_supervisor", "when": "Approves field calibration work."}],
         "current_open_items": ["case_open1"],
         "first_week_checklist": ["Day 1: read the inbox and the review checks of case_open1."],
         "disclaimer": "model wording"}
    d.update(over)
    return d


INVS = [make_inv("case_open1", synthetic=True, severity="review", hypothesis="sensor_issue")]


def test_onboarding_meta_accepted_and_persisted():
    fake = FakeMetaClient([good_brief()])
    b = onboarding.generate_brief("ic_engineer", client=fake, investigations=INVS, work_requests=[])
    assert b.mode == "meta_live" and b.meta_used and b.meta_calls == 1 and not b.rewrite_used
    assert fake.calls[0]["max_tokens"] == 8000
    assert b.brief.disclaimer == ONBOARDING_DISCLAIMER and b.badge == ONBOARDING_BADGE  # server-owned wording
    assert db.latest_brief("ic_engineer").brief_id == b.brief_id
    ctx = json.loads(fake.calls[0]["messages"][1]["content"].split("\n", 1)[1])
    assert ctx["persona"]["persona_id"] == "ic_engineer" and ctx["persona"]["supervisor"] == "shift_supervisor"


def test_onboarding_rejected_then_rewrite_accepted():
    bad = good_brief(current_open_items=["case_invented"])
    fake = FakeMetaClient([bad, good_brief()])
    b = onboarding.generate_brief("ic_engineer", client=fake, investigations=INVS, work_requests=[])
    assert b.mode == "meta_live" and b.rewrite_used and b.meta_calls == 2
    assert any("case_invented" in e for e in b.validation_errors)
    assert "case_invented" in fake.calls[1]["messages"][-1]["content"]


def test_onboarding_rejected_twice_falls_back():
    unsafe = good_brief(first_week_checklist=["Day 1: close the bypass valve and set the setpoint."])
    dated = good_brief(who_you_work_with=[{"persona": "night_watch_engineer", "when": "Monday at 14:00"}],
                       how_the_plant_works=[{"subsystem": "boiler", "explanation": "x"}])
    fake = FakeMetaClient([unsafe, dated])
    b = onboarding.generate_brief("ic_engineer", client=fake, investigations=INVS, work_requests=[])
    assert b.mode == "offline_fallback" and not b.meta_used and b.meta_calls == 2
    assert "rejected" in b.source_label and b.fallback_reason == "Meta brief rejected after one bounded rewrite"
    errs = " ".join(b.validation_errors)
    for frag in ("unsafe_instruction", "unknown persona ids", "unknown subsystem ids", "fabricated_date"):
        assert frag in errs, frag
    ok, fb_errs = onboarding.validate_brief(b.brief.model_dump(), {"case_open1"})
    assert ok is not None, fb_errs
    assert b.brief.first_week_checklist and b.brief.role_summary.startswith("Instrumentation")


def test_onboarding_offline_and_meta_error_fallbacks():
    b = onboarding.generate_brief("environmental_engineer", client=None, investigations=INVS, work_requests=[])
    assert b.mode == "offline_fallback" and b.meta_calls == 0 and b.fallback_reason == "Meta client not configured"
    assert {w.measurement for w in b.brief.what_you_watch} == {"CO", "NOX", "GTEP"}
    b2 = onboarding.generate_brief("ic_engineer", client=FakeMetaClient([MetaClientError("Meta API rate limited (429)")]),
                                   investigations=INVS, work_requests=[])
    assert b2.mode == "offline_fallback" and "429" in b2.fallback_reason
    with pytest.raises(KeyError):
        onboarding.generate_brief("nobody", client=None, investigations=INVS, work_requests=[])


# ----------------------------------------------------------------------------- HTTP
@pytest.fixture
def http(monkeypatch, fake_stats):
    invs = {i.case_id: i for i in [make_inv("case_http1"), make_inv("case_http2", synthetic=True, severity="review")]}
    monkeypatch.setattr(collab_router, "get_investigation", lambda cid: invs[cid])
    monkeypatch.setattr(collab_router, "get_investigations", lambda: list(invs.values()))
    monkeypatch.setattr(collab_router, "get_meta_client", lambda: None)
    monkeypatch.setattr(autonomy, "_emissions_z", lambda inv: NO_EM)
    app = FastAPI()
    app.include_router(collab_router.router, prefix="/api")
    return TestClient(app)


def test_http_routes_404_422(http):
    r = http.get("/api/collab/policy")
    assert r.status_code == 200 and r.json()["counts"]["total"] == 0
    r = http.post("/api/collab/policy/apply-existing")
    assert r.status_code == 200 and r.json()["applied"] == 2
    assert http.post("/api/collab/policy/apply-existing").json() == {"applied": 0, "already_decided": 2, "decisions": []}
    counts = http.get("/api/collab/policy").json()["counts"]
    assert counts == {"auto_triaged_no_action": 1, "requires_human": 1, "human_override_reopened": 0, "total": 2}
    decs = http.get("/api/collab/decisions", params={"case_id": "case_http1"}).json()["decisions"]
    assert len(decs) == 1 and decs[0]["decision"] == "auto_triaged_no_action"
    r = http.post(f"/api/collab/decisions/{decs[0]['decision_id']}/reopen", json={"comment": "check"},
                  headers={"X-Persona": "shift_supervisor"})
    assert r.status_code == 200 and r.json()["actor"] == "shift_supervisor"
    assert http.post(f"/api/collab/decisions/{decs[0]['decision_id']}/reopen").status_code == 409
    assert http.post("/api/collab/decisions/dec_nope/reopen").status_code == 404
    r = http.get("/api/collab/cases/case_http1/activity")
    assert r.status_code == 200 and any(i["kind"] == "auto_decision" for i in r.json()["items"])
    assert http.get("/api/collab/cases/case_nope/activity").status_code == 404
    assert http.get("/api/collab/cases/bad id!/activity").status_code == 422
    r = http.get("/api/collab/dependency-graph", params={"case_id": "case_http2"})
    assert r.status_code == 200 and r.json()["domino_path"]
    assert http.get("/api/collab/dependency-graph", params={"case_id": "case_nope"}).status_code == 404
    assert http.get("/api/collab/dependency-graph", params={"measurement": "XYZ"}).status_code == 422
    assert http.get("/api/collab/dependency-graph", params={"delta": 1}).status_code == 422
    assert http.get("/api/collab/onboarding", params={"persona": "ic_engineer"}).json()["brief"] is None
    r = http.post("/api/collab/onboarding", json={"persona": "ic_engineer"})
    assert r.status_code == 200 and r.json()["mode"] == "offline_fallback" and r.json()["badge"] == ONBOARDING_BADGE
    assert http.get("/api/collab/onboarding", params={"persona": "ic_engineer"}).json()["brief"]["brief_id"] == r.json()["brief_id"]
    assert http.post("/api/collab/onboarding", json={"persona": "nobody"}).status_code == 404
    assert http.post("/api/collab/onboarding", json={}).status_code == 422
    assert http.get("/api/collab/onboarding", params={"persona": "nobody"}).status_code == 404
    assert http.get("/api/collab/onboarding").status_code == 422
