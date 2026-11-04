"""Plant-ops layer tests: routing, work requests, inbox, sensitivity, what-if (offline + scripted fake Meta),
reviewed-precedent memory, and the orchestrator's extra-tool hook. No network."""
from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from app import services
from app.agent.meta_client import ChatResult
from app.plant import store, whatif
from app.plant.memory import SIGNATURE_IDS, cosine, recall_similar, signature
from app.plant.personas import PERSONAS, ROUTING_TABLE, route
from app.plant.schemas import WhatIfAnswer, WhatIfRequest
from app.plant.sensitivity import BaseWindow, simulate_change
from app.plant.subsystems import SUBSYSTEM_REGISTRY
from app.plant.work_requests import rank1_hypothesis, recipients
from app.schemas import Evidence, InvestigationRequest, SampleRange

DS = "ds_uci_551"
START, END = 100, 220  # fixture has 300 rows per year


@pytest.fixture(scope="module")
def case(client):
    """One real (offline) investigation through the full pipeline -> the services hook creates a work request."""
    req = InvestigationRequest(dataset_id=DS, scenario_id="S02_INTAKE_RESTRICTION", year=2014,
                               start_index=START, end_index=END, use_meta=False)
    return services.run_investigation_pipeline(req)


@pytest.fixture
def offline_api(monkeypatch):
    import app.api.plant as plant_api

    monkeypatch.setattr(plant_api, "_client", lambda: None)  # never call the real Meta API from tests


# ----------------------------------------------------------------------------- routing / work requests
def test_routing_table_rules():
    assert route("intake_restriction")["assignee"] == "mechanical_maintenance_engineer"
    assert route("intake_restriction")["supervisor"] == "shift_supervisor"
    assert set(route("intake_restriction")["cc"]) == {"reliability_engineer", "hse_officer"}
    assert route("sensor_issue")["assignee"] == "ic_engineer"
    assert route("operating_condition") == ROUTING_TABLE["operating_condition"]
    assert route("operating_condition")["assignee"] == "performance_engineer"
    assert route("unknown")["assignee"] == "reliability_engineer"
    assert route("something_new")["assignee"] == "reliability_engineer"  # unmapped -> default
    assert route(None)["supervisor"] == "shift_supervisor"
    for rule in ROUTING_TABLE.values():  # every referenced persona exists
        assert {rule["assignee"], rule["supervisor"], *rule["cc"]} <= set(PERSONAS)
    assert PERSONAS["oem_field_service"].external is True


def test_escalations_urgent_hot_gas_path_and_operator():
    ev = [Evidence(evidence_id="ev_tit_01", case_id="c", kind="real_observation", metric="TIT", unit="°C",
                   title="t", sample_range=SampleRange(source_year=2014, start=0, end=10), observed_stat=1.0,
                   comparison_stat=0.0, z_score=3.4, method="m", computation="c")]
    inv = SimpleNamespace(evidence=ev, request=SimpleNamespace(dataset_id="missing"), window=None, reference=None)
    rule, reasons = recipients(inv, "intake_restriction", "urgent_review")
    order = list(reasons)
    assert order[:2] == ["mechanical_maintenance_engineer", "shift_supervisor"]
    assert "plant_manager" in reasons and "urgent_review" in reasons["plant_manager"]
    assert "oem_field_service" in reasons and "ev_tit_01" in reasons["oem_field_service"]
    assert "hse_officer" in reasons and "control_room_operator" in reasons
    _, calm = recipients(SimpleNamespace(evidence=[], request=SimpleNamespace(dataset_id="missing")), "sensor_issue",
                         "review")
    assert "plant_manager" not in calm and "oem_field_service" not in calm and "hse_officer" not in calm


