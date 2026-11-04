"""Tests for app.analytics.evidence / app.analytics.anomaly (ML agent)."""
from __future__ import annotations

import numpy as np
import pytest

from app.analytics.anomaly import correlation, spike_segments, trend_slope, window_vs_reference
from app.analytics.evidence import NOTABLE_FLAG, CaseAnalysis, analyze_case, top_hypothesis
from app.analytics.scenarios import apply_scenario
from app.schemas import HYPOTHESIS_KEYS, Evidence, SampleRange
from tests.test_baseline import model, raw_frame, trained, year_2014  # noqa: F401  (session fixtures)

WINDOW = SampleRange(source_year=2014, start=1200, end=1320)
REFERENCE = SampleRange(source_year=2014, start=960, end=1200)
REQUIRED_IDS = [
    "ev_afdp_01", "ev_afdp_02", "ev_tey_residual_01", "ev_tey_01", "ev_cdp_01", "ev_tit_01", "ev_tat_01",
    "ev_gtep_01", "ev_at_01", "ev_ah_01", "ev_ap_01", "ev_coherence_01", "ev_ood_01",
]


def _analyze(year_2014, model, scenario_id: str) -> CaseAnalysis:  # noqa: F811
    window = year_2014.iloc[WINDOW.start:WINDOW.end]
    reference = year_2014.iloc[REFERENCE.start:REFERENCE.end]
    res = apply_scenario(window, scenario_id, seed=42)
    return analyze_case(f"case_{scenario_id}", res.frame, reference, res, model, WINDOW, REFERENCE)


@pytest.fixture(scope="module")
def analyses(year_2014, model):  # noqa: F811
    return {sid: _analyze(year_2014, model, sid) for sid in
            ("S01_NORMAL", "S02_INTAKE_RESTRICTION", "S03_SENSOR_INCONSISTENCY", "S04_AMBIENT_SHIFT")}


# ---- anomaly helpers -------------------------------------------------------------------------------------------------

def test_window_vs_reference_numbers():
    r = np.array([10.0, 12.0, 11.0, 9.0, 13.0, 11.0])
    w = np.array([20.0, 21.0, 19.0])
    s = window_vs_reference(w, r)
    assert s["median_w"] == 20.0 and s["median_r"] == 11.0 and s["delta"] == 9.0
    assert abs(s["delta_pct"] - 900 / 11) < 1e-9
    assert s["n"] == 3 and s["n_ref"] == 6
    assert abs(s["z"] - (20.0 - 11.0) / np.std(r, ddof=1)) < 1e-12


def test_trend_slope_and_correlation():
    assert abs(trend_slope(np.arange(10) * 2.5 + 3) - 2.5) < 1e-12
    assert abs(trend_slope([1.0, np.nan, 3.0]) - 1.0) < 1e-12
    assert np.isnan(trend_slope([1.0]))
    assert abs(correlation(np.arange(10), -np.arange(10)) + 1.0) < 1e-12


def test_spike_segments_robust_z():
    base = np.sin(np.linspace(0, 6, 100)) * 0.1
    series = base.copy()
    series[40:50] += 5.0
    segs = spike_segments(series, z_thresh=3.0)
    assert len(segs) == 1 and segs[0][0] == 40 and segs[0][1] == 50 and segs[0][2] > 3
    assert spike_segments(base, z_thresh=3.0) == []
    assert spike_segments(np.full(20, 1.0)) == []


# ---- evidence structure ----------------------------------------------------------------------------------------------

def test_evidence_ids_unique_ranges_valid_and_contract_fields(analyses):
    for a in analyses.values():
        ids = [e.evidence_id for e in a.evidence]
        assert len(ids) == len(set(ids))
        assert all(eid in ids for eid in REQUIRED_IDS)
        for e in a.evidence:
            assert isinstance(e, Evidence)
            assert e.evidence_id.startswith("ev_") and e.case_id == a.case_id
            assert e.sample_range.source_year == WINDOW.source_year
            assert WINDOW.start <= e.sample_range.start < e.sample_range.end <= WINDOW.end
            assert e.computation and any(ch.isdigit() for ch in e.computation)
            if e.kind == "model_derived":
                assert e.model_version == "baseline_v1"
        assert set(a.hypothesis_evals) == set(HYPOTHESIS_KEYS)
        for h in a.hypothesis_evals.values():
            assert 0.0 <= h.deterministic_support_score <= 1.0
            assert any("heuristic" in n for n in h.deterministic_notes)
            known = set(ids)
            assert set(h.supporting_evidence_ids) <= known and set(h.contradicting_evidence_ids) <= known


