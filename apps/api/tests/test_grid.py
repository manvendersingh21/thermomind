"""Tests for app.features.grid (readiness, S05 drill, Meta brief validation, contingency options, endpoints)."""
from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import services
from app.agent.meta_client import ChatResult, MetaClientError
from app.data.uci_loader import load_csv_files
from app.features.grid import drill as dm
from app.features.grid import readiness as rd
from app.features.grid import router as grid_router
from app.features.grid.schemas import (
    BRIEF_DISCLAIMER,
    CONTINGENCY_DISCLAIMER,
    ContingencyAssumptions,
    ContingencyRequest,
    DrillRequest,
    GridBrief,
)

FIXTURE = Path(__file__).resolve().parents[3] / "data" / "fixtures" / "gt_2014_sample300.csv"


@pytest.fixture(scope="module")
def bundle():
    data = FIXTURE.read_bytes()
    # 2011 copy acts as the training year, 2014 as the analysis year (300 real rows each).
    return load_csv_files([("gt_2011.csv", data), ("gt_2014.csv", data)], source="TEST_FIXTURE")


class FakeMetaClient:
    model = "fake-muse"

    def __init__(self, scripted: list, raise_on: int | None = None):
        self.scripted = list(scripted)
        self.calls: list[dict] = []
        self.raise_on = raise_on

    @property
    def configured(self) -> bool:
        return True

    def chat(self, messages, tools, max_tokens, response_format=None):
        self.calls.append({"messages": [dict(m) for m in messages], "max_tokens": max_tokens,
                           "response_format": response_format})
        if self.raise_on is not None and len(self.calls) == self.raise_on:
            raise MetaClientError("Meta API error 503: upstream unavailable")
        content = self.scripted.pop(0)
        return ChatResult(message={"role": "assistant", "content": content},
                          usage={"prompt_tokens": 100, "completion_tokens": 50}, latency_ms=7, model=self.model,
                          finish_reason="stop")


def good_brief(**over) -> str:
    b = {
        "headline": "Synthetic load-step drill: TEY step -12% on 2014 samples #100-#119",
        "what_the_data_shows": ["Step-window mean TEY fell by 12.0% versus the original copy."],
        "operator_verifications": ["Verify the required response per grid code.", "Check TIT trend.",
                                   "Confirm with dispatch/TSO.", "Monitor exhaust pressure."],
        "plant_capability": ["Inertia capability about 941 MW·s (assumption)."],
        "notify": ["TSO/dispatch", "Shift supervisor", "Electrical engineer"],
        "risks": ["Synthetic overlay; hourly data cannot show second-scale dynamics."],
        "disclaimer": "No setpoint or control action is issued by this software.",
    }
    b.update(over)
    return json.dumps(b)


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------


def test_electrical_assumption_math():
    s = rd.apparent_power_mva(160, 0.8)
    assert s == pytest.approx(200.0)
    assert rd.kinetic_energy_mws(5, s) == pytest.approx(1000.0)
    assert rd.reactive_at_rated_mvar(160, 0.8) == pytest.approx(120.0)  # 160 * tan(acos 0.8) = 160 * 0.75
    assert rd.reactive_circle_headroom_mvar(200, 160) == pytest.approx(120.0)
    assert rd.reactive_circle_headroom_mvar(100, 150) == 0.0


