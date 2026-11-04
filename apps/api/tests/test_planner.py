"""Maintenance planner: engine math on synthetic data + endpoint shapes via a test-local FastAPI app."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import services
from app.features.planner import engine, router
from app.features.planner.schemas import (
    AfdpProxy,
    CompressorWashRequest,
    FilterChangeoutRequest,
)

# ---------------------------------------------------------------------------
# synthetic helpers
# ---------------------------------------------------------------------------


def _frame(n: int, **cols) -> pd.DataFrame:
    data = {"source_year": np.full(n, 2014), "row_index": np.arange(n)}
    data["TEY"] = cols.pop("TEY", np.full(n, 100.0))
    data["CDP"] = cols.pop("CDP", np.full(n, 12.0))
    data["AFDP"] = cols.pop("AFDP", np.full(n, 3.0))
    data.update(cols)
    return pd.DataFrame(data)


def _ramp_residuals(n: int = 1000, knee: int = 300, slope: float = 0.01) -> np.ndarray:
    p = np.arange(n, dtype=float)
    return np.where(p <= knee, 1.0, 1.0 - slope * (p - knee))


PROXY = AfdpProxy(method="test", coefficient_mwh_per_sample_per_mbar=-0.1, training_years=[2011])


# ---------------------------------------------------------------------------
# compressor wash engine
# ---------------------------------------------------------------------------


def test_wash_break_even_math_on_synthetic_ramp():
    # Residual flat at 1.0 until sample 300, then falls 0.01 MWh/sample. With a 24-sample trailing median,
    # rolling(p) = 1 - 0.01 (p - 311.5) for p >= 312 and 1.0 before => best = 1.0 last at p = 311,
    # cum(P) = 0.005 m^2 with m = P - 311. Cost = 5000 + 10 h * 100 MWh * 50 = 55,000; threshold
    # = 55,000 / (0.5 * 50) = 2,200 MWh -> m = 664 -> break-even at sample 975.
    n = 1000
    req = CompressorWashRequest(
        year=2014, rolling_window_samples=24, energy_price_per_mwh=50, wash_outage_hours=10,
        wash_direct_cost=5000, expected_recovery_fraction=0.5,
    )
    out = engine.compute_compressor_wash(_frame(n), _ramp_residuals(n), req, model_version="t")
    assert out.best_rolling_residual_mwh == pytest.approx(1.0)
    assert out.best_index == 311
    assert out.current_index == n - 1
    assert out.lost_output_rate_now_mwh_per_sample == pytest.approx(0.01 * (999 - 311.5), rel=1e-6)
    assert out.cumulative_lost_output_mwh == pytest.approx(0.005 * 688**2, rel=1e-6)
    assert out.economics["total_cost"] == pytest.approx(55_000)
    assert out.economics["outage_lost_output_mwh"] == pytest.approx(1000)
    assert out.break_even_reached is True
    assert out.break_even_index == 975
    assert out.payback_hours_if_rate_persists == pytest.approx(55_000 / (0.5 * 6.875 * 50), rel=1e-6)
    assert out.status == "consider scheduling a wash (human decision)"
    assert out.requires_human_review is True
    assert "sample #975" in out.computation and "p95" in out.computation
    # chart series: downsampled, cumulative only from the best point on
    assert 0 < len(out.series) <= engine.MAX_SERIES_POINTS + 1
    assert out.series[-1].row_index == n - 1
    assert all(pt.cumulative_loss_mwh is None for pt in out.series if pt.row_index < 311)


def test_wash_no_economic_case_when_cost_high_or_flat():
    n = 1000
    expensive = CompressorWashRequest(year=2014, rolling_window_samples=24, wash_direct_cost=1e8)
    out = engine.compute_compressor_wash(_frame(n), _ramp_residuals(n), expensive)
    assert out.status == "no economic case yet" and out.break_even_reached is False
    flat = engine.compute_compressor_wash(_frame(n), np.zeros(n), CompressorWashRequest(year=2014, rolling_window_samples=24))
    assert flat.status == "no economic case yet"
    assert flat.lost_output_rate_now_mwh_per_sample == 0.0
    assert flat.cumulative_lost_output_mwh == 0.0


def test_wash_insufficient_data_path():
    req = CompressorWashRequest(year=2014)  # default window 168 -> needs 336 finite residuals
    out = engine.compute_compressor_wash(_frame(200), np.zeros(200), req)
    assert out.status == "insufficient data"
    assert out.series == [] and out.cumulative_lost_output_mwh is None
    assert "336" in out.status_reasons[0]
    # NaN residuals do not count as data
    res = np.full(1000, np.nan)
    res[:100] = 0.0
    out2 = engine.compute_compressor_wash(_frame(1000), res, req)
    assert out2.status == "insufficient data"


def test_engine_is_deterministic():
    rng = np.random.default_rng(7)
    n = 2000
    res = np.cumsum(rng.normal(0, 0.05, n))
    afdp = 3 + np.cumsum(np.abs(rng.normal(0, 0.002, n)))
    frame = _frame(n, AFDP=afdp, CDP=12 + rng.normal(0, 0.1, n))
    wreq = CompressorWashRequest(year=2014)
    freq = FilterChangeoutRequest(year=2014)
    a = engine.compute_compressor_wash(frame, res, wreq).model_dump()
    b = engine.compute_compressor_wash(frame.copy(), res.copy(), wreq).model_dump()
    assert a == b
    c = engine.compute_filter_changeout(frame, freq, PROXY).model_dump()
    d = engine.compute_filter_changeout(frame.copy(), freq, PROXY).model_dump()
    assert c == d


def test_assumptions_echo_every_input_with_source():
    req = CompressorWashRequest(year=2014, energy_price_per_mwh=80)
    out = engine.compute_compressor_wash(_frame(100), np.zeros(100), req)
    by_key = {a.key: a for a in out.assumptions}
    assert set(by_key) == {k for k, _, _ in engine.WASH_SPEC}
    assert by_key["energy_price_per_mwh"].value == 80 and by_key["energy_price_per_mwh"].source == "user_input"
    assert by_key["wash_outage_hours"].value == 24 and by_key["wash_outage_hours"].source == "default"
    freq = FilterChangeoutRequest(year=2014, afdp_limit_mbar=6.5)
    fout = engine.compute_filter_changeout(_frame(100), freq, PROXY)
    fkeys = {a.key: a for a in fout.assumptions}
    assert set(fkeys) == {k for k, _, _ in engine.FILTER_SPEC}
    assert fkeys["afdp_limit_mbar"].value == 6.5 and fkeys["afdp_limit_mbar"].source == "user_input"


# ---------------------------------------------------------------------------
# filter change-out engine
# ---------------------------------------------------------------------------


def test_filter_linear_trend_projection_and_limit():
    n = 2000
    afdp = 3.0 + 0.001 * np.arange(n)  # +1 mbar per 1000 samples
    frame = _frame(n, AFDP=afdp)
    req = FilterChangeoutRequest(year=2014, rolling_window_samples=24, trend_window_samples=720, afdp_limit_mbar=7.0)
    out = engine.compute_filter_changeout(frame, req, PROXY, afdp_training_range=[2.1, 7.6])
    now = 3.0 + 0.001 * (n - 1 - 11.5)  # trailing median of a linear ramp = midpoint value
    assert out.current_afdp_rolling_mbar == pytest.approx(now, rel=1e-6)
    assert out.trend_slope_mbar_per_1000_samples == pytest.approx(1.0, rel=1e-6)
    assert out.samples_to_limit == pytest.approx((7.0 - now) / 0.001, rel=1e-4)
    assert out.projected_limit_index == n - 1 + int(np.ceil(out.samples_to_limit))
    assert out.projection[-1].trend_mbar == pytest.approx(7.0, abs=1e-3)
    assert out.limit_reached is False
    # proxy: 0.1 MWh per mbar above the clean (p5) level
    assert out.lost_output_rate_now_mwh_per_sample == pytest.approx(0.1 * (now - out.clean_afdp_mbar), rel=1e-6)
    assert out.proxy.statement.startswith("Statistical association")
    # limit already exceeded -> consider (human decision)
    hit = engine.compute_filter_changeout(frame, req.model_copy(update={"afdp_limit_mbar": 4.0}), PROXY)
    assert hit.limit_reached and hit.samples_to_limit == 0
    assert hit.status == "consider scheduling a filter change-out (human decision)"
    # falling AFDP -> no projected crossing
    down = engine.compute_filter_changeout(_frame(n, AFDP=afdp[::-1].copy()), req, PROXY)
    assert down.samples_to_limit is None and down.projected_limit_index is None
    assert down.status == "no economic case yet"


def test_filter_insufficient_data():
    out = engine.compute_filter_changeout(_frame(100), FilterChangeoutRequest(year=2014), PROXY)
    assert out.status == "insufficient data" and out.series == [] and out.projection == []


def test_afdp_proxy_recovers_partial_coefficient():
    rng = np.random.default_rng(3)
    n = 3000
    cols = {k: rng.normal(10, 2, n) for k in engine.FEATURES}
    cols["TEY"] = 100 - 0.2 * cols["AFDP"] + 2.0 * cols["CDP"] + rng.normal(0, 0.05, n)
    proxy = engine.estimate_afdp_proxy(pd.DataFrame(cols), model=None, training_years=[2011])
    assert proxy.coefficient_mwh_per_sample_per_mbar == pytest.approx(-0.2, abs=0.01)
    assert proxy.n_rows == n and "not physics" in proxy.statement
    small = engine.estimate_afdp_proxy(pd.DataFrame(cols).head(100), model=None)
    assert small.method == "unavailable" and small.coefficient_mwh_per_sample_per_mbar is None


# ---------------------------------------------------------------------------
# endpoints (test-local app; main.py wiring is owned by the principal)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def planner_client(trained_model):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    with TestClient(app) as c:
        yield c


def test_options_shape(planner_client):
    r = planner_client.get("/api/planner/options")
    assert r.status_code == 200
    body = r.json()
    assert body["data_available"] is True and 2014 in body["years"]
    assert body["default_year"] == 2014
    assert body["wash_defaults"]["energy_price_per_mwh"] == 60
    assert body["wash_defaults"]["wash_outage_hours"] == 24
    assert body["wash_defaults"]["wash_direct_cost"] == 15000
    assert body["wash_defaults"]["expected_recovery_fraction"] == 0.7
    assert body["filter_defaults"]["afdp_limit_mbar"] == 7.0
    assert "not a maintenance instruction" in body["disclaimer"]


def test_wash_and_filter_endpoint_shapes(planner_client):
    # fixture data: 300 rows per year -> default 168 window is insufficient, 24 works
    r = planner_client.post("/api/planner/compressor-wash", json={"year": 2014})
    assert r.status_code == 200 and r.json()["status"] == "insufficient data"
    r = planner_client.post("/api/planner/compressor-wash", json={"year": 2014, "rolling_window_samples": 24})
    assert r.status_code == 200
    w = r.json()
    for k in ("status", "computation", "assumptions", "series", "economics", "lost_output_rate_now_mwh_per_sample",
              "cumulative_lost_output_mwh", "break_even_reached", "cdp", "caveats", "disclaimer"):
        assert k in w
    assert w["status"] in ("consider scheduling a wash (human decision)", "no economic case yet")
    assert w["requires_human_review"] is True and w["model_version"]
    assert {"row_index", "rolling_residual_mwh", "cumulative_loss_mwh"} <= set(w["series"][0])
    r = planner_client.post(
        "/api/planner/filter-changeout", json={"year": 2014, "rolling_window_samples": 24, "trend_window_samples": 48}
    )
    assert r.status_code == 200
    f = r.json()
    assert f["proxy"]["training_years"] == [2011, 2012, 2013]
    assert f["proxy"]["coefficient_mwh_per_sample_per_mbar"] is not None
    assert len(f["projection"]) == 2 and f["afdp_training_range_mbar"]
    assert {a["key"] for a in f["assumptions"]} >= {"afdp_limit_mbar", "filter_change_cost", "filter_outage_hours"}
    # same input -> same output
    assert planner_client.post(
        "/api/planner/filter-changeout", json={"year": 2014, "rolling_window_samples": 24, "trend_window_samples": 48}
    ).json() == f


@pytest.mark.parametrize(
    "path,body",
    [
        ("compressor-wash", {"year": 2014, "expected_recovery_fraction": 1.5}),
        ("compressor-wash", {"year": 2014, "expected_recovery_fraction": 0}),
        ("compressor-wash", {"year": 2014, "energy_price_per_mwh": -1}),
        ("compressor-wash", {"year": 2014, "rolling_window_samples": 5}),
        ("compressor-wash", {"year": 1999}),
        ("compressor-wash", {}),
        ("filter-changeout", {"year": 2014, "afdp_limit_mbar": 0}),
        ("filter-changeout", {"year": 2014, "filter_outage_hours": -2}),
        ("filter-changeout", {"year": "abc"}),
    ],
)
def test_bad_inputs_422(planner_client, path, body):
    r = planner_client.post(f"/api/planner/{path}", json=body)
    assert r.status_code == 422, r.text


def test_unknown_dataset_and_missing_model_404(planner_client, monkeypatch):
    r = planner_client.post("/api/planner/compressor-wash", json={"year": 2014, "dataset_id": "ds_nope"})
    assert r.status_code == 404
    monkeypatch.setattr(services, "get_model", lambda recheck=False: None)
    for path in ("compressor-wash", "filter-changeout"):
        r = planner_client.post(f"/api/planner/{path}", json={"year": 2014})
        assert r.status_code == 404
        assert "baseline model not trained" in r.json()["detail"]
    opts = planner_client.get("/api/planner/options").json()
    assert opts["model_available"] is False
