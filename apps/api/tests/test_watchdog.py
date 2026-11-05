"""Watchdog tests: SIMULATED auxiliaries physics, detectors, policy routing, interlocks, deliberation fallbacks,
endpoints (422/404/409), SSE and the background thread. No network: Meta is faked or unconfigured."""
from __future__ import annotations

import json
import math
import time

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent.meta_client import ChatResult, MetaClientError
from app.agent.report_validator import UNSAFE_PATTERNS
from app.features.watchdog import auxiliaries as aux
from app.features.watchdog import deliberation as delib
from app.features.watchdog import monitor
from app.features.watchdog import policy as pol
from app.features.watchdog.router import router


class Unconfigured:
    configured = False


class FakeMetaClient:
    """Scripted MetaClient: returns the given contents in order, or raises MetaClientError."""

    configured = True
    model = "fake-muse"

    def __init__(self, contents=None, error: bool = False):
        self.contents = list(contents or [])
        self.error = error
        self.calls = []

    def chat(self, messages, tools, max_tokens, response_format=None):
        self.calls.append({"messages": messages, "max_tokens": max_tokens, "response_format": response_format})
        if self.error:
            raise MetaClientError("Meta API connection error")
        return ChatResult(message={"role": "assistant", "content": self.contents.pop(0)}, usage={"total_tokens": 1},
                          latency_ms=5, model=self.model, finish_reason="stop")


GOOD = json.dumps({
    "recommendation": "proceed_with_conditions",
    "summary": "The evidence supports the proposed switchover inside the simulated model; the standby is available.",
    "harms_elsewhere": [{"subsystem": "condenser", "effect": "A short flow transient is possible during changeover."}],
    "conditions": ["standby proven running before the duty pump leaves service"],
    "who_must_approve": ["shift_supervisor"],
})
UNSAFE = json.dumps({
    "recommendation": "proceed_with_conditions",
    "summary": "Start pump B immediately and shut down the unit if it fails.",
    "harms_elsewhere": [], "conditions": [], "who_must_approve": [],
})


def make(client=None, **kw) -> monitor.Watchdog:
    kw.setdefault("source", "nominal")
    return monitor.Watchdog(meta_client=client or Unconfigured(), deliberation_backend="builtin",
                            sync_deliberation=True, persist_notifications=False, **kw)


