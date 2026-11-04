"""Executive view: overview aggregation (shape, provenance, attention rules, guarded imports) and the
executive brief (FakeMetaClient accepted / rejected -> fallback), endpoints via a test-local FastAPI app."""
from __future__ import annotations

import json
import sys

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent.meta_client import ChatResult
from app.features.executive import brief as brief_mod
from app.features.executive import overview as ov_mod
from app.features.executive import router as ex_router
from app.features.executive.schemas import (BRIEF_DISCLAIMER, GROUP_TITLES, ExecutiveOverview, Kpi,
                                            OpenCase)

PROVENANCES = {"real", "model_derived", "simulated", "assumption", "prototype_metric"}
NOW = "2026-11-04T12:00:00Z"


# ----------------------------------------------------------------------------- helpers
def kpi(key, group, value, provenance="prototype_metric", unit="", detail=None, available=True):
    return Kpi(key=key, group=group, label=key, value=value, unit=unit, provenance=provenance,
               source_endpoint="/api/x", caveat="c", available=available, detail=detail or {})


def fake_sources(**over) -> ov_mod.Sources:
    base = dict(investigations=lambda: [], work_requests=lambda: [], count_table=lambda name: 2,
                deliberations_awaiting=lambda: 0, human_required=lambda: 0,
                control_capabilities=lambda: {"read": False, "write": False})
    base.update(over)
    return ov_mod.Sources(**base)


def small_overview() -> ExecutiveOverview:
    kpis = [
        kpi("tey_residual_year_mean", "performance", 1.067, "model_derived", "MWh per hourly sample"),
        kpi("thermal_min_margin", "reliability", 7.5, "simulated", "K", {"asset_name": "Step-up transformer"}),
        kpi("emissions_excursions", "compliance", 94, "real", "excursions"),
        kpi("first_pass_acceptance", "decisions", 75.0, unit="%"),
    ]
    cases = [OpenCase(case_id="case_abc123", scenario_id="S02_INTAKE_RESTRICTION", synthetic=True, status="completed")]
    return ExecutiveOverview(dataset_id="ds_uci_551", year=2014, computed_at_utc=NOW,
                             attention=ov_mod.attention_rules(kpis, cases), kpis=kpis, open_cases=cases)


class FakeMetaClient:
    configured = True
    model = "muse-spark-1.3"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.max_tokens_seen = []

    def chat(self, messages, tools, max_tokens, response_format=None):
        self.calls += 1
        self.max_tokens_seen.append(max_tokens)
        content = self.responses.pop(0)
        return ChatResult(message={"role": "assistant", "content": json.dumps(content) if isinstance(content, dict)
                                   else content}, usage={"prompt_tokens": 10, "completion_tokens": 5},
                          latency_ms=12, model=self.model, finish_reason="stop")


def good_brief(**over) -> dict:
    d = {
        "headline": "Thermal margin of 7.5 K on the step-up transformer (simulated) needs an owner",
        "situation": "Output sits 1.07 MWh per sample above the model-derived expectation; 94 screening excursions.",
        "risks": ["Simulated thermal margin is below the 10 K rule."],
        "decisions_needed": [{"decision": "Assign review of case_abc123", "owner_persona": "electrical_engineer",
                              "why": "Simulated margin is small."}],
        "money_and_time_caveats": ["No savings are computed; acceptance of 75 % is a prototype metric."],
        "next_30_days": ["Agree pilot metrics with the reliability engineer."],
    }
    d.update(over)
    return d


@pytest.fixture
def store(tmp_path):
    return brief_mod.BriefStore(tmp_path / "exec.db")


# ----------------------------------------------------------------------------- overview
def test_rolling_notable_share_detects_step_and_quiet_series():
    rng = np.random.default_rng(0)
    quiet = rng.normal(0, 0.1, 1000)
    share, n_notable, n_eval = ov_mod.rolling_notable_share(quiet, std_val=1.0)
    assert share == 0.0 and n_notable == 0 and n_eval == 1000 - 24 - 168 + 1
    step = quiet.copy()
    step[600:] -= 5.0
    share2, n2, _ = ov_mod.rolling_notable_share(step, std_val=1.0)
    assert n2 > 0 and share2 > 0
    assert ov_mod.rolling_notable_share(quiet[:100], std_val=1.0)[0] is None  # too short


