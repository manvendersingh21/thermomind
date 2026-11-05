"""Adversarial input fuzz for the four late packages (deliberation, watchdog, collab, executive).

Each POST gets NaN / inf / huge / negative / wrong-type / unknown-id payloads on a test-local app that includes the
four routers; every response must be a 4xx (or a 2xx with a finite, labelled body) -- never a 500. No network.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.features.collab import router as collab_router
from app.features.deliberation import router as delib_router
from app.features.executive import router as ex_router
from app.features.watchdog import monitor
from app.features.watchdog import router as wd_router

BAD_NUMS = ["NaN", "Infinity", "-Infinity", "1e400", "-1e400", "1e308", "-1", "-99999999999999999999", '"abc"',
            "null", "[]", "{}", "true"]


@pytest.fixture(scope="module")
def api(client):  # `client` (conftest) builds the temporary data/model/db environment
    from fastapi.exceptions import RequestValidationError

    from app.main import request_validation_error_handler

    app = FastAPI()
    # production's 422 handler (FastAPI's default one 500s when echoing a NaN input back as JSON)
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)
    for r in (delib_router.router, wd_router.router, collab_router.router, ex_router.router):
        app.include_router(r, prefix="/api")
    mp = pytest.MonkeyPatch()
    mp.setattr(delib_router, "_client", lambda: None)
    mp.setattr(collab_router, "get_meta_client", lambda: None)
    mp.setattr(ex_router, "get_meta_client", lambda: None)
    with TestClient(app, raise_server_exceptions=__import__('os').environ.get('FUZZ_RAISE') == '1') as c:
        yield c
    mp.undo()
    w = monitor.get_watchdog()
    w.stop()
    monitor._set_watchdog(None)


def _post(c, url, raw: str):
    return c.post(url, content=raw, headers={"Content-Type": "application/json"})


def _check(r, url, raw):
    assert r.status_code < 500, f"{url} {raw} -> {r.status_code} {r.text[:300]}"


def test_garbage_bodies_never_500(api):
    urls = ["/api/deliberation/propose?wait=true", "/api/deliberation/nope/decision", "/api/watchdog/run",
            "/api/collab/onboarding", "/api/collab/decisions/nope/reopen", "/api/executive/brief"]
    for url in urls:
        for raw in ["", "{", "null", "[]", '"x"', "1", "NaN", '{"a":' + "[" * 50 + "]" * 50 + "}"]:
            _check(_post(api, url, raw), url, raw)


def test_deliberation_propose_fuzz(api):
    url = "/api/deliberation/propose?wait=true"
    for field in ("year", "start", "end", "magnitude"):
        for v in BAD_NUMS:
            raw = '{"intent_id":"raise_load","%s":%s}' % (field, v)
            _check(_post(api, url, raw), url, raw)
    for raw in ['{"intent_id":"no_such_intent"}', '{"case_id":"nope"}', '{"case_id":"../../etc"}',
                '{"dataset_id":"nope","intent_id":"raise_load"}',
                '{"custom":{"text":"abc","deltas":{"AT":NaN}}}', '{"custom":{"text":"abc","deltas":{"AT":1e308}}}',
                '{"custom":{"text":"abc","deltas":{"NOPE":1}}}', '{"custom":{"text":"abc","deltas":{"AT":"x"}}}',
                '{"intent_id":"raise_load","persona":"mallory"}', '{"intent_id":"raise_load","start":10,"end":5}',
                '{"intent_id":"raise_load","year":2014,"start":0,"end":100000000}']:
        r = _post(api, url, raw)
        _check(r, url, raw)


def test_deliberation_decision_fuzz(api):
    for raw in ['{"decision":"approve_plan"}', '{"decision":"execute"}', '{"decision":null}', "{}"]:
        r = _post(api, "/api/deliberation/does_not_exist/decision", raw)
        _check(r, "decision", raw)
        assert r.status_code in (404, 422)


def test_watchdog_run_fuzz(api):
    url = "/api/watchdog/run"
    for field in ("speed", "year", "start_index", "seed", "steps", "rate_per_min", "initial_severity", "mwh"):
        for v in BAD_NUMS:
            raw = '{"action":"start","%s":%s}' % (field, v)
            _check(_post(api, url, raw), url, raw)
            raw = '{"action":"demand_step","%s":%s}' % (field, v)
            _check(_post(api, url, raw), url, raw)
    api.post(url, json={"action": "stop"})
    for body in [{"action": "inject_fault", "asset": "../x", "fault": "bearing_degradation"},
                 {"action": "clear_fault", "asset": "NOPE"}, {"action": "tag_out", "asset": "NOPE", "tagged": True},
                 {"action": "decide", "task_id": "x" * 40, "decision": "approve"},
                 {"action": "decide", "task_id": "x", "decision": "execute"},
                 {"action": "set_policy", "auto_execute": "yes"}, {"action": "step", "steps": 36001}]:
        r = api.post(url, json=body)
        _check(r, url, body)
        assert 400 <= r.status_code < 500, (body, r.status_code)
    api.post(url, json={"action": "stop"})


def test_collab_fuzz(api):
    for raw in ['{"persona":"mallory"}', '{"persona":""}', '{"persona":1}', '{"persona":"' + "x" * 65 + '"}']:
        r = _post(api, "/api/collab/onboarding", raw)
        _check(r, "onboarding", raw)
        assert 400 <= r.status_code < 500
    for did in ["nope", "x" * 65, "a%20b"]:
        r = api.post(f"/api/collab/decisions/{did}/reopen", json={"comment": "x"})
        assert 400 <= r.status_code < 500
    for d in ["NaN", "inf", "-inf", "1e400", "abc"]:
        r = api.get(f"/api/collab/dependency-graph?measurement=TIT&delta={d}")
        _check(r, "graph", d)
    r = api.get("/api/collab/dependency-graph?measurement=NOPE&delta=1")
    _check(r, "graph", "NOPE")


def test_executive_fuzz(api):
    for v in BAD_NUMS:
        raw = '{"year":%s}' % v
        r = _post(api, "/api/executive/brief", raw)
        _check(r, "brief", raw)
    for raw in ['{"dataset_id":"nope"}', '{"year":2014,"extra":1}', '{"dataset_id":""}']:
        r = _post(api, "/api/executive/brief", raw)
        _check(r, "brief", raw)
        assert 400 <= r.status_code < 500, (raw, r.status_code)
    assert api.get("/api/executive/overview?year=1999").status_code == 422
    assert api.get("/api/executive/overview?dataset_id=nope").status_code in (404, 422)
    assert api.get("/api/executive/briefs/..%2F..").status_code == 404


# ----------------------------------------------------------------------------- control-language + honesty scan
from app.agent.report_validator import UNSAFE_PATTERNS  # noqa: E402

_HUMAN_ECHO = {"request", "comment"}  # verbatim human input echoed back (not model-written / deterministic)


def _unsafe(v, path="$"):
    if isinstance(v, dict):
        return [h for k, x in v.items() if k not in _HUMAN_ECHO for h in _unsafe(x, f"{path}.{k}")]
    if isinstance(v, list):
        return [h for i, x in enumerate(v) for h in _unsafe(x, f"{path}[{i}]")]
    if isinstance(v, str):
        return [(path, lab, v[:160]) for lab, pat in UNSAFE_PATTERNS if pat.search(v)]
    return []


def test_deterministic_texts_pass_unsafe_patterns_and_carry_labels(api):
    from app.features.watchdog.policy import HONESTY_STATEMENT

    bodies = {}
    intents = api.get("/api/deliberation/intents").json()
    bodies["intents"] = intents
    for it in intents:
        if it["intent_id"] == "custom":
            continue
        r = api.post("/api/deliberation/propose?wait=true", json={"intent_id": it["intent_id"], "year": 2014,
                                                                   "start": 100, "end": 220})
        assert r.status_code == 200, r.text[:300]
        s = r.json()
        assert "executes nothing" in s["banner"] and s["mode"] == "offline"
        bodies[f"propose_{it['intent_id']}"] = s
    d = api.post(f"/api/deliberation/{s['deliberation_id']}/decision", json={"decision": "approve_plan",
                                                                           "persona": "plant_manager"})
    assert d.status_code == 200 and d.json()["decisions"][-1]["executed"] is False
    bodies["decision"] = d.json()

    api.post("/api/watchdog/run", json={"action": "reset", "source": "simulator", "seed": 3})
    for asset, fault in (("CWP_A", "bearing_degradation"), ("CTF_2", "belt_slip")):
        api.post("/api/watchdog/run", json={"action": "inject_fault", "asset": asset, "fault": fault,
                                            "rate_per_min": 1.0, "initial_severity": 0.6})
    for _ in range(3):
        r = api.post("/api/watchdog/run", json={"action": "step", "steps": 600})
        assert r.status_code == 200 and r.json()["honesty_statement"] == HONESTY_STATEMENT
    st = api.get("/api/watchdog/state?history_points=600&n_events=500").json()
    assert st["simulated"] is True and st["honesty_statement"] == HONESTY_STATEMENT
    for ex in st.get("executions", []):  # anything executed is the simulated switchover class, labelled simulated
        assert ex["simulated"] is True and "SIMULATED" in ex["where"].upper()
    bodies["watchdog"] = st

    bodies["policy"] = api.get("/api/collab/policy").json()
    # the default what-if base window lies beyond the 300-row fixture -> must be a 422, never a 500
    assert api.get("/api/collab/dependency-graph?measurement=TIT&delta=5").status_code == 422
    bodies["graph"] = api.get("/api/collab/dependency-graph").json()
    ob = api.post("/api/collab/onboarding", json={"persona": "shift_supervisor"})
    assert ob.status_code == 200
    bodies["onboarding"] = ob.json()
    ov = api.get("/api/executive/overview?year=2014")
    assert ov.status_code == 200 and ov.json()["read_only"] is True
    bodies["overview"] = ov.json()
    br = api.post("/api/executive/brief", json={"year": 2014})
    assert br.status_code == 200
    bodies["brief"] = br.json()

    hits = [h for name, b in bodies.items() for h in _unsafe(b, name)]
    assert hits == [], hits[:10]
