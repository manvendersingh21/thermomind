"""Instrument-health scorecard: engine on synthetic frames, real 2014 data, and the endpoint."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import config, services
from app.features.instruments import engine
from app.features.instruments.router import router
from app.schemas import MEASUREMENT_KEYS

RAW = config.RAW_UCI_DIR


def _frame(n: int, seed: int) -> pd.DataFrame:
    """Coupled synthetic frame: a latent load drives CDP, TEY, TIT, TAT, GTEP; AT anti-correlates."""
    rng = np.random.default_rng(seed)
    load = np.clip(rng.normal(0, 1, n), -2.5, 2.5)  # stationary; train/window share the same distribution
    d = {
        "AT": 15 - 4 * load + rng.normal(0, 0.5, n),
        "AP": 1010 + rng.normal(0, 3, n),
        "AH": 70 + rng.normal(0, 8, n),
        "AFDP": 4 + 0.3 * load + rng.normal(0, 0.1, n),
        "GTEP": 25 + 3 * load + rng.normal(0, 0.2, n),
        "TIT": 1070 + 10 * load + rng.normal(0, 1, n),
        "TAT": 535 + 5 * load + rng.normal(0, 0.5, n),
        "TEY": 130 + 8 * load + rng.normal(0, 0.5, n),
        "CDP": 12 + 1 * load + rng.normal(0, 0.05, n),
        "CO": 2 + rng.gamma(2, 0.5, n),
        "NOX": 70 + rng.normal(0, 5, n),
    }
    return pd.DataFrame(d)


def test_flatline_runs_unit():
    v = np.array([1, 1, 1, 1, 1, 2, 3, 3, 3, 3, 3, 3, np.nan, 3, 3, 3, 3, 3, 3.0])
    runs, rows = engine.flatline_runs(v)
    assert (runs, rows) == (2, 12)  # the 5-long run is below the 6 minimum; NaN breaks the run


def test_synthetic_injected_faults_flagged():
    train = _frame(3000, 1)
    win = _frame(1000, 2)
    win.loc[100:119, "AP"] = 1011.0  # flatline, 20 rows
    win.loc[400, "AH"] = 70 + 400.0  # spike (also outside training range)
    win.loc[700, "AH"] = np.nan
    win.loc[200:249, "NOX"] = 500.0  # OOD vs training min/max, also a flatline
    # decouple TEY from the process: pure noise instead of load-driven
    win["TEY"] = 130 + np.random.default_rng(9).normal(0, 8, len(win))
    ranges = {k: [float(train[k].min()), float(train[k].max())] for k in ["AT", "AP", "AH", "AFDP", "GTEP", "TIT", "TAT", "CDP"]}
    sensors, summary = engine.compute_scorecard(win, train, ranges)
    by = {s.key: s for s in sensors}
    assert len(sensors) == 11 and [s.key for s in sensors] == MEASUREMENT_KEYS
    assert by["AP"].flatline_runs >= 1 and by["AP"].flatline_rows >= 20
    assert by["AH"].spikes >= 1 and by["AH"].out_of_range >= 1 and by["AH"].missing == 1
    assert by["NOX"].out_of_range == 50 and by["NOX"].range_source == "training_years_min_max"
    assert by["AP"].range_source == "model.feature_ranges_train"
    assert "CDP~TEY" in by["TEY"].coupling_drift_pairs and "CDP~TEY" in by["CDP"].coupling_drift_pairs
    assert by["TEY"].score < by["TAT"].score
    assert by["NOX"].score < 90
    assert 0.0 <= min(s.score for s in sensors) and max(s.score for s in sensors) <= 100.0
    assert "TEY" in summary.use_with_cross_check + summary.verify_first
    assert "not a calibration certificate" in summary.headline


def test_clean_frame_scores_ok_and_formula_documented():
    train = _frame(3000, 3)
    win = _frame(800, 4)
    sensors, summary = engine.compute_scorecard(win, train, None)
    by = {s.key: s for s in sensors}
    assert by["TAT"].missing == 0 and by["TAT"].out_of_range == 0 and by["TAT"].flatline_runs == 0
    assert all(not s.coupling_drift_pairs for s in sensors)
    for s in sensors:
        assert s.computation.startswith("100 - missing")
        assert s.status == ("ok" if s.score >= 80 else "watch" if s.score >= 60 else "check")
        assert s.what_to_check and "write" not in s.what_to_check.lower()
    assert summary.disclaimer.startswith("Statistical screening on historical data")


def test_all_missing_sensor_scores_zero_check():
    train = _frame(500, 5)
    win = _frame(200, 6)
    win["CO"] = np.nan
    sensors, summary = engine.compute_scorecard(win, train, None)
    co = next(s for s in sensors if s.key == "CO")
    assert co.score == 0.0 and co.status == "check" and co.missing == 200
    assert "CO" in summary.verify_first


def test_deterministic():
    train, win = _frame(1500, 7), _frame(500, 8)
    a = [s.model_dump() for s in engine.compute_scorecard(win, train, None)[0]]
    b = [s.model_dump() for s in engine.compute_scorecard(win.copy(), train.copy(), None)[0]]
    assert a == b


# --- real data ------------------------------------------------------------------------------------------------

needs_real = pytest.mark.skipif(
    not all((RAW / f"gt_{y}.csv").is_file() for y in range(2011, 2016)), reason="real UCI files not present"
)


@pytest.fixture(scope="module")
def real_bundle():
    from app.data.uci_loader import load_uci_dir

    return load_uci_dir(RAW)


@pytest.fixture(scope="module")
def real_app(real_bundle):
    class _Repo:
        def get(self, dataset_id):
            if dataset_id != "ds_uci_551":
                raise KeyError(f"dataset '{dataset_id}' not found")
            return real_bundle

    mp = pytest.MonkeyPatch()
    mp.setattr(services, "get_repo", lambda: _Repo())
    app = FastAPI()
    app.include_router(router, prefix="/api")
    yield TestClient(app)
    mp.undo()


@needs_real
def test_real_2014_engine(real_bundle):
    f = real_bundle.frame
    train = f[f["source_year"].isin([2011, 2012, 2013])]
    sensors, summary = engine.compute_scorecard(real_bundle.year_frame(2014), train, None)
    assert len(sensors) == 11
    assert all(math.isfinite(s.score) and 0 <= s.score <= 100 for s in sensors)
    assert len(summary.trust) + len(summary.use_with_cross_check) + len(summary.verify_first) == 11


@needs_real
def test_endpoint_shape_2014(real_app):
    r = real_app.get("/api/instruments/scorecard", params={"dataset_id": "ds_uci_551", "year": 2014})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) >= {"dataset_id", "year", "window", "sensors", "summary", "computed_at_utc", "method_notes"}
    assert body["year"] == 2014 and body["window"]["source_year"] == 2014 and body["window"]["start"] == 0
    assert [s["key"] for s in body["sensors"]] == MEASUREMENT_KEYS
    s0 = body["sensors"][0]
    assert set(s0) >= {"score", "status", "missing", "out_of_range", "flatline_runs", "spikes", "coupling_drift_pairs", "computation", "what_to_check"}
    assert "not a calibration certificate" in body["disclaimer"]
    assert any("score" in n.lower() and "100" in n for n in body["method_notes"])


@needs_real
def test_endpoint_window_ok(real_app):
    r = real_app.get("/api/instruments/scorecard", params={"year": 2014, "start": 1000, "end": 1500})
    assert r.status_code == 200
    body = r.json()
    assert body["window"] == {"source_year": 2014, "start": 1000, "end": 1500}
    assert all(s["rows"] == 500 for s in body["sensors"])


@needs_real
@pytest.mark.parametrize(
    "params",
    [
        {"year": 2014, "start": 500, "end": 400},
        {"year": 2014, "start": -5, "end": 400},
        {"year": 2014, "start": 0, "end": 5},
        {"year": 2014, "start": 0, "end": 999999},
    ],
)
def test_endpoint_bad_window_422(real_app, params):
    assert real_app.get("/api/instruments/scorecard", params=params).status_code == 422


@needs_real
def test_endpoint_404s(real_app):
    assert real_app.get("/api/instruments/scorecard", params={"year": 1999}).status_code == 404
    assert real_app.get("/api/instruments/scorecard", params={"dataset_id": "nope", "year": 2014}).status_code == 404
