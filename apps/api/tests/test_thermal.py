"""Thermal monitoring tests: IEEE C57.91-style model closed forms, ageing factor, synthetic hot connection,
demand what-if, read-only advisories, endpoint shapes and 422s (test-local FastAPI app), real 2014 window."""
from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import services
from app.agent.report_validator import UNSAFE_PATTERNS
from app.features.thermal import engine, model
from app.features.thermal.router import router
from app.features.thermal.schemas import BANNER, PROVENANCE, READ_ONLY_SUFFIX, ThermalAssumptions

REPO_ROOT = Path(__file__).resolve().parents[3]
RAW = REPO_ROOT / "data" / "raw" / "uci_551"
PATTERN_FLAGS = {"hot_connection_pattern", "rising_faster_than_peers"}


def synth(n: int = 240, year: int = 2014) -> pd.DataFrame:
    i = np.arange(n)
    return pd.DataFrame({
        "source_year": year,
        "row_index": i,
        "TEY": 135.0 + 25.0 * np.sin(2 * np.pi * i / 24.0),
        "AT": 15.0 + 5.0 * np.cos(2 * np.pi * i / 24.0),
    })


def run(frame: pd.DataFrame, **kw):
    return engine.evaluate(frame, dataset_id="ds_test", year=2014, start=0, end=len(frame), **kw)


class FakeBundle:
    def __init__(self, frame):
        self.frame = frame

    def window(self, year, start, end):
        yf = self.frame[self.frame["source_year"] == int(year)].reset_index(drop=True)
        if len(yf) == 0 or not (0 <= start < end <= len(yf)):
            raise IndexError(f"window [{start}, {end}) is out of range for year {year} (0..{len(yf)} rows available)")
        return yf.iloc[start:end].reset_index(drop=True).copy()


@pytest.fixture()
def client(monkeypatch):
    bundle = FakeBundle(synth(500))

    def get(dataset_id):
        if dataset_id != "ds_test":
            raise KeyError(dataset_id)
        return bundle

    monkeypatch.setattr(services, "get_repo", lambda: SimpleNamespace(get=get))
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


# --- model ------------------------------------------------------------------------------------------------


def test_steady_state_hot_spot_matches_closed_form_at_rated_load():
    to, hs = model.transformer_steady_state(1.0, 30.0)
    assert to == pytest.approx(30.0 + 55.0) and hs == pytest.approx(30.0 + 55.0 + 25.0)
    # transient model at constant K=1 stays on the closed form at every hourly step
    top, hot = model.transformer_transient(np.ones(48), np.full(48, 30.0))
    assert np.allclose(top, 85.0) and np.allclose(hot, 110.0)
    # and a step to K=1 from K=0.5 converges to it (τ_TO = 3 h → within 0.01 K after 48 h)
    k = np.r_[np.full(24, 0.5), np.ones(48)]
    _, hot2 = model.transformer_transient(k, np.full(k.size, 30.0))
    assert hot2[-1] == pytest.approx(110.0, abs=0.01) and hot2[24] < 110.0


def test_closed_form_general_k_uses_r_n_m():
    k, r, n, m = 0.7, 5.0, 0.8, 0.8
    expected = 20.0 + 55.0 * ((k * k * r + 1) / (r + 1)) ** n + 25.0 * k ** (2 * m)
    assert model.transformer_steady_state(k, 20.0)[1] == pytest.approx(expected)


def test_temperatures_monotonic_in_k():
    ks = np.linspace(0.1, 1.4, 30)
    hs = [model.transformer_steady_state(k, 20.0)[1] for k in ks]
    assert all(b > a for a, b in zip(hs, hs[1:]))
    q = model.quadratic_rise_temperature(ks, 20.0, 65.0)
    assert np.all(np.diff(q) > 0)
    assert q[ks.searchsorted(1.0)] > 20.0