def test_readiness_numbers_and_provenance(bundle):
    r = rd.compute_readiness(bundle, 2014, 0, 300, nameplate_mw=160, h_constant_s=5, power_factor=0.8)
    yf = bundle.year_frame(2014)
    train = bundle.frame[bundle.frame["source_year"] == 2011]
    n = r.numbers
    assert r.training_years == [2011]
    assert n["output_proxy_mean"].value == pytest.approx(round(yf["TEY"].mean(), 2))
    assert n["headroom_to_nameplate"].value == pytest.approx(round(160 - yf["TEY"].mean(), 2))
    assert n["kinetic_energy_mws"].value == pytest.approx(1000.0)
    assert n["tit_p99_train"].value == pytest.approx(round(float(train["TIT"].quantile(0.99)), 1), abs=0.11)
    assert n["tit_margin_to_p99"].value == pytest.approx(
        round(float(train["TIT"].quantile(0.99)) - yf["TIT"].max(), 1), abs=0.11)
    # provenance labels
    for k in ("output_proxy_mean", "tit_window_max", "afdp_window_median", "at_window_mean"):
        assert n[k].provenance == "real_observation", k
    for k in ("tit_p99_train", "tit_margin_to_p99", "afdp_percentile_vs_train"):
        assert n[k].provenance == "derived_from_history", k
    for k in ("headroom_to_nameplate", "apparent_power_mva", "kinetic_energy_mws", "q_rated_mvar",
              "q_headroom_proxy_mvar"):
        assert n[k].provenance == "assumption", k
    assert n["tey_at_slope"].provenance == "model_derived"
    assert "not an OEM limit" in n["tit_p99_train"].note
    assert all(c.computation for c in r.cards) and {c.key for c in r.cards} >= {"inertia", "thermal_tit", "ambient_at"}
    assert r.assumptions.h_typical_range_s == [2.5, 6.0] and "doi:10.1016/j.rser.2019.109369" in r.assumptions.h_reference
    assert r.charts.nameplate_mw == 160 and len(r.charts.tey) == 300


# ---------------------------------------------------------------------------
# Drill overlay + brief
# ---------------------------------------------------------------------------


def test_overlay_never_mutates_input_and_steps_tey(bundle):
    window = bundle.window(2014, 0, 120)
    before = window.copy(deep=True)
    train, _, _ = rd.training_frame(bundle.frame)
    slopes = dm.coupling_slopes(train)
    res = dm.apply_grid_event(window, slopes, seed=7)
    pd.testing.assert_frame_equal(window, before)
    assert res.synthetic is True and res.scenario_id == "S05_GRID_EVENT" and res.seed == 7
    lo, hi = dm.step_rows(120)
    assert hi - lo == 20
    ratio = res.frame["TEY"].to_numpy()[lo:hi] / window["TEY"].to_numpy()[lo:hi]
    assert ratio == pytest.approx([0.88] * 20)
    pd.testing.assert_series_equal(res.frame["TEY"].iloc[:lo], window["TEY"].iloc[:lo])
    d_tey = res.frame["TEY"].to_numpy()[lo] - window["TEY"].to_numpy()[lo]
    d_tit = res.frame["TIT"].to_numpy()[lo] - window["TIT"].to_numpy()[lo]
    assert d_tit == pytest.approx(slopes["TIT"][0] * d_tey)
    assert slopes["TIT"][0] > 0 and slopes["CDP"][0] > 0  # TIT/CDP rise with TEY in training data


def test_offline_brief_validates(bundle):
    d = dm.run_drill(bundle, DrillRequest(dataset_id=bundle.dataset_id, year=2014, start=0, end=120))
    assert d.mode == "offline_preview" and d.brief_source == "deterministic_offline" and not d.meta_used
    assert d.brief.headline.startswith("[OFFLINE DETERMINISTIC]")
    brief, errs = dm.validate_brief(d.brief.model_dump())
    assert errs == [] and isinstance(brief, GridBrief)
    assert d.evidence.tey_step_delta_pct == pytest.approx(-12.0, abs=0.01)
    assert d.synthetic and d.report_status == "draft_requires_human_review"


def test_fake_meta_happy_path(bundle):
    client = FakeMetaClient([good_brief()])
    d = dm.run_drill(bundle, DrillRequest(dataset_id=bundle.dataset_id, year=2014, start=0, end=120, use_meta=True),
                     client=client)
    assert d.mode == "meta_live" and d.meta_used and d.meta_model == "fake-muse"
    assert len(client.calls) == 1 and client.calls[0]["max_tokens"] == dm.META_MAX_TOKENS == 9000
    assert client.calls[0]["messages"][0]["content"].startswith("You are ThermoMind's grid-event operator-support agent")
    assert d.brief.disclaimer == BRIEF_DISCLAIMER