def test_work_request_created_when_investigation_completes(case):
    assert case.status == "completed" and case.mode == "offline_preview"
    wrs = store.list_work_requests(case_id=case.case_id)
    assert len(wrs) == 1
    wr = wrs[0]
    key = rank1_hypothesis(case)
    assert wr.routed_by == f"rule:{key}" and wr.assigned_persona == route(key)["assignee"]
    assert wr.supervisor_persona == route(key)["supervisor"] and wr.status == "open"
    assert wr.checks == case.report.engineer_review_checks
    assert wr.synthetic is True and wr.delivery == "in_app_simulated"
    assert "no email/SMS/paging" in wr.delivery_note
    assert wr.assignment_label.startswith("Assigned to ") and "Supervisor" in wr.assignment_label
    for pid in (wr.assigned_persona, wr.supervisor_persona):
        notes = [n for n in store.list_notifications(pid) if n.work_request_id == wr.id]
        assert len(notes) == 1 and notes[0].kind == "work_request" and notes[0].delivery == "in_app_simulated"
    # idempotent: calling the hook again does not duplicate
    from app.plant.work_requests import on_investigation_completed

    on_investigation_completed(case)
    assert len(store.list_work_requests(case_id=case.case_id)) == 1


def test_inbox_per_persona(client, case):
    wr = store.list_work_requests(case_id=case.case_id)[0]
    r = client.get(f"/api/plant/inbox?persona={wr.assigned_persona}")
    assert r.status_code == 200
    body = r.json()
    assert any(w["id"] == wr.id for w in body["work_requests"]) and body["unread_count"] >= 1
    assert "Simulated in-app notification" in body["delivery_note"]
    r2 = client.get("/api/plant/inbox", headers={"X-Persona": wr.supervisor_persona})
    assert any(w["id"] == wr.id for w in r2.json()["work_requests"])  # supervisor sees it too
    r3 = client.get("/api/plant/inbox?persona=electrical_engineer")
    assert all(w["id"] != wr.id for w in r3.json()["work_requests"])
    assert client.get("/api/plant/inbox?persona=nobody").status_code == 404
    personas = client.get("/api/plant/personas").json()
    assert len(personas["personas"]) == 11 and personas["default_persona"] == "reliability_engineer"


def test_work_request_status_transitions(client, case):
    wr = store.list_work_requests(case_id=case.case_id)[0]
    url = f"/api/plant/work-requests/{wr.id}/status"
    r = client.post(url, json={"status": "acknowledged", "comment": "on my way"},
                    headers={"X-Persona": wr.assigned_persona})
    assert r.status_code == 200 and r.json()["status"] == "acknowledged"
    assert r.json()["history"][-1]["persona"] == wr.assigned_persona
    assert client.post(url, json={"status": "open"}).status_code == 409
    assert client.post(url, json={"status": "done", "comment": "filter house inspected"}).status_code == 200
    assert client.post(url, json={"status": "dismissed"}).status_code == 409  # final
    assert client.post(url, json={"status": "bogus"}).status_code == 422
    assert client.post("/api/plant/work-requests/wr_nope/status", json={"status": "done"}).status_code == 404
    n = store.list_notifications(wr.assigned_persona)[0]
    assert client.post(f"/api/plant/notifications/{n.id}/read").json()["read"] is True


# ----------------------------------------------------------------------------- sensitivity
class LinearModel:
    """Deterministic fake baseline: TEY = 100 - 2*AFDP + 0.1*TIT; narrow AFDP training range for OOD tests."""
    version = "fake_linear"
    features = ["AT", "AP", "AH", "AFDP", "GTEP", "TIT", "TAT", "CDP"]
    evaluation = SimpleNamespace(feature_ranges_train={"AFDP": [0.0, 4.6], "TIT": [0.0, 2000.0]})

    def predict(self, frame):
        return 100 - 2 * frame["AFDP"].to_numpy(float) + 0.1 * frame["TIT"].to_numpy(float)