def test_ageing_factor_reference_and_loss_of_life():
    assert float(model.ageing_acceleration_factor(110.0)) == pytest.approx(1.0, abs=1e-12)
    assert float(model.ageing_acceleration_factor(120.0)) == pytest.approx(2.71, abs=0.02)  # ~doubling per 6-7 K
    assert float(model.ageing_acceleration_factor(98.0)) < 0.3
    assert model.cumulative_loss_of_life_h(np.full(10, 110.0))[-1] == pytest.approx(10.0)


def test_diurnal_profile_mean_equals_multiplier_and_flat_is_constant():
    m = model.demand_multiplier_profile(np.arange(48), 1.2, "diurnal_datacenter")
    assert m.mean() == pytest.approx(1.2) and m.max() > 1.2 > m.min() > 1.0
    assert np.all(model.demand_multiplier_profile(np.arange(5), 1.15, "flat") == 1.15)
    with pytest.raises(ValueError):
        model.demand_multiplier_profile(np.arange(5), 1.1, "weekly")


# --- engine -----------------------------------------------------------------------------------------------


def test_real_only_synthetic_load_has_no_flags_and_is_labelled():
    f = synth()
    before = f.copy()
    r = run(f)
    pd.testing.assert_frame_equal(f, before)  # input never mutated
    assert r.flags == [] and r.advisories == []
    assert r.provenance == PROVENANCE and r.synthetic is False and r.synthetic_defect is None
    assert all(s.provenance == PROVENANCE and s.rise_index in (None, 1.0) for s in r.status)
    assert [s.asset_id for s in r.status] == ["GEN", "GCB", "GSU", "HVSG", "BUS"]
    assert r.banner == BANNER


def test_hot_connection_scenario_flags_exactly_one_asset_and_is_deterministic():
    r = run(synth(), scenario="T01_HOT_CONNECTION", scenario_seed=7)
    pattern_assets = {f.asset_id for f in r.flags if f.flag in PATTERN_FLAGS}
    assert pattern_assets == {"HVSG"}
    assert {f.asset_id for f in r.flags} == {"HVSG"}
    assert all(f.synthetic for f in r.flags)
    assert r.synthetic is True and r.synthetic_defect.asset_id == "HVSG" and r.synthetic_defect.synthetic
    hv = next(s for s in r.status if s.asset_id == "HVSG")
    assert hv.synthetic and hv.rise_index_drift > 0.5
    assert any(a.kind == "hot_connection" and "SYNTHETIC" in a.text for a in r.advisories)
    r2 = run(synth(), scenario="T01_HOT_CONNECTION", scenario_seed=7)
    assert [p.HVSG for p in r.series] == [p.HVSG for p in r2.series]


def test_demand_multiplier_raises_temperatures_and_ageing():
    f = synth()
    base = run(f)
    what = run(f, demand_multiplier=1.15)
    assert what.demand.applied and what.demand.what_if
    assert all(row.scenario_peak_c > row.baseline_peak_c for row in what.demand.impact)
    assert what.demand.scenario_loss_of_life_pct > what.demand.baseline_loss_of_life_pct
    assert all(p.GSU_whatif > p.GSU for p in what.series)
    # baseline status is unchanged by the what-if; the what-if status is reported separately
    assert [s.current_c for s in what.status] == [s.current_c for s in base.status]
    assert [s.current_c for s in what.demand.scenario_status] > [s.current_c for s in base.status]
    dc = run(f, demand_multiplier=1.3, demand_profile="diurnal_datacenter")
    assert dc.demand.notional_hour_note and "not a clock time" in dc.demand.notional_hour_note.lower()
    assert dc.demand.samples_above_nameplate_scenario >= dc.demand.samples_above_nameplate_baseline


def test_margin_flags_and_advisory_wording_when_alarm_is_close():
    a = ThermalAssumptions(transformer_hot_spot_alarm_c=75.0, transformer_hot_spot_limit_c=200.0)
    r = run(synth(), assumptions=a)
    gsu = [f for f in r.flags if f.asset_id == "GSU"]
    assert gsu and gsu[0].flag in {"approaching_alarm", "above_alarm", "exceeded_alarm_in_window"}
    adv = [x for x in r.advisories if x.asset_id == "GSU"]
    assert adv and adv[0].text.startswith("Advisory:") and "EVALUATE per site procedure" in adv[0].text
    assert "IR survey" in adv[0].text and adv[0].text.endswith(READ_ONLY_SUFFIX) and adv[0].read_only