def test_unsafe_phrase_rejected_then_fallback(bundle):
    bad = good_brief(operator_verifications=["Verify grid code.", "Check that the operator should open the bypass valve."])
    bad2 = good_brief(what_the_data_shows=["Raise the setpoint by 5 MW."], operator_verifications=["Adjust fuel now."])
    _, errs = dm.validate_brief(bad)
    assert any("unsafe_instruction" in e for e in errs)
    client = FakeMetaClient([bad, bad2])
    d = dm.run_drill(bundle, DrillRequest(dataset_id=bundle.dataset_id, year=2014, start=0, end=120, use_meta=True),
                     client=client)
    assert len(client.calls) == 2  # one call + exactly one rewrite
    assert "failed validation" in client.calls[1]["messages"][-1]["content"]
    assert d.mode == "offline_fallback" and not d.meta_used and d.validation_errors
    assert any(e.kind == "rewrite_requested" for e in d.events) and any(e.kind == "fallback" for e in d.events)


def test_rewrite_recovers_and_verb_and_date_rules(bundle):
    client = FakeMetaClient([good_brief(risks=["Operators should bypass the interlock."]), good_brief()])
    d = dm.run_drill(bundle, DrillRequest(dataset_id=bundle.dataset_id, year=2014, start=0, end=120, use_meta=True),
                     client=client)
    assert len(client.calls) == 2 and d.mode == "meta_live" and d.validation_errors  # first attempt's errors kept
    _, errs = dm.validate_brief(good_brief(operator_verifications=["Increase output to 150 MW."]))
    assert any("must start with one of" in e for e in errs)
    _, errs = dm.validate_brief(good_brief(headline="Drill for the event on 28 April 2025 replayed"))
    assert any("fabricated_date" in e for e in errs)
    _, errs = dm.validate_brief("not json at all")
    assert errs and "not a JSON object" in errs[0]


# ---------------------------------------------------------------------------
# Contingency
# ---------------------------------------------------------------------------


def test_contingency_coverage_math():
    a = ContingencyAssumptions(nameplate_mw=160, ss_a_spare_mw=40, ss_b_spare_mw=25, line_a_rating_mw=120,
                               line_b_rating_mw=80, share_to_a=0.5, second_unit_available_mw=10,
                               tso_redispatch_assumed_mw=5, min_stable_mw=100)
    opts = {o.option_id: o for o in rd.enumerate_options(30.0, 120.0, "transformer_thermal", a, tit_margin=4.0)}
    assert opts["unit_partial_derate"].covered_mw == pytest.approx(20.0)  # output 120 - min stable 100
    assert opts["second_unit_shift"].covered_mw == pytest.approx(10.0)
    assert opts["tso_redispatch"].covered_mw == pytest.approx(5.0)
    # SS-A min(40, 120-60=60)=40, SS-B min(25, 80-60=20)=20 -> 60, capped at shortfall 30
    assert opts["substation_spare"].covered_mw == pytest.approx(30.0)
    assert opts["substation_spare"].residual_shortfall_mw == 0.0
    assert all(o.who_to_notify == ["dispatch/TSO", "shift_supervisor", "electrical_engineer"] for o in opts.values())


def test_contingency_ranking_by_residual_then_dependency():
    a = ContingencyAssumptions(second_unit_available_mw=50, min_stable_mw=0)  # TSO default covers full request
    opts = rd.enumerate_options(10.0, 130.0, "transformer_thermal", a, tit_margin=None)
    assert [o.rank for o in opts] == [1, 2, 3, 4]
    assert all(o.residual_shortfall_mw == 0 for o in opts)
    assert [o.external_dependency for o in opts] == ["plant_internal", "site", "network_operator", "tso_external"]
    a2 = ContingencyAssumptions(second_unit_available_mw=0, ss_a_spare_mw=0, ss_b_spare_mw=0,
                                tso_redispatch_assumed_mw=3)
    opts2 = rd.enumerate_options(10.0, 130.0, "unit_derate", a2, tit_margin=None)
    assert opts2[0].option_id == "tso_redispatch" and opts2[0].residual_shortfall_mw == pytest.approx(7.0)
    assert residuals_sorted(opts2)


def residuals_sorted(opts):
    r = [o.residual_shortfall_mw for o in opts]
    return r == sorted(r)