def test_overview_shape_and_provenance_on_fixture_data(trained_model):
    ov = ov_mod.compute_overview(2014, sources=fake_sources(), now_utc=NOW)
    keys = {k.key for k in ov.kpis}
    for required in ("tey_residual_year_mean", "compressor_wash_status", "instrument_health", "thermal_min_margin",
                     "emissions_hours_above", "emissions_excursions", "grid_headroom", "cases_awaiting_review",
                     "work_requests_open", "deliberations_awaiting", "human_required", "precedents",
                     "handover_notes", "onboarding_briefs", "control_write_path", "notable_deviation_share"):
        assert required in keys, required
    for k in ov.kpis:
        assert k.provenance in PROVENANCES
        assert k.source_endpoint and k.caveat
        assert k.group in GROUP_TITLES
    by = {k.key: k for k in ov.kpis}
    assert by["thermal_min_margin"].provenance == "simulated"
    assert by["tey_residual_year_mean"].provenance == "model_derived"
    assert by["emissions_excursions"].provenance == "real"
    assert by["grid_headroom"].provenance == "assumption"
    assert by["control_write_path"].value == "none"
    assert by["handover_notes"].value == 2
    assert ov.footer.startswith("All figures are prototype metrics")
    assert "AVAILABILITY PROXY" in by["notable_deviation_share"].caveat
    json.dumps(ov.model_dump())  # serialisable, no NaN objects


def test_attention_rules_fire_with_persona_and_link():
    kpis = [
        kpi("thermal_min_margin", "reliability", 6.2, "simulated", "K", {"asset_name": "Generator"}),
        kpi("compressor_wash_status", "performance", "consider scheduling a wash (human decision)", "assumption"),
        kpi("instrument_health", "reliability", "9 / 1 / 1", "real", detail={"check": 1, "verify_first": ["CDP"]}),
        kpi("human_required", "decisions", 3),
        kpi("deliberations_awaiting", "decisions", 1),
        kpi("work_requests_open", "decisions", 2),
    ]
    items = ov_mod.attention_rules(kpis, [])
    by = {i.id: i for i in items}
    assert by["thermal_margin"].persona == "electrical_engineer" and by["thermal_margin"].link == "/thermal"
    assert by["compressor_wash"].persona == "performance_engineer" and by["compressor_wash"].link == "/planner"
    assert by["instrument_check"].persona == "ic_engineer" and "CDP" in by["instrument_check"].title
    assert by["human_required"].severity == "attention"
    assert by["deliberations"].persona == "plant_manager"
    assert by["work_requests"].severity == "info"
    assert [i.severity for i in items] == sorted((i.severity for i in items), key=lambda s: s != "attention")


def test_attention_rules_quiet_when_nothing_fires():
    kpis = [
        kpi("thermal_min_margin", "reliability", 57.1, "simulated", "K"),
        kpi("compressor_wash_status", "performance", "no economic case yet", "assumption"),
        kpi("instrument_health", "reliability", "11 / 0 / 0", "real", detail={"check": 0}),
        kpi("human_required", "decisions", 0),
        kpi("deliberations_awaiting", "decisions", None, available=False),
    ]
    assert ov_mod.attention_rules(kpis, []) == []


def test_guarded_imports_when_optional_packages_absent(monkeypatch, trained_model):
    # parent packages too: once imported elsewhere (e.g. by app.main), the submodule is also a package attribute
    for name in ("app.features.deliberation", "app.features.deliberation.store", "app.features.watchdog",
                 "app.plant", "app.plant.store"):
        monkeypatch.setitem(sys.modules, name, None)
    monkeypatch.setitem(sys.modules, "app.connectors.base", None)
    assert ov_mod._default_deliberations_awaiting() is None
    assert ov_mod._default_work_requests() is None
    assert ov_mod._default_control_capabilities() is None
    ov = ov_mod.compute_overview(2014, sources=ov_mod.Sources(investigations=lambda: []), now_utc=NOW)
    by = {k.key: k for k in ov.kpis}
    assert by["deliberations_awaiting"].available is False
    assert by["work_requests_open"].available is False and by["work_requests_open"].caveat.startswith("Unavailable")
    assert by["control_write_path"].available is False


