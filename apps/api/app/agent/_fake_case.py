"""Small, deterministic fake CaseAnalysis for agent tests and the live smoke script.

Duck-types the CaseAnalysis contract with SimpleNamespace + tiny DataFrames. The scenario
object deliberately carries a hidden `expected_behavior` so tests can prove it never leaks.
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from app.schemas import (BaselineComparison, DataQualityReport, Evidence, HypothesisEvaluation,
                         MEASUREMENT_KEYS, SampleRange, Transformation)

CASE_ID = "case_fake_0001"
YEAR = 2014
WINDOW = SampleRange(source_year=YEAR, start=1200, end=1320)
REFERENCE = SampleRange(source_year=YEAR, start=960, end=1200)
SECRET = "HIDDEN_EXPECTED_BEHAVIOR_DO_NOT_LEAK"


def _frame(start: int, end: int, rng: np.random.Generator, afdp_ramp: float = 0.0) -> pd.DataFrame:
    n = end - start
    base = {"AT": 18.0, "AP": 1012.0, "AH": 70.0, "AFDP": 3.5, "GTEP": 25.0, "TIT": 1085.0,
            "TAT": 545.0, "TEY": 133.0, "CDP": 11.8, "CO": 2.0, "NOX": 65.0}
    data = {"source_year": np.full(n, YEAR), "row_index": np.arange(start, end)}
    for k in MEASUREMENT_KEYS:
        data[k] = base[k] + rng.normal(0, 0.02 * abs(base[k]) + 1e-3, n)
    if afdp_ramp:
        data["AFDP"] = data["AFDP"] + np.linspace(0, afdp_ramp, n)
        data["TEY"] = data["TEY"] - np.linspace(0, 3.0, n)
    return pd.DataFrame(data)


def make_fake_analysis(synthetic: bool = True) -> SimpleNamespace:
    rng = np.random.default_rng(42)
    reference_frame = _frame(REFERENCE.start, REFERENCE.end, rng)
    window_frame = _frame(WINDOW.start, WINDOW.end, rng, afdp_ramp=1.4 if synthetic else 0.0)
    scenario = SimpleNamespace(
        scenario_id="S02_INTAKE_RESTRICTION" if synthetic else "S01_NORMAL",
        synthetic=synthetic,
        affected_measurements=["AFDP"] if synthetic else [],
        transformations=[Transformation(measurement="AFDP", operation="add_ramp",
                                        params={"end_delta": 1.4}, description="ramp on AFDP")]
        if synthetic else [],
        title="hidden title", description="hidden description",
        expected_behavior=SECRET,
    )
    label = "synthetic_overlay" if synthetic else "real_only"
    evidence = [
        Evidence(evidence_id="ev_afdp_01", case_id=CASE_ID,
                 kind="measured_plus_synthetic_overlay" if synthetic else "real_observation",
                 metric="AFDP", unit="mbar", title="AFDP median window vs reference",
                 sample_range=WINDOW, reference_range=REFERENCE,
                 observed_stat=4.2, comparison_stat=3.5, delta=0.7, delta_pct=20.0, z_score=4.1,
                 method="median_window_vs_reference",
                 computation="median(window AFDP)=4.20 - median(reference AFDP)=3.50 = +0.70 mbar",
                 is_synthetic=synthetic, flags=["rising_trend"]),
        Evidence(evidence_id="ev_tey_residual_01", case_id=CASE_ID, kind="model_derived",
                 metric="TEY_residual", unit="MWh", title="TEY residual (observed - expected)",
                 sample_range=WINDOW, reference_range=REFERENCE,
                 observed_stat=-1.5, comparison_stat=0.1, delta=-1.6, delta_pct=None, z_score=-2.4,
                 method="baseline_residual_mean", computation="mean residual window=-1.50 MWh vs reference=+0.10 MWh",
                 model_version="baseline_v1", flags=[]),
        Evidence(evidence_id="ev_cdp_01", case_id=CASE_ID, kind="real_observation",
                 metric="CDP", unit="mbar (as published; unit under validation)",
                 title="CDP median window vs reference", sample_range=WINDOW, reference_range=REFERENCE,
                 observed_stat=11.8, comparison_stat=11.8, delta=0.0, delta_pct=0.0, z_score=0.1,
                 method="median_window_vs_reference", computation="median(window CDP)=11.80 - median(reference CDP)=11.80 = 0.00",
                 flags=["isolated_single_sensor_check"]),
    ]
    data_quality = DataQualityReport(
        case_id=CASE_ID, missing_values={k: 0 for k in MEASUREMENT_KEYS},
        out_of_training_range={"AFDP": 3 if synthetic else 0},
        sensor_consistency_flags=["AFDP rises while CDP flat"] if synthetic else [],
        scenario_label=label, synthetic_measurements=["AFDP"] if synthetic else [],
        source="UCI_GAS_TURBINE_551", notes=["no timestamps; rows identified by source_year + row_index"],
    )
    baseline = BaselineComparison(
        case_id=CASE_ID, model_version="baseline_v1", window=WINDOW, reference=REFERENCE,
        observed_tey_mean=131.5, expected_tey_mean=133.0, residual_mean=-1.5,
        residual_std_window=0.9, residual_std_validation=0.62, residual_z=-2.4,
        reference_residual_mean=0.1, holdout_mae=0.55, holdout_r2=0.99,
        caveats=["model trained on 2011-2013 only", "CDP unit under validation"],
    )
    hypothesis_evals = {
        "intake_restriction": HypothesisEvaluation(
            case_id=CASE_ID, hypothesis_key="intake_restriction",
            supporting_evidence_ids=["ev_afdp_01", "ev_tey_residual_01"], contradicting_evidence_ids=[],
            deterministic_notes=["AFDP up while TEY residual negative"], deterministic_support_score=0.7),
        "operating_condition": HypothesisEvaluation(
            case_id=CASE_ID, hypothesis_key="operating_condition",
            supporting_evidence_ids=[], contradicting_evidence_ids=["ev_tey_residual_01"],
            deterministic_notes=["ambient-corrected residual still negative"], deterministic_support_score=0.2),
        "sensor_issue": HypothesisEvaluation(
            case_id=CASE_ID, hypothesis_key="sensor_issue",
            supporting_evidence_ids=["ev_cdp_01"], contradicting_evidence_ids=["ev_tey_residual_01"],
            deterministic_notes=["CDP flat while AFDP rises"], deterministic_support_score=0.3),
        "unknown": HypothesisEvaluation(
            case_id=CASE_ID, hypothesis_key="unknown",
            supporting_evidence_ids=[], contradicting_evidence_ids=[],
            deterministic_notes=["residual category"], deterministic_support_score=0.1),
    }
    return SimpleNamespace(
        case_id=CASE_ID, window=WINDOW, reference=REFERENCE,
        window_frame=window_frame, reference_frame=reference_frame, scenario=scenario,
        evidence=evidence, data_quality=data_quality, baseline=baseline,
        hypothesis_evals=hypothesis_evals,
    )