def test_simulate_change_deterministic_ood_and_correlation_shape(trained_model):
    base = BaseWindow(DS, 2014, START, END, None, "test window")
    a = simulate_change("AFDP", 0.5, base, LinearModel())
    b = simulate_change("AFDP", 0.5, base, LinearModel())
    assert a == b
    me = a["model_effect"]
    assert me["applicable"] and me["delta_tey_mean"] == pytest.approx(-1.0, abs=1e-6)
    assert me["delta_tey_min"] == pytest.approx(-1.0, abs=1e-6) and me["delta_tey_max"] == pytest.approx(-1.0, abs=1e-6)
    items = a["co_movement"]["items"]
    assert len(items) == 10 and all(-1.0 <= i["pearson_r"] <= 1.0 for i in items if i["pearson_r"] is not None)
    assert "not causation" in a["co_movement"]["label"] and a["co_movement"]["training_years"] == [2011, 2012, 2013]
    assert abs(items[0]["pearson_r"]) >= abs(items[-1]["pearson_r"])
    big = simulate_change("AFDP", 2.0, base, LinearModel())
    assert big["train_range_check"]["ood_flag"] is True and big["train_range_check"]["rows_outside"] > 0
    assert simulate_change("AFDP", 0.0, base, LinearModel())["train_range_check"]["within_training_range"] in (True, False)
    co = simulate_change("CO", 1.0, base, LinearModel())
    assert co["model_effect"]["applicable"] is False and "not an input" in co["model_effect"]["note"]
    with pytest.raises(ValueError):
        simulate_change("AFDP", 1e6, base, LinearModel())
    with pytest.raises(ValueError):
        simulate_change("FOO", 1.0, base, LinearModel())


# ----------------------------------------------------------------------------- what-if offline
def test_whatif_offline_fallback_validates_and_persists(case):
    s = whatif.run_whatif(WhatIfRequest(case_id=case.case_id, measurement="AFDP", delta=0.5, question="what if?"),
                          None, persona="mechanical_maintenance_engineer")
    assert s.status == "completed" and s.mode == "offline" and s.mode_label == "offline (no Meta call)"
    assert s.meta_used is False and s.agents == []
    ans = WhatIfAnswer.model_validate(s.answer.model_dump())
    assert ans.how_it_works and ans.how_it_works[0].subsystem == "intake" and ans.how_it_works[0].source
    assert ans.recommended_next_steps and all(x.requires_supervisor_approval for x in ans.recommended_next_steps)
    assert len(ans.subsystem_assessments) == len(SUBSYSTEM_REGISTRY)
    assert all(a.owner_label.startswith("owner: ") for a in ans.subsystem_assessments)
    assert whatif.scan_texts(whatif.answer_texts(ans)) == []
    assert store.get_session(s.session_id).status == "completed"


def test_whatif_api_offline_and_errors(client, case, offline_api):
    r = client.post("/api/plant/whatif?wait=true", json={"case_id": case.case_id, "measurement": "TIT", "delta": 5},
                    headers={"X-Persona": "ic_engineer"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "offline" and body["persona"] == "ic_engineer" and body["answer"]["change"]["unit"] == "°C"
    assert client.get(f"/api/plant/whatif/{body['session_id']}").json()["session_id"] == body["session_id"]
    assert client.post("/api/plant/whatif", json={"measurement": "XX", "delta": 1}).status_code == 422
    assert client.post("/api/plant/whatif", json={"case_id": "case_nope", "measurement": "AFDP", "delta": 1}
                       ).status_code == 404
    assert client.get("/api/plant/sensitivity?measurement=AFDP&delta=99").status_code == 422
    assert len(client.get("/api/plant/subsystems").json()) == len(SUBSYSTEM_REGISTRY)


# ----------------------------------------------------------------------------- what-if with a scripted fake Meta
GOOD_AGG = {
    "effects_elsewhere": [{"subsystem": "compressor", "description": "CDP historically co-moves with AFDP.",
                           "direction": "increase", "magnitude_hint": "+0.46 mbar", "confidence": "low",
                           "tool_numbers_cited": ["co_movement CDP r=0.67"], "basis": "historical association"}],
    "recommended_next_steps": [{"action": "Inspect the filter elements per site procedure.", "kind": "inspect",
                                "subsystem": "intake", "rationale": "AFDP rise"},
                               "Verify the AFDP transmitter calibration."],
    "cross_impacts": [{"subsystems": ["intake", "compressor"], "description": "Shared air path.", "basis": "generic"}],
    "what_to_check_before_acting": ["Check the redundant AFDP channel."],
}
BAD_AGG = dict(GOOD_AGG, recommended_next_steps=[{"action": "Shutdown the turbine and bypass the filter.",
                                                  "kind": "inspect"}])


class ParallelFakeMeta:
    """Thread-safe scripted client: routes by the system prompt (subsystem agents vs aggregator)."""
    model = "fake-muse"
    configured = True

    def __init__(self, aggregator_replies: list[dict], agent_text: str | None = None):
        self.agg = list(aggregator_replies)
        self.agent_text = agent_text
        self.lock = threading.Lock()
        self.calls: list[dict] = []

    def chat(self, messages, tools, max_tokens, response_format=None):
        with self.lock:
            self.calls.append({"system": messages[0]["content"][:80], "tools": tools, "max_tokens": max_tokens})
        system = messages[0]["content"]
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        if system.startswith("You are the ThermoMind aggregator"):
            with self.lock:
                reply = self.agg.pop(0)
            return ChatResult(message={"role": "assistant", "content": json.dumps(reply)}, usage=usage,
                              latency_ms=3, model=self.model, finish_reason="stop")
        key = system.split("(", 1)[1].split(")", 1)[0]
        if tools:  # round 1: call the pre-bound deterministic tool
            return ChatResult(message={"role": "assistant", "content": None, "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "simulate_change",
                                                              "arguments": json.dumps({"measurement": "AFDP",
                                                                                       "delta": 0.5})}}]},
                usage=usage, latency_ms=3, model=self.model, finish_reason="tool_calls")
        text = self.agent_text or (f"impact on {key}: modelled ΔTEY small (from simulate_change)")
        return ChatResult(message={"role": "assistant", "content": json.dumps({
            "subsystem": key, "impact_summary": text, "direction": "no_clear_change",
            "magnitude_hint": "< 0.1 MWh", "confidence": "medium", "caveats": ["association, not causation"],
            "tool_numbers_cited": ["simulate_change.model_effect.delta_tey_mean"]})},
            usage=usage, latency_ms=3, model=self.model, finish_reason="stop")


