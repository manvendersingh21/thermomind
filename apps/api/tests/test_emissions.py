"""Emissions-watch tests: engine on synthetic data, thresholds, window endpoint (test-local app), 422/404, real 2014."""
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
from app.features.emissions import engine
from app.features.emissions.router import router
from app.features.emissions.schemas import DISCLAIMER

REPO_ROOT = Path(__file__).resolve().parents[3]
RAW = REPO_ROOT / "data" / "raw" / "uci_551"


def synth(n: int = 400, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    f = pd.DataFrame(
        {
            "source_year": 2014,
            "row_index": np.arange(n),
            "CO": 1.0 + 0.1 * rng.random(n),
            "NOX": 50.0 + rng.random(n),
            "TEY": 140.0 + rng.normal(0, 1, n),
            "TIT": 1090.0 + rng.normal(0, 1, n),
            "AT": 15.0 + rng.normal(0, 1, n),
        }
    )
    # known CO excursion: rows 100..104 (5 samples), low load, TIT rising; peak 9.0 at row 102
    f.loc[100:104, "CO"] = [6.0, 8.0, 9.0, 7.0, 6.5]
    f.loc[100:104, "TEY"] = 100.0
    f["TIT"] = f["TIT"].astype(float)
    f.loc[97:104, "TIT"] = np.linspace(1020, 1060, 8)
    # two-sample blip (must NOT count) at rows 200..201
    f.loc[200:201, "CO"] = 9.5
    # NOX excursion rows 300..303 with a NaN-free run of 4
    f.loc[300:303, "NOX"] = 90.0
    return f


class FakeRepo:
    def __init__(self, frame: pd.DataFrame, dataset_id: str = "ds_test"):
        self.frame, self.dataset_id = frame, dataset_id

    def get(self, dataset_id: str):
        if dataset_id != self.dataset_id:
            raise KeyError(dataset_id)
        frame = self.frame
        return SimpleNamespace(year_frame=lambda y: frame[frame["source_year"] == int(y)].reset_index(drop=True))


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(services, "get_repo", lambda: FakeRepo(synth()))
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def test_engine_finds_known_excursion_and_ignores_short_blip():
    r = engine.analyze(synth(), dataset_id="ds_test", source_year=2014, co_threshold=5.0, nox_threshold=80.0)
    co = [e for e in r.excursions if e.pollutant == "CO"]
    assert len(co) == 1  # the 2-sample blip at 200-201 is below the 3-sample minimum
    e = co[0]
    assert (e.start_index, e.end_index, e.n_samples) == (100, 104, 5)
    assert e.peak_value == 9.0 and e.peak_index == 102
    assert e.peak_ratio == pytest.approx(9.0 / 5.0)
    assert e.tey_mean == pytest.approx(100.0)
    assert e.tit_change is not None and e.tit_change >= 15
    assert "part-load operation" in e.context_tags
    assert any("TIT rising" in t for t in e.context_tags)
    assert e.context_is_heuristic and "heuristic" in e.context
    nox = [e for e in r.excursions if e.pollutant == "NOX"]
    assert len(nox) == 1 and (nox[0].start_index, nox[0].n_samples) == (300, 4)
    assert r.kpis.hours_above_co == 7  # 5 + the 2-sample blip count as samples above, only runs>=3 are excursions
    assert r.kpis.excursions_co == 1 and r.kpis.excursions_nox == 1 and r.kpis.excursions_total == 2


def test_default_threshold_is_year_p95():
    f = synth()
    r = engine.analyze(f, dataset_id="ds_test", source_year=2014)
    assert r.thresholds.co == pytest.approx(float(np.percentile(f["CO"], 95)))
    assert r.thresholds.nox == pytest.approx(float(np.percentile(f["NOX"], 95)))
    assert r.thresholds.co_source == "default_p95_of_year"
    assert "not a permit limit" in r.thresholds.label
    r2 = engine.analyze(f, dataset_id="ds_test", source_year=2014, co_threshold=5.0)
    assert r2.thresholds.co == 5.0 and r2.thresholds.co_source == "user"
    assert r2.thresholds.co_default_p95 == pytest.approx(r.thresholds.co)


def test_runs_break_on_nan_and_row_gaps():
    vals = np.array([9, 9, np.nan, 9, 9, 9, 9, 9], dtype=float)
    ri = np.array([0, 1, 2, 3, 4, 5, 7, 8])  # gap between 5 and 7
    assert engine.find_runs(vals, ri, 5.0) == [(3, 5)]


def test_correlation_sign_and_profile_shape():
    f = synth()
    f["TEY"] = np.linspace(100, 160, len(f))
    f["CO"] = 10.0 - 0.05 * f["TEY"] + np.random.default_rng(1).normal(0, 0.01, len(f))
    r = engine.analyze(f, dataset_id="ds_test", source_year=2014)
    assert r.kpis.corr_co_tey.pearson < -0.99 and r.kpis.corr_co_tey.spearman < -0.99
    assert len(r.profile_tey) == 10
    meds = [b.co_median for b in r.profile_tey]
    assert meds == sorted(meds, reverse=True)  # CO falls as load proxy rises (by construction)
    assert sum(b.n for b in r.profile_tey) == len(f)


def test_downsample_preserves_peak_and_caps_points():
    f = synth(n=9000)
    f.loc[4321:4323, "CO"] = 50.0
    r = engine.analyze(f, dataset_id="ds_test", source_year=2014, co_threshold=5.0, nox_threshold=80.0)
    assert len(r.series) <= 2000 and r.downsample_factor == 5
    assert max(p.co for p in r.series) == 50.0
    assert r.kpis.rows_analyzed == 9000


def test_overview_endpoint_shape(client):
    res = client.get("/api/emissions/overview", params={"dataset_id": "ds_test", "year": 2014})
    assert res.status_code == 200, res.text
    j = res.json()
    for k in ("kpis", "thresholds", "profile_tey", "profile_tit", "excursions", "series", "disclaimer", "distribution_co"):
        assert k in j
    assert j["disclaimer"] == DISCLAIMER and j["screening_only"] is True
    assert j["provenance_kind"] == "real_observation"
    assert j["start"] == 0 and j["end"] == 400


def test_window_endpoint_shape_and_subset(client):
    res = client.get(
        "/api/emissions/window",
        params={"dataset_id": "ds_test", "year": 2014, "start": 90, "end": 120, "co_threshold": 5, "nox_threshold": 80},
    )
    assert res.status_code == 200, res.text
    j = res.json()
    assert (j["start"], j["end"]) == (90, 120)
    assert j["kpis"]["rows_analyzed"] == 30
    assert [e["start_index"] for e in j["excursions"]] == [100]
    assert all(90 <= p["row_index"] < 120 for p in j["series"])
    # default thresholds in a window remain the whole-year p95
    d = client.get("/api/emissions/window", params={"dataset_id": "ds_test", "year": 2014, "start": 0, "end": 50}).json()
    o = client.get("/api/emissions/overview", params={"dataset_id": "ds_test", "year": 2014}).json()
    assert d["thresholds"]["co"] == o["thresholds"]["co"]


@pytest.mark.parametrize(
    "path,params,code",
    [
        ("overview", {"year": 2014, "co_threshold": -1}, 422),
        ("overview", {"year": 2014, "co_threshold": 0}, 422),
        ("overview", {"year": 2014, "nox_threshold": "nan"}, 422),
        ("overview", {"year": 2014, "nox_threshold": "abc"}, 422),
        ("overview", {}, 422),
        ("window", {"year": 2014, "start": 50, "end": 50}, 422),
        ("window", {"year": 2014, "start": 60, "end": 10}, 422),
        ("window", {"year": 2014, "start": -1, "end": 10}, 422),
        ("window", {"year": 2014, "start": 10}, 422),
        ("window", {"year": 2014, "start": 1000, "end": 1100}, 422),  # beyond the data
        ("window", {"year": 2014, "start": 10, "end": 12}, 422),  # < 3 rows
        ("overview", {"year": 1999}, 404),
        ("overview", {"year": 2014, "dataset_id": "nope"}, 404),
    ],
)
def test_bad_input_status(client, path, params, code):
    params = {"dataset_id": "ds_test", **params}
    res = client.get(f"/api/emissions/{path}", params=params)
    assert res.status_code == code, res.text
    assert "detail" in res.json()


def test_dataset_without_co_nox_is_422(monkeypatch):
    f = synth().drop(columns=["CO"])
    monkeypatch.setattr(services, "get_repo", lambda: FakeRepo(f))
    app = FastAPI()
    app.include_router(router, prefix="/api")
    res = TestClient(app).get("/api/emissions/overview", params={"dataset_id": "ds_test", "year": 2014})
    assert res.status_code == 422


@pytest.mark.skipif(not (RAW / "gt_2014.csv").is_file(), reason="real UCI raw files not present")
def test_real_2014_run_has_finite_kpis(monkeypatch):
    from app.data.uci_loader import load_uci_dir

    bundle = load_uci_dir(RAW)
    monkeypatch.setattr(services, "get_repo", lambda: SimpleNamespace(get=lambda _id: bundle))
    app = FastAPI()
    app.include_router(router, prefix="/api")
    res = TestClient(app).get("/api/emissions/overview", params={"dataset_id": "ds_uci_551", "year": 2014})
    assert res.status_code == 200, res.text
    j = res.json()
    k = j["kpis"]
    assert k["rows_analyzed"] == j["total_rows_in_year"] > 5000
    for key in ("hours_above_co", "hours_above_nox", "excursions_total"):
        assert k[key] > 0
    for c in ("corr_co_tey", "corr_co_at", "corr_nox_tey", "corr_nox_at"):
        for m in ("pearson", "spearman"):
            assert math.isfinite(k[c][m])
    # honest data check: in the real 2014 data CO is higher at the lowest load decile than at the highest
    prof = j["profile_tey"]
    assert prof[0]["co_median"] > prof[-1]["co_median"]
    assert k["corr_co_tey"]["spearman"] < 0
    assert len(j["series"]) <= 2000
    assert all(math.isfinite(e["peak_value"]) for e in j["excursions"])