def test_contingency_no_option_cases(bundle):
    res = rd.compute_contingency(bundle, ContingencyRequest(dataset_id=bundle.dataset_id, year=2014, start=0, end=300,
                                                            shortfall_mw=0.0))
    assert res.status == "no_shortfall" and res.options == [] and res.simulated is True
    a = ContingencyAssumptions(second_unit_available_mw=0, ss_a_spare_mw=0, ss_b_spare_mw=0, tso_redispatch_assumed_mw=0,
                               severity_pct=50)
    res2 = rd.compute_contingency(bundle, ContingencyRequest(dataset_id=bundle.dataset_id, year=2014, start=0, end=300,
                                                             constraint="unit_derate", assumptions=a))
    assert res2.shortfall_mw > 0 and res2.status == "not_covered"
    assert all(not o.applicable and o.covered_mw == 0 for o in res2.options)
    assert res2.disclaimer == CONTINGENCY_DISCLAIMER
    with pytest.raises(ValueError):
        rd.compute_contingency(bundle, ContingencyRequest(dataset_id=bundle.dataset_id))


def test_contingency_option_text_passes_unsafe_scan():
    a = ContingencyAssumptions(second_unit_available_mw=20)
    for constraint in ("transformer_thermal", "line_limit", "unit_derate"):
        for o in rd.enumerate_options(25.0, 140.0, constraint, a, tit_margin=1.5):
            texts = [o.title, o.description, o.computation, *o.prerequisites, *o.who_to_notify]
            for t in texts:
                assert dm.scan_text(t) == [], (constraint, t)
    assert dm.scan_text("open the bypass valve") != []  # the scanner itself works


# ---------------------------------------------------------------------------
# Endpoints (test-local app)
# ---------------------------------------------------------------------------


class _Repo:
    def __init__(self, b):
        self.b = b

    def get(self, dataset_id):
        if dataset_id != self.b.dataset_id:
            raise KeyError(f"dataset '{dataset_id}' not found")
        return self.b


@pytest.fixture
def api(bundle, tmp_path, monkeypatch):
    monkeypatch.setattr(services, "get_repo", lambda: _Repo(bundle))
    app = FastAPI()
    app.include_router(grid_router.router, prefix="/api")
    store = dm.DrillStore(tmp_path / "grid.db")
    fake = FakeMetaClient([good_brief()])
    app.dependency_overrides[grid_router.get_drill_store] = lambda: store
    app.dependency_overrides[grid_router.get_grid_meta_client] = lambda: fake
    with TestClient(app) as c:
        yield c, bundle.dataset_id, fake


def test_endpoint_shapes(api):
    c, ds, fake = api
    r = c.get("/api/grid/readiness", params={"dataset_id": ds, "year": 2014, "start": 0, "end": 300})
    assert r.status_code == 200, r.text
    body = r.json()
    assert {"numbers", "cards", "summary", "charts", "assumptions", "disclaimer"} <= set(body)
    assert body["numbers"]["kinetic_energy_mws"]["provenance"] == "assumption"
    r = c.post("/api/grid/drill", json={"dataset_id": ds, "year": 2014, "start": 0, "end": 120,
                                        "event": "overvoltage", "use_meta": True})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["mode"] == "meta_live" and d["banner"].startswith("Synthetic drill. Advisory only.")
    assert d["evidence"]["synthetic"] is True and len(d["series"]) == 4
    assert c.get(f"/api/grid/drills/{d['drill_id']}").json()["drill_id"] == d["drill_id"]
    assert [x["drill_id"] for x in c.get("/api/grid/drills").json()] == [d["drill_id"]]
    r = c.post("/api/grid/contingency", json={"dataset_id": ds, "year": 2014, "start": 0, "end": 300,
                                              "constraint": "unit_derate"})
    assert r.status_code == 200, r.text
    cj = r.json()
    assert cj["simulated"] is True and cj["disclaimer"] == CONTINGENCY_DISCLAIMER and len(cj["topology"]) == 7