def test_whatif_with_fake_meta_parallel_agents_validates(case):
    fake = ParallelFakeMeta([GOOD_AGG])
    s = whatif.run_whatif(WhatIfRequest(case_id=case.case_id, measurement="AFDP", delta=0.5, question="q"), fake)
    assert s.status == "completed" and s.mode == "meta_live" and s.meta_used is True, s.validation_errors
    agents = {a.agent: a for a in s.agents}
    assert set(agents) == {*(x["key"] for x in SUBSYSTEM_REGISTRY), "aggregator"}
    for sub in SUBSYSTEM_REGISTRY:
        run = agents[sub["key"]]
        assert run.ok and run.used_tools and run.tokens["total_tokens"] == 30
        assert [e.kind for e in run.events][:4] == ["model_request", "model_response", "tool_call", "tool_result"]
        assert run.assessment.owner_label.startswith("owner: ")
    assert all(c["max_tokens"] <= 5000 for c in fake.calls)
    ans = s.answer
    assert ans.effects_elsewhere[0].subsystem == "compressor"
    assert [x.kind for x in ans.recommended_next_steps] == ["inspect", "review"]
    assert all(x.requires_supervisor_approval for x in ans.recommended_next_steps)
    assert ans.how_it_works and ans.subsystem_assessments[0].confidence == "medium"


def test_whatif_rejects_control_language(case):
    fake = ParallelFakeMeta([BAD_AGG, BAD_AGG], agent_text="Close the inlet valve and trip the turbine.")
    s = whatif.run_whatif(WhatIfRequest(case_id=case.case_id, measurement="AFDP", delta=0.5), fake)
    assert s.status == "needs_review"
    assert any("unsafe_instruction" in e for e in s.validation_errors)
    agents = {a.agent: a for a in s.agents}
    assert all(not agents[x["key"]].ok for x in SUBSYSTEM_REGISTRY)  # every agent rejected after its rewrite
    # the shown answer is the labelled deterministic stand-in and is itself clean
    assert whatif.scan_texts(whatif.answer_texts(s.answer)) == []
    assert all("deterministic stand-in" in a.caveats[0] for a in s.answer.subsystem_assessments)


# ----------------------------------------------------------------------------- memory
def _inv(case_id, zs: dict, decision=None, comment=None):
    ev = [SimpleNamespace(evidence_id=k, z_score=v) for k, v in zs.items()]
    review = SimpleNamespace(decision=decision, reviewer="r", comment=comment, ts_utc="t") if decision else None
    return SimpleNamespace(case_id=case_id, evidence=ev, review=review, scenario_label="synthetic_overlay",
                           scenario=SimpleNamespace(scenario_id="S02", synthetic=True), report=None,
                           deterministic_summary={"top_hypotheses": [{"hypothesis_key": "intake_restriction"}]})