def test_advisories_contain_no_control_verbs():
    f = synth()
    tight = ThermalAssumptions(transformer_hot_spot_alarm_c=60.0, contact_alarm_c=50.0, busbar_alarm_c=30.0,
                               generator_alarm_c=60.0, generator_limit_c=70.0)
    texts = []
    for kw in ({}, {"scenario": "T01_HOT_CONNECTION"}, {"assumptions": tight},
               {"assumptions": tight, "scenario": "T01_HOT_CONNECTION", "demand_multiplier": 1.4},
               {"demand_multiplier": 1.5, "demand_profile": "diurnal_datacenter"}):
        r = run(f, **kw)
        texts += [a.text for a in r.advisories] + [fl.message for fl in r.flags]
    assert len(texts) >= 8
    for t in texts:
        hits = [label for label, pat in UNSAFE_PATTERNS if pat.search(t)]
        assert hits == [], f"unsafe wording {hits} in: {t}"


def test_downsample_caps_points_and_keeps_peak():
    f = synth(n=4000)
    f.loc[2501, "TEY"] = 175.0
    r = run(f)
    assert len(r.series) <= engine.MAX_POINTS and r.downsample_factor == 4
    gsu = next(s for s in r.status if s.asset_id == "GSU")
    assert max(p.GEN for p in r.series) == pytest.approx(next(s for s in r.status if s.asset_id == "GEN").peak_c)
    assert gsu.peak_c >= max(p.GSU for p in r.series) - 1e-9


def test_engine_rejects_short_window():
    with pytest.raises(ValueError):
        run(synth(n=10))


# --- endpoints (test-local app) ---------------------------------------------------------------------------


def test_assets_endpoint_shape(client):
    r = client.get("/api/thermal/assets")
    assert r.status_code == 200
    body = r.json()
    assert [a["asset_id"] for a in body["assets"]] == ["GEN", "GCB", "GSU", "HVSG", "BUS"]
    assert body["default_assumptions"]["top_oil_rise_rated_k"] == 55.0
    assert body["default_assumptions"]["hot_spot_gradient_rated_k"] == 25.0
    assert body["scenarios"] == ["none", "T01_HOT_CONNECTION"]
    assert body["provenance"] == PROVENANCE and "no thermal sensors" in body["banner"]


def test_evaluate_endpoint_shape(client):
    r = client.post("/api/thermal/evaluate", json={"dataset_id": "ds_test", "year": 2014, "start": 100, "end": 340,
                                                   "scenario": "T01_HOT_CONNECTION", "demand_multiplier": 1.15,
                                                   "demand_profile": "diurnal_datacenter",
                                                   "assumptions": {"approach_margin_k": 8}})
    assert r.status_code == 200, r.text
    b = r.json()
    for key in ("series", "status", "flags", "ageing", "advisories", "assumptions", "provenance", "demand", "limits"):
        assert key in b
    assert b["window"] == {"source_year": 2014, "start": 100, "end": 340, "n_samples": 240, "note": b["window"]["note"]}
    assert b["assumptions"]["approach_margin_k"] == 8 and b["assumptions"]["exponent_n"] == 0.8
    assert b["provenance"] == "simulated_from_real_load" and b["synthetic"] is True
    assert b["series"][0]["row_index"] == 100 and len(b["series"]) == 240
    assert b["ageing"]["window_hours"] == 240 and "EXTRAPOLATED" in b["ageing"]["extrapolation_label"]
    assert b["demand"]["applied"] is True and len(b["demand"]["impact"]) == 5
    assert all(x["provenance"] == PROVENANCE for x in b["status"] + b["flags"] + b["advisories"])