def run_until(w: monitor.Watchdog, pred, max_steps: int = 7200, chunk: int = 30) -> bool:
    for _ in range(max_steps // chunk):
        w.step_n(chunk)
        if pred(w):
            return True
    return False


def has_kind(kind):
    return lambda w: any(d["kind"] == kind for d in w.detections)


# ---------------------------------------------------------------------------------------------- physics
def test_steady_state_temperature_rises_with_load():
    spec = aux.SPEC_BY_ID["CWP_A"]
    rises = [aux.steady_state_rise_k(spec, r) for r in (0.5, 0.8, 1.0)]
    assert rises[0] < rises[1] < rises[2]
    assert rises[2] == pytest.approx(spec.rated_rise_k)  # rated current -> rated (class-B) rise
    temps = []
    for d in (0.4, 1.0):
        m = aux.AuxiliariesModel(ambient_c=15.0)
        m.set_demand(d, d)
        m._settle()
        temps.append(m.motors["CWP_A"].winding_c)
    assert temps[1] > temps[0] + 10


def test_first_order_time_constant():
    tau = 1500.0
    theta = 40.0
    for _ in range(int(tau)):
        theta = aux.first_order_step(theta, 140.0, tau, 1.0)
    assert (theta - 40.0) / 100.0 == pytest.approx(1 - math.exp(-1), abs=1e-6)  # 63.2 % after one τ
    t = aux.time_to_reach_s(40.0, 140.0, 103.2120558, tau)
    assert t == pytest.approx(tau, rel=1e-4)
    assert aux.time_to_reach_s(40.0, 120.0, 155.0, tau) is None


def test_bearing_fault_raises_current_temperature_and_vibration():
    healthy, faulty = aux.AuxiliariesModel(seed=3), aux.AuxiliariesModel(seed=3)
    faulty.inject_fault("CWP_A", "bearing_degradation", rate_per_min=0.05, seed=1)
    for _ in range(900):
        healthy.step()
        faulty.step()
    h, f = healthy.motors["CWP_A"], faulty.motors["CWP_A"]
    assert f.current_a > h.current_a * 1.10
    assert f.winding_c > h.winding_c + 5
    assert f.vibration_mm_s > h.vibration_mm_s + 2
    # deterministic for a given seed
    again = aux.AuxiliariesModel(seed=3)
    again.inject_fault("CWP_A", "bearing_degradation", rate_per_min=0.05, seed=1)
    for _ in range(900):
        again.step()
    assert again.motors["CWP_A"].winding_c == pytest.approx(f.winding_c)


def test_belt_slip_lowers_fan_current_and_airflow():
    m = aux.AuxiliariesModel()
    i0 = m.motors["CTF_2"].current_a
    m.inject_fault("CTF_2", "belt_slip", rate_per_min=1.0, seed=2, initial_severity=0.5)
    m.step()
    assert m.motors["CTF_2"].current_a < 0.7 * i0
    assert m.group_capacity("ct_fans") < 1.0
    with pytest.raises(ValueError):
        m.inject_fault("CWP_A", "belt_slip")


# ---------------------------------------------------------------------------------------------- interlocks
def test_interlock_blocks_starting_tagged_out_standby():
    m = aux.AuxiliariesModel()
    m.set_tag_out("CWP_B", True)
    ok, reasons = m.can_start("CWP_B")
    assert not ok and "tagged out" in reasons[0]
    with pytest.raises(aux.InterlockError):
        m.request_switchover("cooling_water", "CWP_B", "CWP_A", "sw_t")
    assert m.motors["CWP_A"].state == "running" and m.motors["CWP_B"].state == "standby"
    with pytest.raises(aux.InterlockError):  # cannot tag out a running motor
        m.set_tag_out("CWP_A", True)


def test_minimum_flow_interlock_and_switchover_sequence():
    m = aux.AuxiliariesModel()
    with pytest.raises(aux.InterlockError, match="minimum flow"):
        m.stop("CWP_A")
    sw = m.request_switchover("cooling_water", "CWP_B", "CWP_A", "sw_t")
    assert m.motors["CWP_A"].running  # duty stays until the standby proves running
    for _ in range(10):
        m.step()
    assert sw.phase == "completed"
    assert m.motors["CWP_B"].state == "running" and m.motors["CWP_A"].state == "stopped"


# ---------------------------------------------------------------------------------------------- detectors
def test_overheat_detector_fires_with_time_to_limit():
    w = make()
    w.step_n(120)
    w.inject_fault("CWP_A", "bearing_degradation", 0.05, 11, 0.0)
    assert run_until(w, has_kind("auxiliary_overheating"))
    det = next(d for d in w.detections if d["kind"] == "auxiliary_overheating")
    n = det["evidence"]["numbers"]
    assert det["asset"] == "CWP_A" and det["severity"] in ("warning", "high", "critical")
    assert n["time_to_limit_conservative_s"] is not None and n["time_to_limit_conservative_s"] > 0
    assert n["winding_c"] < n["alarm_c"]  # early warning: fires on the trend, before the alarm
    assert n["current_excess_pct"] >= 5
    assert det["evidence"]["provenance"] and det["proposed_action"]["action_class"] == "simulated_auxiliary_switchover"
    assert "start standby cooling-water pump B" in det["proposed_action"]["intent"]


def test_healthy_plant_raises_no_detection():
    w = make()
    w.step_n(3600)
    assert list(w.detections) == []


def test_capability_shortfall_is_human_required_and_never_executed():
    w = make()
    w.set_demand_step(60.0)
    assert run_until(w, has_kind("capability_shortfall"), max_steps=300)
    det = next(d for d in w.detections if d["kind"] == "capability_shortfall")
    assert det["evidence"]["numbers"]["shortfall_mwh"] > 1
    assert "bring second unit online" in det["proposed_action"]["intent"]
    task = next(t for t in w.human_tasks if t["detection_id"] == det["id"])
    assert task["status"] == "awaiting_human" and task["policy_id"] == "WD-POL-020"
    assert {"shift_supervisor", "control_room_operator"} <= set(task["notified"])
    assert list(w.executions) == []
    out = w.decide(task["id"], "approve", "plant_manager", "dispatch informed")
    assert "nothing executed on any plant" in out["decision"]["outcome"]
    assert list(w.executions) == []


# ---------------------------------------------------------------------------------------------- policy
def test_policy_matrix():
    on, off = pol.PolicyConfig(True), pol.PolicyConfig(False)
    sw = "simulated_auxiliary_switchover"
    assert pol.decide(sw, "proceed_with_conditions", on).route == "auto_execute_simulated"
    assert pol.decide(sw, "hold_for_human", on).route == "human_required"
    assert pol.decide(sw, "do_not_proceed", on).route == "human_required"
    assert pol.decide(sw, "proceed_with_conditions", off).route == "human_required"
    for cls in ("unit_commitment", "redispatch_request", "auxiliary_maintenance", "investigation_request",
                "real_plant_action", "anything_else"):
        r = pol.decide(cls, "proceed_with_conditions", on)
        assert r.route == "human_required"
        assert "shift_supervisor" in r.notify
    assert pol.HONESTY_STATEMENT == ("Auto-execution exists only inside the simulated auxiliaries model. "
                                     "ThermoMind has no write path to any real plant.")


def test_auto_execution_only_in_simulator_with_notifications():
    w = make()
    w.step_n(120)
    w.inject_fault("CWP_A", "bearing_degradation", 0.05, 11, 0.0)
    assert run_until(w, lambda x: any(e["status"] == "completed" for e in x.executions))
    ex = next(iter(w.executions))
    assert ex["where"] == "SIMULATED auxiliaries subsystem" and ex["policy_id"] == "WD-POL-001"
    assert ex["reversible"] is True and ex["simulated"] is True
    assert {"control_room_operator", "shift_supervisor"} <= set(ex["notified"])
    assert w.aux.motors["CWP_B"].state == "running" and w.aux.motors["CWP_A"].state == "stopped"
    assert {n["persona"] for n in w.outbox} >= {"control_room_operator", "shift_supervisor"}
    types = [e["type"] for e in w.events]
    for t in ("detection", "proposal", "deliberation", "execution", "notification"):
        assert t in types


def test_policy_off_routes_switchover_to_human_and_approval_executes_in_simulator():
    w = make()
    w.set_policy(False)
    w.step_n(120)
    w.inject_fault("CWP_A", "bearing_degradation", 0.05, 11, 0.0)
    assert run_until(w, lambda x: len(x.human_tasks) > 0)
    assert list(w.executions) == []
    task = w.human_tasks[0]
    assert task["policy_id"] == "WD-POL-002"
    out = w.decide(task["id"], "approve", "shift_supervisor", None)
    assert "WD-POL-003" in out["decision"]["outcome"]
    assert w.executions[0]["approved_by"] == "shift_supervisor"
    with pytest.raises(ValueError):
        w.decide(task["id"], "reject", "shift_supervisor", None)


def test_tagged_out_standby_blocks_auto_execution_and_escalates():
    w = make()
    w.tag_out("CWP_B", True)
    w.step_n(120)
    w.inject_fault("CWP_A", "bearing_degradation", 0.05, 11, 0.0)
    assert run_until(w, lambda x: len(x.executions) > 0)
    assert w.executions[0]["status"] == "blocked_by_interlock"
    assert "tagged out" in w.executions[0]["interlocks"][0]
    assert w.human_tasks and w.human_tasks[0]["status"] == "awaiting_human"
    assert w.aux.motors["CWP_B"].state == "standby"


# ---------------------------------------------------------------------------------------------- deliberation
def _det_prop():
    det = {"kind": "auxiliary_overheating", "asset": "CWP_A", "severity": "high", "rationale": "r",
           "evidence": {"numbers": {"winding_c": 100}}}
    prop = {"intent": "start standby cooling-water pump B and take pump A out of service",
            "action_class": "simulated_auxiliary_switchover", "magnitude": 1.0,
            "params": {"group": "cooling_water", "start": "CWP_B", "stop": "CWP_A"}, "responsible": ["x"]}
    return det, prop


def test_deliberation_fake_meta_valid_answer_is_used():
    det, prop = _det_prop()
    fake = FakeMetaClient([GOOD])
    res = delib.deliberate(det, prop, {}, client=fake, backend="builtin")
    assert res["mode"] == "meta_live" and res["validated"]
    assert res["answer"]["recommendation"] == "proceed_with_conditions"
    assert len(fake.calls) == 1 and fake.calls[0]["max_tokens"] == 6000
    assert fake.calls[0]["response_format"] == {"type": "json_object"}


def test_deliberation_unsafe_answer_is_rejected_and_held_for_human():
    det, prop = _det_prop()
    res = delib.deliberate(det, prop, {}, client=FakeMetaClient([UNSAFE]), backend="builtin")
    assert res["mode"] == "meta_live_rejected" and not res["validated"]
    assert res["answer"]["recommendation"] == "hold_for_human"
    assert any("unsafe-pattern" in e for e in res["errors"])
    texts = delib.answer_texts(delib.DeliberationAnswer.model_validate(res["answer"]))
    assert not delib.unsafe_hits(texts)
    assert UNSAFE_PATTERNS  # the shared scanner is really in use


def test_deliberation_falls_back_when_meta_unavailable():
    det, prop = _det_prop()
    res = delib.deliberate(det, prop, {}, client=FakeMetaClient(error=True), backend="builtin")
    assert res["mode"] == "offline_fallback" and "Meta error" in res["mode_label"]
    res2 = delib.deliberate(det, prop, {}, client=Unconfigured(), backend="builtin")
    assert res2["mode"] == "offline_fallback" and "offline (no Meta call)" in res2["mode_label"]
    assert res2["answer"]["recommendation"] == "proceed_with_conditions"
    assert not delib.unsafe_hits(delib.answer_texts(delib.offline_answer(det, prop)))


def test_rejected_meta_answer_blocks_auto_execution_end_to_end():
    w = make(client=FakeMetaClient([UNSAFE] * 5))
    w.step_n(120)
    w.inject_fault("CWP_A", "bearing_degradation", 0.05, 11, 0.0)
    assert run_until(w, lambda x: len(x.human_tasks) > 0)
    assert list(w.executions) == []
    assert w.proposals[0]["deliberation"]["mode"] == "meta_live_rejected"


# ---------------------------------------------------------------------------------------------- data source
def test_replay_source_via_simulated_historian():
    n = 30
    frame = pd.DataFrame({"source_year": 2014, "row_index": np.arange(n), "TEY": np.linspace(120, 150, n),
                          "AT": np.full(n, 20.0), **{k: np.ones(n) for k in
                                                    ("AP", "AH", "AFDP", "GTEP", "TIT", "TAT", "CDP", "CO", "NOX")}})
    w = monitor.Watchdog(source="replay", start_index=0, frame_provider=lambda y: frame, meta_client=Unconfigured(),
                         deliberation_backend="builtin", sync_deliberation=True, persist_notifications=False)
    assert w.source.kind == "uci_replay" and w.source.row["row_index"] == 0
    assert w.aux.cooling_demand == pytest.approx(120 / aux.UNIT_RATED_MWH, rel=1e-3)
    w.step_n(3600)
    assert w.source.row["row_index"] == 1
    assert w.state()["source"]["time_axis"] == "ordered_hourly_sample_without_actual_timestamp"


# ---------------------------------------------------------------------------------------------- API
@pytest.fixture()
def api():
    w = make()
    monitor._set_watchdog(w)
    app = FastAPI()
    app.include_router(router, prefix="/api")
    with TestClient(app) as c:
        yield c, w
    monitor._set_watchdog(None)


def test_endpoints_reject_bad_input(api):
    c, _ = api
    assert c.post("/api/watchdog/run", json={"action": "explode"}).status_code == 422
    assert c.post("/api/watchdog/run", json={"action": "start", "speed": 0}).status_code == 422
    assert c.post("/api/watchdog/run", json={"action": "start", "speed": 10_000}).status_code == 422
    assert c.post("/api/watchdog/run", json={"action": "inject_fault", "asset": "NOPE",
                                             "fault": "bearing_degradation"}).status_code == 422
    assert c.post("/api/watchdog/run", json={"action": "inject_fault", "asset": "CWP_A",
                                             "fault": "meltdown"}).status_code == 422
    assert c.post("/api/watchdog/run", json={"action": "inject_fault", "asset": "CWP_A",
                                             "fault": "belt_slip"}).status_code == 422
    assert c.post("/api/watchdog/run", json={"action": "demand_step"}).status_code == 422
    assert c.post("/api/watchdog/run", json={"action": "set_policy"}).status_code == 422
    assert c.post("/api/watchdog/run", json={"action": "tag_out", "asset": "CWP_A", "tagged": True}).status_code == 409
    assert c.post("/api/watchdog/run", json={"action": "decide", "task_id": "hum_x",
                                             "decision": "approve"}).status_code == 404
    assert c.post("/api/watchdog/run", json={"action": "decide", "task_id": "hum_x", "decision": "approve",
                                             "persona": "mallory"}).status_code == 422
    assert c.get("/api/watchdog/events?n=0").status_code == 422
    assert c.get("/api/watchdog/events?n=100000").status_code == 422
    assert c.get("/api/watchdog/stream?interval_s=0.1").status_code == 422  # > 2 Hz refused


def test_endpoints_happy_path(api):
    c, w = api
    r = c.post("/api/watchdog/run", json={"action": "step", "steps": 60})
    assert r.status_code == 200 and r.json()["sim_time_s"] == 60
    assert c.post("/api/watchdog/run", json={"action": "inject_fault", "asset": "CWP_A",
                                             "fault": "bearing_degradation", "rate_per_min": 0.05}).status_code == 200
    assert c.post("/api/watchdog/run", json={"action": "set_policy", "auto_execute": False}).status_code == 200
    s = c.get("/api/watchdog/state").json()
    assert s["simulated"] is True and s["honesty_statement"] == pol.HONESTY_STATEMENT
    assert s["policy"]["auto_execute_simulated_switchover"] is False
    assert {m["asset_id"] for m in s["auxiliaries"]["motors"]} == set(aux.SPEC_BY_ID)
    ev = c.get("/api/watchdog/events?n=5").json()
    assert ev["events"] and ev["last_seq"] >= len(ev["events"])


def test_sse_stream_yields_state_events(api):
    c, _ = api
    with c.stream("GET", "/api/watchdog/stream?max_events=2&interval_s=0.5") as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    chunks = [b for b in body.split("\n\n") if b.strip()]
    assert len(chunks) == 2
    data = json.loads(chunks[0].split("data: ", 1)[1])
    assert data["simulated"] is True and "auxiliaries" in data


def test_background_thread_starts_and_stops_cleanly():
    w = make()
    w.start(speed=600)
    time.sleep(0.6)
    assert w.running
    assert w.stop(timeout=3.0) is True
    assert not w.running
    t = w.aux.t_s
    assert t > 50
    time.sleep(0.2)
    assert w.aux.t_s == t  # nothing advances after stop
    w.shutdown()


def test_buffers_are_bounded():
    w = make()
    for i in range(monitor.BUF["events"] + 50):
        w.set_demand_step(float(i % 3))
    assert len(w.events) == monitor.BUF["events"]
    assert w.aux.motors["CWP_A"].history.maxlen == aux.HISTORY_LEN