def test_signature_and_recall_similar_only_reviewed_ordered():
    assert len(signature([])) == len(SIGNATURE_IDS) and signature([]) == [0.0] * len(SIGNATURE_IDS)
    assert cosine([1, 0], [1, 0]) == pytest.approx(1.0) and cosine([0, 0], [1, 0]) == 0.0
    q = _inv("q", {"ev_afdp_01": 4, "ev_tey_residual_01": -3})
    invs = [q,
            _inv("near", {"ev_afdp_01": 3.9, "ev_tey_residual_01": -2.8}, "rejected", "sensor, not filter"),
            _inv("far", {"ev_at_01": 5}, "accepted"),
            _inv("mid", {"ev_afdp_01": 2, "ev_cdp_01": 2}, "more_data_requested"),
            _inv("unreviewed_twin", {"ev_afdp_01": 4, "ev_tey_residual_01": -3})]
    resp = recall_similar(case_id="q", investigations=invs, k=3)
    ids = [p.case_id for p in resp.precedents]
    assert ids == ["near", "mid", "far"] and "unreviewed_twin" not in ids and "q" not in ids
    assert resp.precedents[0].decision == "rejected" and resp.precedents[0].comment == "sensor, not filter"
    assert resp.precedents[0].rank1_hypothesis == "intake_restriction"
    assert resp.reviewed_cases_considered == 3 and "not ground truth" in resp.note
    sims = [p.similarity for p in resp.precedents]
    assert sims == sorted(sims, reverse=True)
    with pytest.raises(KeyError):
        recall_similar(case_id="missing", investigations=invs)


def test_precedents_endpoint(client, case):
    r = client.get(f"/api/plant/precedents?case_id={case.case_id}")
    assert r.status_code == 200 and r.json()["signature_ids"] == SIGNATURE_IDS
    assert client.get("/api/plant/precedents?case_id=case_nope").status_code == 404


# ----------------------------------------------------------------------------- orchestrator extra-tool hook
def test_orchestrator_dispatches_recall_similar_cases(client, case):
    from app.agent._fake_case import make_fake_analysis
    from app.agent.orchestrator import run_investigation
    from tests.test_agent_mock import FakeMetaClient, good_report, text_msg, tool_call_msg

    services.get_store().set_review(case.case_id, __import__("app.schemas", fromlist=["ReviewRecord"]).ReviewRecord(
        decision="rejected", reviewer="demo", comment="looked like a transmitter drift", ts_utc="2026-01-01T00:00:00Z"))
    required = [("get_baseline_comparison", {}), ("get_data_quality", {}),
                ("evaluate_hypothesis", {"hypothesis_key": "intake_restriction"})]
    fake = FakeMetaClient([tool_call_msg([("recall_similar_cases", {"k": 2}), *required]), text_msg(good_report())])
    out = run_investigation(make_fake_analysis(synthetic=True), "synthetic_overlay", fake)
    assert out.status == "completed", out.validation_errors
    names = [t["function"]["name"] for t in fake.calls[0]["tools"]]
    assert "recall_similar_cases" in names and names[0] == "get_sensor_window"
    assert "Precedent memory" in fake.calls[0]["messages"][0]["content"]
    tool_msgs = [m for m in fake.calls[1]["messages"] if m["role"] == "tool"]
    payload = json.loads(tool_msgs[0]["content"])
    assert payload["available"] is True and any(p["case_id"] == case.case_id for p in payload["precedents"])
    assert any(e.kind == "tool_call" and e.tool_name == "recall_similar_cases" for e in out.events)
    bad = FakeMetaClient([tool_call_msg([("recall_similar_cases", {"k": 99}), *required]), text_msg(good_report())])
    out2 = run_investigation(make_fake_analysis(synthetic=True), "synthetic_overlay", bad)
    assert any(e.tool_name == "recall_similar_cases" and not e.ok for e in out2.events)