def test_endpoint_errors(api):
    c, ds, _ = api
    q = {"dataset_id": ds, "year": 2014}
    assert c.get("/api/grid/readiness", params={**q, "start": 0, "end": 10}).status_code == 422  # < 24 rows
    assert c.get("/api/grid/readiness", params={**q, "start": 0, "end": 999}).status_code == 422
    assert c.get("/api/grid/readiness", params={**q, "power_factor": 1.5}).status_code == 422
    assert c.get("/api/grid/readiness", params={**q, "nameplate_mw": -1}).status_code == 422
    assert c.get("/api/grid/readiness", params={"dataset_id": "nope", "year": 2014}).status_code == 404
    assert c.get("/api/grid/readiness", params={"dataset_id": ds, "year": 2099}).status_code == 404
    base = {"dataset_id": ds, "year": 2014, "start": 0, "end": 120}
    assert c.post("/api/grid/drill", json={**base, "event": "earthquake"}).status_code == 422
    assert c.post("/api/grid/drill", json={**base, "end": 30}).status_code == 422  # < 48 rows
    assert c.post("/api/grid/contingency", json=base).status_code == 422  # neither shortfall nor constraint
    assert c.post("/api/grid/contingency", json={**base, "constraint": "meteor"}).status_code == 422
    assert c.get("/api/grid/drills/drill_missing").status_code == 404


# ---------------------------------------------------------------------------
# Security review fixes: grid/electrical control patterns (F2), evaluative option wording (F3), input bounds (F5)
# ---------------------------------------------------------------------------

# Review repro: a model brief that passes the allowed-verb rule on the first word but chains grid control actions.
REPRO_BRIEF = {
    "headline": "Synthetic frequency-dip drill: TEY step -12% on 2014 samples #100-#119",
    "what_the_data_shows": ["Step-window mean TEY 120.1 MWh vs original 136.5 MWh (-12.0%)."],
    "operator_verifications": [
        "Verify the frequency deviation; transfer load to the second unit.",
        "Check TIT then rack out the generator breaker.",
        "Confirm dispatch agreement and run the unit at 120 MW.",
        "Monitor voltage and raise excitation if it sags.",
        "Communicate to the TSO: request TSO re-dispatch for 60 MW.",
    ],
    "plant_capability": ["Inertia capability (assumption): about 1000 MW·s."],
    "notify": ["TSO / dispatch"],
    "risks": ["The overlay is synthetic."],
    "disclaimer": "No setpoint or control action is issued by this software.",
}

GRID_CONTROL_TEXTS = [
    "Transfer load to Unit 2.", "Shed 20 MW of load.", "Unload the unit.", "Back down the unit to minimum load.",
    "Take the unit offline.", "Bring the unit online.", "Rack out the breaker.", "Rack in the generator breaker.",
    "Run the unit at 120 MW.", "Raise excitation.", "Lower the excitation.", "Adjust the AVR voltage reference setpoint.",
    "Block the governor.", "Governor block.", "Isolate Line A.", "Disconnect the GSU.",
    "Isolate the step-up transformer.", "Disconnect the feeder.", "Ramp down to 100 MW.", "Ramp up to 150 MW.",
    "Request TSO re-dispatch for 60 MW.", "Request re-dispatch.", "Set reactive power to 40 Mvar.",
    "Increase MVAr output to 50 Mvar.", "Operators should request TSO re-dispatch for 60 MW.",
]

ALLOWED_TEXTS = [
    "Evaluate requesting TSO re-dispatch for ~60 MW (TSO decision)",
    "Options to evaluate (human review)",
    "Higher ambient temperature would reduce output.",
    "Consider escalating to dispatch/TSO (human decision).",
    "Evaluate a lower operating point for this unit (operator/dispatch decision)",
    "Confirm with dispatch/TSO whether any instruction applies to this unit.",
    "Escalate to the electrical engineer if voltage or reactive-power behaviour is reported by the TSO.",
    "No switching, load transfer or dispatch change is performed by this software.",
    "Evaluate whether to request TSO re-dispatch.",
    "Reactive capability proxy (assumption): about 132 Mvar circle headroom at the window-mean output.",
]


@pytest.mark.parametrize("text", GRID_CONTROL_TEXTS)
def test_grid_control_phrases_are_rejected(text):
    assert dm.scan_text(text) != [], text


@pytest.mark.parametrize("text", ALLOWED_TEXTS)
def test_descriptive_and_evaluative_phrases_are_allowed(text):
    assert dm.scan_text(text) == [], text