def test_provenance_kinds_follow_affected_measurements(analyses):
    s01 = analyses["S01_NORMAL"].evidence_by_id()
    assert s01["ev_afdp_01"].kind == "real_observation" and not s01["ev_afdp_01"].is_synthetic
    assert s01["ev_tey_residual_01"].kind == "model_derived" and not s01["ev_tey_residual_01"].is_synthetic
    assert analyses["S01_NORMAL"].data_quality.scenario_label == "real_only"
    s02 = analyses["S02_INTAKE_RESTRICTION"].evidence_by_id()
    assert s02["ev_afdp_01"].kind == "measured_plus_synthetic_overlay" and s02["ev_afdp_01"].is_synthetic
    assert s02["ev_tit_01"].kind == "real_observation" and not s02["ev_tit_01"].is_synthetic
    assert s02["ev_tey_residual_01"].kind == "model_derived" and s02["ev_tey_residual_01"].is_synthetic
    assert analyses["S02_INTAKE_RESTRICTION"].data_quality.synthetic_measurements == ["AFDP", "TEY", "CDP"]
    assert analyses["S02_INTAKE_RESTRICTION"].data_quality.scenario_label == "synthetic_overlay"


def test_s02_intake_restriction_is_top_with_notable_afdp(analyses):
    a = analyses["S02_INTAKE_RESTRICTION"]
    by = a.evidence_by_id()
    assert NOTABLE_FLAG in by["ev_afdp_01"].flags and by["ev_afdp_01"].z_score >= 2.0
    assert NOTABLE_FLAG in by["ev_afdp_02"].flags and by["ev_afdp_02"].observed_stat > 0  # positive slope
    assert top_hypothesis(a.hypothesis_evals) == "intake_restriction"
    h = a.hypothesis_evals["intake_restriction"]
    assert "ev_afdp_01" in h.supporting_evidence_ids
    assert h.deterministic_support_score > a.hypothesis_evals["sensor_issue"].deterministic_support_score
    assert a.baseline is not None and a.baseline.residual_mean < a.baseline.reference_residual_mean
    assert by["ev_coherence_01"].values["count"] >= 2


def test_s03_sensor_issue_top_with_low_coherence(analyses):
    a = analyses["S03_SENSOR_INCONSISTENCY"]
    by = a.evidence_by_id()
    assert top_hypothesis(a.hypothesis_evals) == "sensor_issue"
    assert by["ev_coherence_01"].values["count"] <= 1
    assert "ev_cdp_02" in by and by["ev_cdp_02"].values["isolated_segments"] >= 1
    assert "isolated_single_sensor" in by["ev_cdp_02"].flags
    assert NOTABLE_FLAG not in by["ev_afdp_01"].flags
    assert "ev_afdp_01" in a.hypothesis_evals["intake_restriction"].contradicting_evidence_ids
    assert any("CDP" in f for f in a.data_quality.sensor_consistency_flags)
    # the isolated segment range lies inside the overlaid rows [1240, 1280)
    assert 1240 <= by["ev_cdp_02"].sample_range.start < by["ev_cdp_02"].sample_range.end <= 1280


def test_s01_no_notable_residual_on_default_window(analyses):
    a = analyses["S01_NORMAL"]
    by = a.evidence_by_id()
    assert NOTABLE_FLAG not in by["ev_tey_residual_01"].flags
    assert NOTABLE_FLAG not in by["ev_tey_residual_02"].flags
    assert top_hypothesis(a.hypothesis_evals) == "unknown"
    assert a.hypothesis_evals["intake_restriction"].deterministic_support_score == 0.0
    assert a.data_quality.sensor_consistency_flags == []
    assert a.data_quality.synthetic_measurements == []


def test_ood_counts_computed(analyses):
    s01 = analyses["S01_NORMAL"]
    assert set(s01.data_quality.out_of_training_range) == set(s01.evidence_by_id()["ev_ood_01"].values["counts"])
    assert all(v == 0 for v in s01.data_quality.out_of_training_range.values())
    s03 = analyses["S03_SENSOR_INCONSISTENCY"]
    ood = s03.evidence_by_id()["ev_ood_01"]
    assert ood.values["counts"]["CDP"] == s03.data_quality.out_of_training_range["CDP"] >= 1
    assert "out_of_training_range" in ood.flags and ood.model_version == "baseline_v1"


def test_baseline_comparison_contract(analyses):
    b = analyses["S01_NORMAL"].baseline
    assert b is not None and b.model_version == "baseline_v1" and b.unit == "MWh"
    assert abs(b.residual_z - b.residual_mean / b.residual_std_validation) < 1e-9
    assert abs(b.observed_tey_mean - b.expected_tey_mean - b.residual_mean) < 1e-6
    assert b.holdout_mae > 0 and 0 < b.holdout_r2 <= 1 and b.caveats


def test_no_model_skips_model_evidence(year_2014):  # noqa: F811
    window = year_2014.iloc[WINDOW.start:WINDOW.end]
    reference = year_2014.iloc[REFERENCE.start:REFERENCE.end]
    res = apply_scenario(window, "S02_INTAKE_RESTRICTION", seed=42)
    a = analyze_case("nomodel", res.frame, reference, res, None, WINDOW, REFERENCE)
    ids = {e.evidence_id for e in a.evidence}
    assert "ev_tey_residual_01" not in ids and "ev_ood_01" not in ids and "ev_afdp_01" in ids
    assert a.baseline is None
    assert any("model" in n.lower() for n in a.data_quality.notes)
    assert a.data_quality.out_of_training_range == {}
    assert set(a.hypothesis_evals) == set(HYPOTHESIS_KEYS)
