"""Tests for app.analytics.torch_baseline / app.analytics.comparison (GPU / challenger-model agent).

The whole module is skipped when torch is not installed (it is an optional extra: requirements-gpu.txt).
Training uses a tiny MLP for a few epochs on every 10th row of the real UCI data (chronological split) or,
when the raw files are absent, on the 300-row 2014 fixture, which ``chronological_split`` turns into the
documented ordered 70/15/15 fallback split (single source_year). Whole module runs in well under 60 s.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

torch = pytest.importorskip("torch")

from app.analytics._io import load_fixture_frame, load_raw_frame  # noqa: E402
from app.analytics.comparison import (  # noqa: E402
    SELECTION_RULE, comparison_table, gpu_info, load_challengers, load_model_comparison,
)
from app.analytics.torch_baseline import (  # noqa: E402
    JSON_NAME, WEIGHTS_NAME, TorchBaselineModel, train_torch_baseline,
)
from app.schemas import FEATURE_KEYS, TARGET_KEY, ModelComparison, ModelEvaluation  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
RAW_UCI_DIR = REPO_ROOT / "data" / "raw" / "uci_551"
FIXTURE = REPO_ROOT / "data" / "fixtures" / "gt_2014_sample300.csv"
RAW_AVAILABLE = RAW_UCI_DIR.exists() and len(list(RAW_UCI_DIR.glob("gt_*.csv"))) == 5
PRODUCTION_JSON = REPO_ROOT / "data" / "models" / "baseline_v1.json"

TINY = dict(epochs=6, patience=3, batch_size=256, hidden=(32, 32, 16))


@pytest.fixture(scope="module")
def small_frame() -> pd.DataFrame:
    if RAW_AVAILABLE:
        return load_raw_frame(RAW_UCI_DIR).iloc[::10].reset_index(drop=True)
    return load_fixture_frame(FIXTURE, 2014)


@pytest.fixture(scope="module")
def trained(small_frame, tmp_path_factory) -> tuple[ModelEvaluation, Path]:
    model_dir = tmp_path_factory.mktemp("challenger")
    evaluation = train_torch_baseline(small_frame, model_dir, seed=42, device="cpu", **TINY)
    return evaluation, model_dir


def test_evaluation_contract_and_split(trained, small_frame):
    evaluation, model_dir = trained
    assert (model_dir / WEIGHTS_NAME).exists() and (model_dir / JSON_NAME).exists()
    on_disk = ModelEvaluation.model_validate(json.loads((model_dir / JSON_NAME).read_text()))
    assert on_disk.model_version == evaluation.model_version == "mlp_v1"
    assert evaluation.model_id == "challenger_tey_mlp"
    assert evaluation.role == "challenger"
    assert evaluation.algorithm.startswith("torch.nn MLP")
    assert evaluation.features == FEATURE_KEYS and evaluation.target == TARGET_KEY
    assert evaluation.device == "cpu"
    assert evaluation.training_seconds is not None and evaluation.training_seconds > 0
    assert set(evaluation.naive_baselines) == {"train_mean", "previous_observation"}
    assert set(evaluation.residual_quantiles_validation) == {"p01", "p05", "p50", "p95", "p99"}
    assert set(evaluation.feature_ranges_train) == set(FEATURE_KEYS)
    if RAW_AVAILABLE:
        assert evaluation.split.method == "chronological_by_source_year"
        assert evaluation.split.train_years == [2011, 2012, 2013]
        assert evaluation.split.validation_years == [2014] and evaluation.split.test_years == [2015]
    else:
        assert evaluation.split.method == "ordered_70_15_15_fallback"
    assert evaluation.split.train_rows + evaluation.split.validation_rows + evaluation.split.test_rows == len(small_frame)
    joined = " ".join(evaluation.notes).lower()
    for phrase in ("challenger", "non-convex", "not meaningful", "validation mae", "no verified fault labels"):
        assert phrase in joined, phrase


def test_metrics_finite(trained):
    evaluation, _ = trained
    for ms in (evaluation.validation, evaluation.holdout, *evaluation.naive_baselines.values()):
        assert np.isfinite(ms.mae) and np.isfinite(ms.rmse) and np.isfinite(ms.r2)
        assert ms.mae >= 0 and ms.rmse >= ms.mae and ms.n > 0
    assert np.isfinite(evaluation.residual_std_validation) and evaluation.residual_std_validation > 0
    q = evaluation.residual_quantiles_validation
    assert q["p01"] <= q["p05"] <= q["p50"] <= q["p95"] <= q["p99"]
    # even a few epochs must beat predicting the training mean on the holdout
    assert evaluation.holdout.mae < evaluation.naive_baselines["train_mean"].mae


def test_predictions_finite_and_interface(trained, small_frame):
    _, model_dir = trained
    model = TorchBaselineModel.load(model_dir)
    assert model.version == model.evaluation.model_version == "mlp_v1"
    window = small_frame.iloc[:120]
    pred = model.predict(window)
    assert pred.shape == (120,) and np.isfinite(pred).all()
    assert pred.min() > 50 and pred.max() < 250  # plausible TEY range (MWh)
    assert np.allclose(model.residuals(window), window[TARGET_KEY].to_numpy() - pred)
    counts = model.out_of_range_counts(window)
    assert set(counts) == set(FEATURE_KEYS) and all(v >= 0 for v in counts.values())
    assert model.predict(window.iloc[:0]).shape == (0,)
    nan_window = window.iloc[:5].copy()
    nan_window.loc[nan_window.index[2], "AFDP"] = np.nan
    p = model.predict(nan_window)
    assert np.isnan(p[2]) and np.isfinite(p[[0, 1, 3, 4]]).all()


def test_predict_matches_after_reload(trained, small_frame):
    _, model_dir = trained
    m1 = TorchBaselineModel.load(model_dir)
    m2 = TorchBaselineModel.load(model_dir)
    sample = small_frame.iloc[:200]
    np.testing.assert_allclose(m1.predict(sample), m2.predict(sample), rtol=0, atol=1e-6)
    # the reloaded model must reproduce the validation metrics stored in the json (same split, same weights)
    if RAW_AVAILABLE:
        val = small_frame[small_frame["source_year"] == 2014]
    else:
        n = len(small_frame)
        val = small_frame.sort_values(["source_year", "row_index"]).iloc[int(n * 0.7):int(n * 0.7) + int(n * 0.15)]
    mae = float(np.mean(np.abs(val[TARGET_KEY].to_numpy() - m1.predict(val))))
    assert abs(mae - m1.evaluation.validation.mae) < 1e-4


def test_reproducible_given_seed_on_cpu(small_frame, tmp_path):
    e1 = train_torch_baseline(small_frame, tmp_path / "a", seed=7, device="cpu", epochs=3, patience=3,
                              batch_size=256, hidden=(16, 16))
    e2 = train_torch_baseline(small_frame, tmp_path / "b", seed=7, device="cpu", epochs=3, patience=3,
                              batch_size=256, hidden=(16, 16))
    assert e1.validation.mae == pytest.approx(e2.validation.mae, abs=1e-6)
    sample = small_frame.iloc[:50]
    np.testing.assert_allclose(TorchBaselineModel.load(tmp_path / "a").predict(sample),
                               TorchBaselineModel.load(tmp_path / "b").predict(sample), atol=1e-6)


def test_load_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        TorchBaselineModel.load(tmp_path / "nope")


def test_gpu_info_returns_dict():
    info = gpu_info()
    assert isinstance(info, dict)
    assert set(info) >= {"available", "name", "memory_mb", "driver"}
    assert isinstance(info["available"], bool)
    if torch.cuda.is_available():
        assert info["available"] is True and info["name"] and info["memory_mb"] > 0


@pytest.fixture
def production_dir(tmp_path) -> Path:
    """A model dir holding only the production evaluation json (copied from data/models, else a stub)."""
    if PRODUCTION_JSON.exists():
        (tmp_path / "baseline_v1.json").write_text(PRODUCTION_JSON.read_text())
    else:
        from app.analytics.train import train_baseline

        train_baseline(load_fixture_frame(FIXTURE, 2014), tmp_path, seed=42)
    return tmp_path


def test_comparison_without_challenger(production_dir):
    comparison = load_model_comparison(production_dir)
    assert isinstance(comparison, ModelComparison)
    assert comparison.production.role == "production_baseline"
    assert comparison.challengers == []
    assert comparison.selection_rule == SELECTION_RULE and "never on the 2015 holdout" in comparison.selection_rule
    assert isinstance(comparison.gpu, dict) and "available" in comparison.gpu
    assert "baseline_v1" in comparison_table(comparison)


def test_comparison_with_challenger(production_dir, trained):
    _, challenger_dir = trained
    (production_dir / JSON_NAME).write_text((challenger_dir / JSON_NAME).read_text())
    (production_dir / "garbage.json").write_text("{not json")  # must be ignored, never crash
    comparison = load_model_comparison(production_dir)
    assert [c.model_version for c in comparison.challengers] == ["mlp_v1"]
    assert comparison.challengers[0].role == "challenger"
    assert comparison.production.split.method == "chronological_by_source_year" or not PRODUCTION_JSON.exists()
    table = comparison_table(comparison)
    assert "mlp_v1" in table and "challenger" in table
    assert load_challengers(production_dir / "missing") == []


def test_comparison_missing_production_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_model_comparison(tmp_path)
