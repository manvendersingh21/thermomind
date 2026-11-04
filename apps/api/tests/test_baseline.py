"""Tests for app.analytics.train / app.analytics.baseline (ML agent).

Shared fixtures live here and are imported by test_scenarios.py / test_evidence.py.
Training on the full raw data takes ~2 s on this machine; the subsample fixture (every 5th row) is used
for reproducibility checks.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.analytics._io import load_fixture_frame, load_raw_frame
from app.analytics.baseline import BaselineModel
from app.analytics.train import JOBLIB_NAME, JSON_NAME, chronological_split, train_baseline
from app.schemas import FEATURE_KEYS, TARGET_KEY, ModelEvaluation

# Resolve the real repo data paths directly: tests/conftest.py (Backend agent) may redirect app.config to a temp
# directory holding small fixture copies, which is too small for the default 2014 [1200,1320) window.
REPO_ROOT = Path(__file__).resolve().parents[3]
RAW_UCI_DIR = REPO_ROOT / "data" / "raw" / "uci_551"
FIXTURE_DIR = REPO_ROOT / "data" / "fixtures"
RAW_AVAILABLE = RAW_UCI_DIR.exists() and len(list(RAW_UCI_DIR.glob("gt_*.csv"))) == 5
needs_raw = pytest.mark.skipif(not RAW_AVAILABLE, reason="raw UCI csv files not present")


@pytest.fixture(scope="session")
def raw_frame() -> pd.DataFrame:
    if not RAW_AVAILABLE:
        pytest.skip("raw UCI csv files not present")
    return load_raw_frame(RAW_UCI_DIR)


@pytest.fixture(scope="session")
def subsample_frame(raw_frame: pd.DataFrame) -> pd.DataFrame:
    return raw_frame.iloc[::5].reset_index(drop=True)


@pytest.fixture(scope="session")
def trained(raw_frame: pd.DataFrame, tmp_path_factory) -> tuple[ModelEvaluation, Path]:
    model_dir = tmp_path_factory.mktemp("models_full")
    evaluation = train_baseline(raw_frame, model_dir, seed=42)
    return evaluation, model_dir


@pytest.fixture(scope="session")
def model(trained) -> BaselineModel:
    return BaselineModel.load(trained[1])


@pytest.fixture(scope="session")
def year_2014(raw_frame: pd.DataFrame) -> pd.DataFrame:
    return raw_frame[raw_frame["source_year"] == 2014].sort_values("row_index", kind="stable").reset_index(drop=True)


# ---------------------------------------------------------------------------------------------------------------------

def test_private_loader_contract_frame(raw_frame):
    assert list(raw_frame.columns[:2]) == ["source_year", "row_index"]
    assert len(raw_frame) == 36733
    assert sorted(raw_frame["source_year"].unique().tolist()) == [2011, 2012, 2013, 2014, 2015]
    for col in FEATURE_KEYS + [TARGET_KEY]:
        assert raw_frame[col].dtype == np.float64
    per_year = raw_frame.groupby("source_year")["row_index"].agg(["min", "max", "count"])
    assert (per_year["min"] == 0).all()
    assert (per_year["max"] == per_year["count"] - 1).all()


def test_split_years_correct_and_disjoint(raw_frame):
    train, val, test, split, notes = chronological_split(raw_frame)
    assert split.train_years == [2011, 2012, 2013]
    assert split.validation_years == [2014]
    assert split.test_years == [2015]
    assert split.method == "chronological_by_source_year"
    assert notes == []
    assert set(train["source_year"]).isdisjoint(set(val["source_year"]))
    assert set(train["source_year"]).isdisjoint(set(test["source_year"]))
    assert set(val["source_year"]).isdisjoint(set(test["source_year"]))
    assert len(train) + len(val) + len(test) == len(raw_frame)
    assert split.train_rows == len(train) and split.validation_rows == len(val) and split.test_rows == len(test)


def test_fallback_split_on_single_year_fixture(tmp_path):
    frame = load_fixture_frame(FIXTURE_DIR / "gt_2014_sample300.csv", 2014)
    assert len(frame) == 300
    evaluation = train_baseline(frame, tmp_path, seed=42)
    assert evaluation.split.method == "ordered_70_15_15_fallback"
    assert evaluation.split.train_rows == 210 and evaluation.split.validation_rows == 45 and evaluation.split.test_rows == 45
    assert any("70/15/15" in n for n in evaluation.notes)


def test_training_artifacts_and_evaluation_contract(trained):
    evaluation, model_dir = trained
    assert (model_dir / JOBLIB_NAME).exists() and (model_dir / JSON_NAME).exists()
    on_disk = ModelEvaluation.model_validate(json.loads((model_dir / JSON_NAME).read_text()))
    assert on_disk.model_version == evaluation.model_version == "baseline_v1"
    assert evaluation.model_id == "baseline_tey_hgbr"
    assert evaluation.features == FEATURE_KEYS
    assert evaluation.target == "TEY" and evaluation.target_unit == "MWh"
    assert TARGET_KEY not in evaluation.features and "CO" not in evaluation.features and "NOX" not in evaluation.features
    assert set(evaluation.feature_ranges_train) == set(FEATURE_KEYS)
    assert set(evaluation.residual_quantiles_validation) == {"p01", "p05", "p50", "p95", "p99"}
    assert set(evaluation.naive_baselines) == {"train_mean", "previous_observation"}
    assert evaluation.naive_baselines["previous_observation"].n == evaluation.holdout.n - 1  # first row of the year dropped
    joined = " ".join(evaluation.notes).lower()
    for phrase in ("contemporaneous", "not a physics", "dispatch", "no verified fault labels", "cdp unit", "leakage"):
        assert phrase in joined, phrase


def test_metrics_finite_and_model_beats_naive(trained):
    evaluation, _ = trained
    for ms in (evaluation.validation, evaluation.holdout, *evaluation.naive_baselines.values()):
        assert np.isfinite(ms.mae) and np.isfinite(ms.rmse) and np.isfinite(ms.r2)
        assert ms.mae >= 0 and ms.rmse >= ms.mae
    assert np.isfinite(evaluation.residual_std_validation) and evaluation.residual_std_validation > 0
    assert evaluation.holdout.mae < evaluation.naive_baselines["train_mean"].mae
    assert evaluation.holdout.mae < evaluation.naive_baselines["previous_observation"].mae
    q = evaluation.residual_quantiles_validation
    assert q["p01"] <= q["p05"] <= q["p50"] <= q["p95"] <= q["p99"]


def test_reproducible_given_seed(subsample_frame, tmp_path):
    e1 = train_baseline(subsample_frame, tmp_path / "a", seed=42)
    e2 = train_baseline(subsample_frame, tmp_path / "b", seed=42)
    assert e1.holdout.mae == e2.holdout.mae
    assert e1.validation.rmse == e2.validation.rmse
    m1, m2 = BaselineModel.load(tmp_path / "a"), BaselineModel.load(tmp_path / "b")
    sample = subsample_frame.iloc[:50]
    np.testing.assert_array_equal(m1.predict(sample), m2.predict(sample))


def test_predictions_non_nan_and_residuals(model, year_2014):
    window = year_2014.iloc[1200:1320]
    pred = model.predict(window)
    assert pred.shape == (120,)
    assert np.isfinite(pred).all()
    assert np.allclose(model.residuals(window), window[TARGET_KEY].to_numpy() - pred)
    assert model.version == model.evaluation.model_version == "baseline_v1"
    # predictions live in the plausible TEY range of the data set
    assert pred.min() > 90 and pred.max() < 200


def test_predict_handles_nan_rows(model, year_2014):
    window = year_2014.iloc[:5].copy()
    window.loc[window.index[2], "AFDP"] = np.nan
    pred = model.predict(window)
    assert np.isnan(pred[2]) and np.isfinite(pred[[0, 1, 3, 4]]).all()


def test_out_of_range_counts(model, year_2014):
    window = year_2014.iloc[1200:1320].copy()
    assert all(v == 0 for v in model.out_of_range_counts(window).values())
    lo, hi = model.evaluation.feature_ranges_train["CDP"]
    window.loc[window.index[:7], "CDP"] = hi + 5.0
    counts = model.out_of_range_counts(window)
    assert counts["CDP"] == 7
    assert set(counts) == set(FEATURE_KEYS)


def test_load_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        BaselineModel.load(tmp_path / "nope")