def test_review_repro_brief_is_rejected():
    brief, errs = dm.validate_brief(json.dumps(REPRO_BRIEF))
    assert brief is None
    joined = "\n".join(errs)
    # ';' / 'then' chained clauses must each start with an allowed verb
    assert "operator_verifications[0]" in joined and "operator_verifications[1]" in joined
    assert "unsafe_instruction" in joined
    for i in range(5):
        assert f"operator_verifications[{i}]" in joined, (i, joined)


def test_verification_split_keeps_allowed_chains():
    ok = good_brief(operator_verifications=["Verify the event classification; confirm with dispatch/TSO.",
                                            "Check unit output then communicate the step to the shift supervisor."])
    brief, errs = dm.validate_brief(ok)
    assert brief is not None, errs


def test_contingency_option_wording_is_evaluative(bundle):
    req = ContingencyRequest(dataset_id="x", year=2014, start=0, end=300, constraint="line_limit",
                             assumptions=ContingencyAssumptions(severity_pct=60))
    res = rd.compute_contingency(bundle, req)
    titles = {o.option_id: o.title for o in res.options}
    assert titles["tso_redispatch"].startswith("Evaluate requesting TSO re-dispatch for ~")
    assert titles["tso_redispatch"].endswith("(TSO decision)")
    assert titles["unit_partial_derate"] == "Evaluate a lower operating point for this unit (operator/dispatch decision)"
    res2 = rd.compute_contingency(bundle, ContingencyRequest(
        dataset_id="x", year=2014, start=0, end=300, shortfall_mw=5000,
        assumptions=ContingencyAssumptions(tso_redispatch_assumed_mw=0, ss_a_spare_mw=0, ss_b_spare_mw=0)))
    assert "consider escalating to dispatch/TSO (human decision)" in res2.headline, res2.headline
    for o in res.options:
        for t in (o.title, o.description, o.computation, *o.prerequisites):
            assert dm.scan_text(t) == [], t


def test_readiness_derived_provenance(bundle):
    n = rd.compute_readiness(bundle, 2014, 0, 300).numbers
    for k in ("tit_margin_to_p99", "afdp_percentile_vs_train", "tit_p99_train"):
        assert n[k].provenance == "derived_from_history", k


def _finite_422(c):
    from fastapi.exceptions import RequestValidationError

    from app.main import request_validation_error_handler

    c.app.add_exception_handler(RequestValidationError, request_validation_error_handler)
    c.app.middleware_stack = None  # rebuild so the handler applies to an already-started test app


@pytest.mark.parametrize("patch", [
    {"nameplate_mw": "Infinity"}, {"nameplate_mw": "NaN"}, {"nameplate_mw": 1e308}, {"seed": 2**31},
    {"seed": -1}, {"year": 1999}, {"year": 2101}, {"start": 100_001}, {"end": 10**20}, {"h_constant_s": float("inf")},
])
def test_drill_rejects_non_finite_and_huge(api, patch):
    c, ds, _ = api
    _finite_422(c)
    body = json.dumps({"dataset_id": ds, "year": 2014, "start": 0, "end": 120, **patch})  # allows Infinity/NaN
    r = c.post("/api/grid/drill", content=body, headers={"content-type": "application/json"})
    assert r.status_code == 422, (patch, r.text)


@pytest.mark.parametrize("patch", [
    {"shortfall_mw": "NaN"}, {"shortfall_mw": float("inf")}, {"shortfall_mw": 1e308},
    {"assumptions": {"min_stable_mw": "Infinity"}}, {"assumptions": {"min_stable_mw": 1e308}},
    {"assumptions": {"transformer_mva": "NaN"}}, {"year": 10**20},
])
def test_contingency_rejects_non_finite_and_huge(api, patch):
    c, ds, _ = api
    _finite_422(c)
    body = json.dumps({"dataset_id": ds, "constraint": "transformer_thermal", **patch})  # allows Infinity/NaN
    r = c.post("/api/grid/contingency", content=body, headers={"content-type": "application/json"})
    assert r.status_code == 422, (patch, r.text)


def test_readiness_query_bounds(api):
    c, ds, _ = api
    for extra in ({"year": 1999}, {"start": -1}, {"end": 10**9}, {"nameplate_mw": "inf"}, {"nameplate_mw": "nan"}):
        assert c.get("/api/grid/readiness", params={"dataset_id": ds, "year": 2014, **extra}).status_code == 422, extra
