"""Tests for the GPU challenger second opinion (app.analytics.second_opinion + its wiring in evidence/tools/services).

The real ``mlp_v1`` artefact (data/models/mlp_v1.{pt,json}) is used when present and torch is importable; those
tests are skipped otherwise. Agreement/hypothesis behaviour is also exercised with a tiny torch-free fake challenger.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from app import config, services
from app.agent.tools import ToolRunner
from app.analytics.evidence import (
    CHALLENGER_EVIDENCE_IDS, MODEL_AGREEMENT_ID, CHALLENGER_RESIDUAL_ID, analyze_case,
)
from app.analytics.scenarios import apply_scenario
from app.analytics.second_opinion import AGREEMENT_LABELS, classify_agreement, compute_second_opinion
from app.schemas import TARGET_KEY, SampleRange
from tests.test_baseline import model, raw_frame, trained, year_2014  # noqa: F401  (session fixtures)

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_MODEL_DIR = REPO_ROOT / "data" / "models"
ARTIFACT_PRESENT = (REAL_MODEL_DIR / "mlp_v1.pt").is_file() and (REAL_MODEL_DIR / "mlp_v1.json").is_file()
WINDOW = SampleRange(source_year=2014, start=1200, end=1320)
REFERENCE = SampleRange(source_year=2014, start=960, end=1200)
SCENARIOS = ("S01_NORMAL", "S02_INTAKE_RESTRICTION", "S03_SENSOR_INCONSISTENCY", "S04_AMBIENT_SHIFT")


def _has_torch() -> bool:
    try:
        import torch  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


needs_artifact = pytest.mark.skipif(not (ARTIFACT_PRESENT and _has_torch()),
                                    reason="mlp_v1 artefact or torch not available")


@pytest.fixture(scope="module")
def challenger():
    if not (ARTIFACT_PRESENT and _has_torch()):
        pytest.skip("mlp_v1 artefact or torch not available")
    from app.analytics.torch_baseline import TorchBaselineModel

    return TorchBaselineModel.load(REAL_MODEL_DIR, device=None)  # cuda:0 when available, else cpu


class _PerfectChallenger:
    """Torch-free fake: predicts observed TEY exactly, so its residual z is always 0."""

    def __init__(self, evaluation):
        self.evaluation = evaluation.model_copy(update={"model_version": "fake_v0", "role": "challenger"})
        self.version = "fake_v0"
        self.features = list(evaluation.features)

    def predict(self, frame):
        return frame[TARGET_KEY].to_numpy(dtype=float).copy()


class _BrokenChallenger(_PerfectChallenger):
    def predict(self, frame):
        raise RuntimeError("simulated CUDA failure")


def _run(year_2014, model, scenario_id, challenger=None):  # noqa: F811
    window = year_2014.iloc[WINDOW.start:WINDOW.end]
    reference = year_2014.iloc[REFERENCE.start:REFERENCE.end]
    res = apply_scenario(window, scenario_id, seed=42)
    return analyze_case(f"case_{scenario_id}", res.frame, reference, res, model, WINDOW, REFERENCE, challenger=challenger)


def _assert_finite_json(obj):
    json.dumps(obj, allow_nan=False)  # raises ValueError on NaN/inf


# ---- agreement classification ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("pz,cz,label", [
    (-3.0, -2.5, "agree_notable"), (2.0, 4.1, "agree_notable"),
    (0.3, -1.9, "agree_normal"), (0.0, 0.0, "agree_normal"),
    (-3.0, 2.5, "disagree"), (-3.0, -1.0, "disagree"), (1.5, 2.2, "disagree"),
    (None, 1.0, "disagree"), (float("nan"), 0.0, "disagree"),
])
def test_classify_agreement_constructed_cases(pz, cz, label):
    got, note = classify_agreement(pz, cz)
    assert got == label and got in AGREEMENT_LABELS and note
    if label == "disagree":
        assert "treat the residual as uncertain" in note.lower() and "do not corroborate" in note


# ---- real artefact ---------------------------------------------------------------------------------------------------

@needs_artifact
def test_second_opinion_with_real_artifact(challenger, year_2014):  # noqa: F811
    so = compute_second_opinion(year_2014.iloc[1200:1320], year_2014.iloc[960:1200], challenger, production_z=-0.5)
    _assert_finite_json(so)
    assert so["model_version"] == "mlp_v1" and so["role"] == "challenger"
    import torch

    assert so["device"].startswith("cuda:0") == torch.cuda.is_available()
    assert so["inference_ms"] > 0
    assert so["n_window"] == 120 and so["n_reference"] == 240
    for k in ("observed_tey_mean", "expected_tey_mean", "residual_mean_window", "residual_mean_reference",
              "residual_std_validation", "z_raw", "z_vs_reference"):
        assert isinstance(so[k], float) and math.isfinite(so[k]), k
    std = so["residual_std_validation"]
    assert so["residual_std_validation"] == pytest.approx(challenger.evaluation.residual_std_validation)
    assert so["z_vs_reference"] == pytest.approx((so["residual_mean_window"] - so["residual_mean_reference"]) / std)
    assert so["residual_mean_window"] == pytest.approx(so["observed_tey_mean"] - so["expected_tey_mean"], abs=1e-9)
    assert so["agreement"] in AGREEMENT_LABELS and so["agreement_note"]
    # without a production z there is nothing to compare against
    assert compute_second_opinion(year_2014.iloc[1200:1320], year_2014.iloc[960:1200], challenger)["agreement"] is None


@needs_artifact
@pytest.mark.parametrize("scenario_id", SCENARIOS)
def test_evidence_appended_and_existing_unchanged(challenger, year_2014, model, scenario_id):  # noqa: F811
    base = _run(year_2014, model, scenario_id)
    with_c = _run(year_2014, model, scenario_id, challenger=challenger)
    n = len(base.evidence)
    # every pre-existing Evidence object is identical (ids, order, numbers) and the new ones come last
    assert with_c.evidence[:n] == base.evidence
    assert [e.evidence_id for e in with_c.evidence[n:]] == [CHALLENGER_RESIDUAL_ID, MODEL_AGREEMENT_ID]
    assert with_c.data_quality == base.data_quality and with_c.baseline == base.baseline
    for key, h in base.hypothesis_evals.items():
        assert abs(with_c.hypothesis_evals[key].deterministic_support_score - h.deterministic_support_score) <= 0.1

    mlp, agree = with_c.evidence[n], with_c.evidence[n + 1]
    assert mlp.kind == "model_derived" and mlp.model_version == "mlp_v1"
    assert mlp.method == "challenger_mlp_residual_window_vs_reference"
    assert "gpu_second_opinion" in mlp.flags
    assert ("notable_deviation" in mlp.flags) == (abs(mlp.z_score) >= 2.0)
    assert "mlp_v1" in mlp.computation and any(ch.isdigit() for ch in mlp.computation)
    prod_z = base.evidence_by_id()["ev_tey_residual_01"].values["z_vs_reference"]
    assert agree.metric == "model_agreement"
    assert agree.observed_stat == pytest.approx(prod_z) and agree.comparison_stat == pytest.approx(mlp.z_score)
    label = agree.values["agreement"]
    assert label == classify_agreement(prod_z, mlp.z_score)[0] == with_c.second_opinion["agreement"]
    assert agree.flags == (["baselines_agree"] if label.startswith("agree") else ["baselines_disagree"])
    for e in with_c.evidence[n:]:
        _assert_finite_json(e.model_dump())
        assert e.sample_range == WINDOW and e.reference_range == REFERENCE
    _assert_finite_json(with_c.second_opinion)


@needs_artifact
def test_s02_default_window_agreement_is_sensible(challenger, year_2014, model):  # noqa: F811
    a = _run(year_2014, model, "S02_INTAKE_RESTRICTION", challenger=challenger)
    so = a.second_opinion
    # Observed with the shipped artefacts: production z_vs_reference ~ -1.54, challenger ~ -1.77 -> agree_normal.
    # Not forced: only require a valid label and that both residuals point the same way (negative, as the overlay
    # lowers TEY relative to its inputs).
    assert so["agreement"] in AGREEMENT_LABELS
    assert so["z_vs_reference"] < 0 and so["production_z_vs_reference"] < 0
    print(f"S02 agreement={so['agreement']} production_z={so['production_z_vs_reference']:.2f} "
          f"challenger_z={so['z_vs_reference']:.2f} device={so['device']}")


@needs_artifact
def test_tools_expose_second_opinion(challenger, year_2014, model):  # noqa: F811
    a = _run(year_2014, model, "S03_SENSOR_INCONSISTENCY", challenger=challenger)
    runner = ToolRunner(a)
    out, ids = runner.run("get_baseline_comparison", {})
    so = out["second_opinion"]
    assert so["available"] is True and so["model_version"] == "mlp_v1"
    assert "challenger, not production" in so["note"] and f"agreement={so['agreement']}" in so["note"]
    assert set(CHALLENGER_EVIDENCE_IDS) <= set(ids) and so["evidence_ids"] == list(CHALLENGER_EVIDENCE_IDS)
    _assert_finite_json(out)
    listed, list_ids = runner.run("list_evidence", {})
    assert set(CHALLENGER_EVIDENCE_IDS) <= set(list_ids) and listed["count"] == len(a.evidence)


# ---- torch-free behaviour ------------------------------------------------------------------------------------------

def test_without_challenger_behaviour_unchanged(year_2014, model):  # noqa: F811
    a = _run(year_2014, model, "S02_INTAKE_RESTRICTION")
    assert a.second_opinion is None
    assert not any(e.evidence_id in CHALLENGER_EVIDENCE_IDS for e in a.evidence)
    out, _ = ToolRunner(a).run("get_baseline_comparison", {})
    assert out["second_opinion"]["available"] is False


def test_disagreement_adds_note_but_not_score(year_2014, model):  # noqa: F811
    fake = _PerfectChallenger(model.evaluation)
    base = _run(year_2014, model, "S03_SENSOR_INCONSISTENCY")
    a = _run(year_2014, model, "S03_SENSOR_INCONSISTENCY", challenger=fake)
    prod_z = base.evidence_by_id()["ev_tey_residual_01"].values["z_vs_reference"]
    assert abs(prod_z) >= 2.0  # production sees a notable residual in this case; the fake challenger (z=0) does not
    agree = a.evidence_by_id()[MODEL_AGREEMENT_ID]
    assert agree.values["agreement"] == "disagree" and agree.flags == ["baselines_disagree"]
    assert a.evidence_by_id()[CHALLENGER_RESIDUAL_ID].z_score == 0.0
    for key in ("sensor_issue", "unknown"):
        h, h0 = a.hypothesis_evals[key], base.hypothesis_evals[key]
        assert any(n.startswith("baselines_disagree") for n in h.deterministic_notes)
        assert MODEL_AGREEMENT_ID in h.supporting_evidence_ids
        assert h.deterministic_support_score == h0.deterministic_support_score
    for key in ("intake_restriction", "operating_condition"):
        assert a.hypothesis_evals[key] == base.hypothesis_evals[key]


def test_broken_challenger_never_breaks_the_case(year_2014, model):  # noqa: F811
    base = _run(year_2014, model, "S01_NORMAL")
    a = _run(year_2014, model, "S01_NORMAL", challenger=_BrokenChallenger(model.evaluation))
    assert a.second_opinion is None and a.evidence == base.evidence
    assert any("Challenger second opinion unavailable" in n for n in a.data_quality.notes)


def test_services_get_challenger_follows_model_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MODEL_DIR", tmp_path)
    assert services.get_challenger() is None
    if ARTIFACT_PRESENT and _has_torch():
        monkeypatch.setattr(config, "MODEL_DIR", REAL_MODEL_DIR)
        c = services.get_challenger()
        assert c is not None and c.version == "mlp_v1"
        assert services.get_challenger() is c  # cached
    monkeypatch.setattr(config, "MODEL_DIR", tmp_path)
    assert services.get_challenger() is None


def test_demo_status_reports_challenger_and_gpu(client):
    body = client.get("/api/demo/status").json()
    m = body["model"]
    assert set(("challenger_ready", "challenger_version", "gpu")) <= set(m)
    assert isinstance(m["challenger_ready"], bool) and "available" in m["gpu"]
    assert m["challenger_version"] in (None, "mlp_v1")
    assert np.isfinite(m.get("holdout_mae", 0.0))