@pytest.mark.parametrize("payload,status", [
    ({"dataset_id": "ds_test", "start": 50, "end": 50}, 422),
    ({"dataset_id": "ds_test", "start": 0, "end": 10}, 422),
    ({"dataset_id": "ds_test", "start": 400, "end": 600}, 422),  # beyond the 500 rows of the year
    ({"dataset_id": "ds_test", "year": 2013, "start": 0, "end": 100}, 422),
    ({"dataset_id": "ds_test", "scenario": "T99"}, 422),
    ({"dataset_id": "ds_test", "demand_multiplier": 5}, 422),
    ({"dataset_id": "ds_test", "demand_profile": "weekly"}, 422),
    ({"dataset_id": "ds_test", "assumptions": {"contact_alarm_c": 120}}, 422),  # alarm above limit
    ({"dataset_id": "ds_test", "assumptions": {"top_oil_rise_rated_k": -5}}, 422),
    ({"dataset_id": "ds_test", "assumptions": {"bogus": 1}}, 422),
    ({"dataset_id": "nope"}, 404),
])
def test_evaluate_rejects_bad_input(client, payload, status):
    r = client.post("/api/thermal/evaluate", json=payload)
    assert r.status_code == status, r.text
    assert "detail" in r.json()


# --- real data --------------------------------------------------------------------------------------------


@pytest.mark.skipif(not (RAW / "gt_2014.csv").is_file(), reason="UCI raw files not present")
def test_real_2014_default_window_no_flags_at_default_assumptions():
    from app.data.uci_loader import load_uci_dir

    bundle = load_uci_dir(RAW)
    frame = bundle.window(2014, 1200, 1320)
    r = engine.evaluate(frame, dataset_id="ds_uci_551", year=2014, start=1200, end=1320)
    # observed (not forced): at default assumptions the real-load-derived feed stays well below every alarm
    assert r.flags == [] and r.advisories == []
    assert all(s.state == "normal" and s.margin_to_alarm_k > 10 for s in r.status)
    gsu = next(s for s in r.status if s.asset_id == "GSU")
    assert 40 < gsu.current_c < 110 and r.ageing.equivalent_faa < 1.0
    t01 = engine.evaluate(frame, dataset_id="ds_uci_551", year=2014, start=1200, end=1320, scenario="T01_HOT_CONNECTION")
    assert {f.asset_id for f in t01.flags if f.flag in PATTERN_FLAGS} == {"HVSG"}
    assert math.isfinite(t01.ageing.loss_of_life_pct)


@pytest.mark.parametrize("payload", [
    {"dataset_id": "ds_test", "assumptions": {"loss_ratio_r": "NaN"}},
    {"dataset_id": "ds_test", "assumptions": {"tau_top_oil_h": "Infinity"}},
    {"dataset_id": "ds_test", "assumptions": {"hv_rated_mwh": 1e308}},
    {"dataset_id": "ds_test", "demand_multiplier": "NaN"},
    {"dataset_id": "ds_test", "demand_multiplier": float("inf")},
    {"dataset_id": "ds_test", "year": 1999},
    {"dataset_id": "ds_test", "year": 10**20},
    {"dataset_id": "ds_test", "start": 0, "end": 100_001},
    {"dataset_id": "ds_test", "scenario_seed": 2**31},
])
def test_evaluate_rejects_non_finite_and_huge(client, payload):
    import json

    from fastapi.exceptions import RequestValidationError

    from app.main import request_validation_error_handler

    client.app.add_exception_handler(RequestValidationError, request_validation_error_handler)
    r = client.post("/api/thermal/evaluate", content=json.dumps(payload), headers={"content-type": "application/json"})
    assert r.status_code == 422, r.text


def test_gcb_cites_generator_breaker_standard():
    gcb = next(a for a in engine.ASSETS if a.asset_id == "GCB") if hasattr(engine, "ASSETS") else None
    if gcb is None:
        pytest.skip("asset list not exposed as engine.ASSETS")
    assert "IEEE C37.013" in gcb.standard_ref and "62271-37-013" in gcb.standard_ref