# ----------------------------------------------------------------------------- brief
def test_number_whitelist_tolerance():
    allowed = brief_mod.payload_numbers({"a": 132.91, "b": "headroom 27.09 MWh", "c": [0.75]})
    assert brief_mod.number_supported("133", 133.0, allowed)          # rounding
    assert brief_mod.number_supported("27.1", 27.1, allowed)
    assert not brief_mod.number_supported("140", 140.0, allowed)
    assert brief_mod.number_supported("30", 30.0, allowed)            # structural (next 30 days)
    assert [t for t, _ in brief_mod.numbers_in_text("case_abc123 and S02_INTAKE and p95 cost 12")] == ["12"]


def test_brief_accepted_with_fake_meta_client(store):
    ov = small_overview()
    client = FakeMetaClient([good_brief()])
    b = brief_mod.generate_brief(ov, client=client, store=store, now_utc=NOW)
    assert b.mode == "meta_live" and b.meta_used and b.meta_calls == 1 and not b.rewrite_used
    assert client.max_tokens_seen == [8000]
    assert b.disclaimer == BRIEF_DISCLAIMER and b.status.startswith("DRAFT")
    assert b.brief.decisions_needed[0].owner_persona == "electrical_engineer"
    assert store.list()[0].brief_id == b.brief_id and b.brief_hash


def test_brief_number_not_in_payload_rejected_then_fallback(store):
    ov = small_overview()
    bad = good_brief(situation="A wash would recover 4,200 MWh this year.")
    client = FakeMetaClient([bad, bad])
    b = brief_mod.generate_brief(ov, client=client, store=store, now_utc=NOW)
    assert client.calls == 2 and b.rewrite_used
    assert b.mode == "offline_fallback" and not b.meta_used
    assert any("number_not_in_payload" in e for e in b.validation_errors)
    assert "rejected" in b.source_label and b.fallback_reason
    assert b.brief.headline  # deterministic fallback content


def test_brief_unsafe_unknown_case_and_money_rejected_then_rewrite_accepted(store):
    ov = small_overview()
    bad = good_brief(next_30_days=["Reduce load on the unit and cite case_zzz999."],
                     money_and_time_caveats=["A wash saves $50,000."])
    client = FakeMetaClient([bad, good_brief()])
    b = brief_mod.generate_brief(ov, client=client, store=store, now_utc=NOW)
    assert b.mode == "meta_live" and b.rewrite_used and b.meta_calls == 2
    errs = " ".join(b.validation_errors)
    assert "unsafe_instruction" in errs and "unknown case ids" in errs and "financial_claim" in errs


def test_offline_fallback_when_no_client(store):
    b = brief_mod.generate_brief(small_overview(), client=None, store=store, now_utc=NOW)
    assert b.mode == "offline_fallback" and b.meta_calls == 0 and b.source_label.startswith("OFFLINE FALLBACK")
    assert b.brief.decisions_needed and b.brief.decisions_needed[0].owner_persona == "electrical_engineer"


# ----------------------------------------------------------------------------- endpoints
@pytest.fixture
def api(monkeypatch, store):
    monkeypatch.setattr(ex_router, "get_store", lambda: store)
    monkeypatch.setattr(ex_router, "get_meta_client", lambda: None)
    monkeypatch.setattr(ex_router, "now_utc", lambda: NOW)
    monkeypatch.setattr(ov_mod, "compute_overview", lambda year, dataset_id, sources=None, now_utc=None: small_overview())
    app = FastAPI()
    app.include_router(ex_router.router, prefix="/api")
    return TestClient(app)


def test_endpoints_overview_brief_list_and_404(api):
    r = api.get("/api/executive/overview?year=2014")
    assert r.status_code == 200
    body = r.json()
    assert body["attention"][0]["persona"] == "electrical_engineer" and body["read_only"] is True
    r = api.post("/api/executive/brief", json={"year": 2014})
    assert r.status_code == 200 and r.json()["mode"] == "offline_fallback"
    bid = r.json()["brief_id"]
    lst = api.get("/api/executive/briefs").json()
    assert lst[0]["brief_id"] == bid
    assert api.get(f"/api/executive/briefs/{bid}").status_code == 200
    assert api.get("/api/executive/briefs/eb_nope").status_code == 404
    assert api.get("/api/executive/overview?year=1900").status_code == 422
    assert api.post("/api/executive/brief", json={"year": 2014, "extra": 1}).status_code == 422


def test_package_exports_router_module():
    import app.features.executive as pkg

    assert hasattr(pkg.router, "router") and pkg.router.router.prefix == "/executive"
