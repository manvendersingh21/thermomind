"""Deterministic evidence computation for one investigation case (``analyze_case``).

Everything here is computed from the window/reference frames and (optionally)
the baseline model. No text in this module describes what the "right answer"
is; the deterministic hypothesis scores are labelled heuristics and are
inputs for human review, not conclusions.

Notability rule: a deviation is "notable" when |z| >= NOTABLE_Z (2.0) where z
uses the reference window's std (for measurements) or the validation residual
std (for model residuals). The flag is recorded in ``Evidence.flags`` as
"notable_deviation"; nothing here asserts a fault.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.analytics.anomaly import correlation, robust_z, spike_segments, trend_slope, window_vs_reference
from app.analytics.baseline import BaselineModel
from app.analytics.scenarios import SCENARIOS, ScenarioResult
from app.schemas import (
    FEATURE_KEYS,
    HYPOTHESIS_KEYS,
    MEASUREMENT_KEYS,
    MEASUREMENTS,
    TARGET_KEY,
    UCI_SOURCE_ID,
    BaselineComparison,
    DataQualityReport,
    Evidence,
    HypothesisEvaluation,
    SampleRange,
)

NOTABLE_Z = 2.0          # |z| >= 2 -> "notable_deviation"
MOVING_Z = 1.0           # |z| >= 1 -> counts as "moving" in the cross-sensor coherence tally
SPIKE_Z = 3.0            # robust-z threshold for spike/segment detection
NOTABLE_FLAG = "notable_deviation"
HEURISTIC_NOTE = "deterministic_support_score is a fixed-rule heuristic in [0,1], not a probability and not a diagnosis."


@dataclass
class CaseAnalysis:
    case_id: str
    window: SampleRange
    reference: SampleRange
    window_frame: pd.DataFrame
    reference_frame: pd.DataFrame
    scenario: ScenarioResult
    evidence: list[Evidence] = field(default_factory=list)
    data_quality: DataQualityReport | None = None
    baseline: BaselineComparison | None = None
    hypothesis_evals: dict[str, HypothesisEvaluation] = field(default_factory=dict)

    def evidence_by_id(self) -> dict[str, Evidence]:
        return {e.evidence_id: e for e in self.evidence}


# --------------------------------------------------------------------------- helpers

def _f(x: float | None, nd: int = 3) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "nan"
    return f"{x:.{nd}f}"


def _finite(x: float) -> float | None:
    return float(x) if x is not None and math.isfinite(float(x)) else None


def _is_notable(z: float | None, thresh: float = NOTABLE_Z) -> bool:
    return z is not None and math.isfinite(z) and abs(z) >= thresh


def _unit(key: str) -> str:
    return MEASUREMENTS.get(key, {}).get("unit", "")


def _kind_for(measure: str, scenario: ScenarioResult) -> tuple[str, bool]:
    if scenario.synthetic and measure in scenario.affected_measurements:
        return "measured_plus_synthetic_overlay", True
    return "real_observation", False


def _window_vs_ref_evidence(
    evidence_id: str, case_id: str, measure: str, wf: pd.DataFrame, rf: pd.DataFrame,
    window: SampleRange, reference: SampleRange, scenario: ScenarioResult,
) -> Evidence:
    stats = window_vs_reference(wf[measure], rf[measure])
    kind, synthetic = _kind_for(measure, scenario)
    z = _finite(stats["z"])
    flags = [NOTABLE_FLAG] if _is_notable(z) else []
    dq = "pass"
    if stats["n"] == 0 or stats["n_ref"] < 2:
        dq = "fail"
    elif int(wf[measure].isna().sum()) > 0:
        dq = "warn"
    unit = _unit(measure)
    comp = (
        f"median_window={_f(stats['median_w'])} {unit} vs median_reference={_f(stats['median_r'])} {unit}; "
        f"delta={_f(stats['delta'])} ({_f(stats['delta_pct'], 2)}%); "
        f"z=(mean_window {_f(stats['mean_w'])} - mean_reference {_f(stats['mean_r'])}) / std_reference {_f(stats['std_r'])} = {_f(z, 2)}; "
        f"n_window={stats['n']}, n_reference={stats['n_ref']}"
    )
    return Evidence(
        evidence_id=evidence_id, case_id=case_id, kind=kind, metric=measure, unit=unit,
        title=f"{MEASUREMENTS.get(measure, {}).get('name', measure)} ({measure}): case window vs reference window",
        sample_range=window, reference_range=reference,
        observed_stat=_finite(stats["median_w"]), comparison_stat=_finite(stats["median_r"]),
        delta=_finite(stats["delta"]), delta_pct=_finite(stats["delta_pct"]), z_score=z,
        method="median_window_vs_reference; z=(mean_w-mean_r)/std_reference",
        computation=comp, data_quality=dq, is_synthetic=synthetic, flags=flags,
        values={k: (_finite(v) if isinstance(v, float) else v) for k, v in stats.items()},
    )


def _trend_evidence(
    evidence_id: str, case_id: str, measure: str, wf: pd.DataFrame, rf: pd.DataFrame,
    window: SampleRange, reference: SampleRange, scenario: ScenarioResult,
) -> Evidence:
    """Least-squares trend within the window; z = (slope*n) / std_reference, i.e. the fitted
    change across the whole window measured in reference standard deviations."""
    slope = trend_slope(wf[measure])
    n = int(wf[measure].notna().sum())
    ref = rf[measure].dropna().to_numpy(dtype=float)
    std_r = float(np.std(ref, ddof=1)) if ref.size > 1 else float("nan")
    ref_slope = trend_slope(rf[measure]) if ref.size > 1 else float("nan")
    total_change = slope * n if math.isfinite(slope) else float("nan")
    z = (total_change / std_r) if (math.isfinite(total_change) and math.isfinite(std_r) and std_r > 0) else float("nan")
    kind, synthetic = _kind_for(measure, scenario)
    unit = _unit(measure)
    flags = [NOTABLE_FLAG] if _is_notable(z) else []
    comp = (
        f"least-squares slope over window = {_f(slope, 5)} {unit}/sample; fitted change over n={n} samples "
        f"= {_f(total_change)} {unit}; z = {_f(total_change)} / std_reference {_f(std_r)} = {_f(z, 2)}; "
        f"reference slope for comparison = {_f(ref_slope, 5)} {unit}/sample"
    )
    return Evidence(
        evidence_id=evidence_id, case_id=case_id, kind=kind, metric=f"{measure}_trend", unit=f"{unit}/sample",
        title=f"{measure}: linear trend within the case window",
        sample_range=window, reference_range=reference,
        observed_stat=_finite(slope), comparison_stat=_finite(ref_slope),
        delta=_finite(total_change), delta_pct=None, z_score=_finite(z),
        method="least_squares_slope_per_sample; z=(slope*n)/std_reference",
        computation=comp, is_synthetic=synthetic, flags=flags,
        values={"slope_per_sample": _finite(slope), "n": n, "fitted_change": _finite(total_change),
                "std_reference": _finite(std_r), "reference_slope_per_sample": _finite(ref_slope)},
    )


def _segment_evidence(
    evidence_id: str, case_id: str, measure: str, wf: pd.DataFrame, window: SampleRange, reference: SampleRange,
    scenario: ScenarioResult, corroborating: list[str],
) -> Evidence | None:
    """Robust-z segments in ``measure``; each segment is 'isolated' when none of ``corroborating`` shows a
    |robust z| >= SPIKE_Z in the same rows (so it is not a simultaneous load change)."""
    segs = spike_segments(wf[measure], z_thresh=SPIKE_Z)
    if not segs:
        return None
    other_z = {c: np.abs(np.nan_to_num(robust_z(wf[c]), nan=0.0)) for c in corroborating if c in wf.columns}
    rows: list[dict] = []
    isolated = 0
    for start, end, peak in segs:
        coincident = [c for c, z in other_z.items() if bool((z[start:end] >= SPIKE_Z).any())]
        is_isolated = len(coincident) == 0
        isolated += int(is_isolated)
        rows.append({
            "window_rows": [start, end], "absolute_rows": [window.start + start, window.start + end],
            "peak_robust_z": round(float(peak), 2), "coincident_in": coincident, "isolated": is_isolated,
        })
    first = next((r for r in rows if r["isolated"]), rows[0])
    kind, synthetic = _kind_for(measure, scenario)
    flags = ["isolated_single_sensor"] if isolated > 0 else ["coincident_with_other_sensors"]
    if isolated > 0:
        flags.append(NOTABLE_FLAG)
    peak = max((abs(r["peak_robust_z"]) for r in rows), default=float("nan"))
    comp = (
        f"robust z = (x - median_window) / (1.4826*MAD_window), threshold |z|>={SPIKE_Z}; "
        f"{len(segs)} segment(s) found: " + "; ".join(
            f"rows[{r['window_rows'][0]},{r['window_rows'][1]}) peak_z={r['peak_robust_z']}"
            f" {'ISOLATED' if r['isolated'] else 'coincident in ' + ','.join(r['coincident_in'])}" for r in rows
        ) + f"; isolated={isolated}/{len(segs)} (checked against {', '.join(corroborating)})"
    )
    return Evidence(
        evidence_id=evidence_id, case_id=case_id, kind=kind, metric=f"{measure}_segments", unit="robust_z",
        title=f"{measure}: spike/step segments within the case window",
        sample_range=SampleRange(source_year=window.source_year, start=first["absolute_rows"][0], end=first["absolute_rows"][1]),
        reference_range=reference,
        observed_stat=_finite(peak), comparison_stat=float(SPIKE_Z), delta=None, delta_pct=None,
        z_score=_finite(float(first["peak_robust_z"])),
        method="robust_mad_z_segments; isolated if no corroborating sensor spikes in same rows",
        computation=comp, is_synthetic=synthetic, flags=flags,
        values={"segments": rows, "isolated_segments": isolated, "total_segments": len(segs),
                "corroborating_checked": corroborating},
    )


# --------------------------------------------------------------------------- main entry

def analyze_case(
    case_id: str,
    window_frame: pd.DataFrame,
    reference_frame: pd.DataFrame,
    scenario: ScenarioResult,
    model: BaselineModel | None,
    window: SampleRange,
    reference: SampleRange,
) -> CaseAnalysis:
    wf = window_frame.reset_index(drop=True)
    rf = reference_frame.reset_index(drop=True)
    info = SCENARIOS.get(scenario.scenario_id)
    scenario_label = "synthetic_overlay" if scenario.synthetic else "real_only"
    ev: list[Evidence] = []
    dq_notes: list[str] = []
    model_version = model.version if model is not None else None

    # --- measurement evidence ----------------------------------------------------
    ev.append(_window_vs_ref_evidence("ev_afdp_01", case_id, "AFDP", wf, rf, window, reference, scenario))
    ev.append(_trend_evidence("ev_afdp_02", case_id, "AFDP", wf, rf, window, reference, scenario))

    # --- model-derived residual evidence -------------------------------------------
    baseline: BaselineComparison | None = None
    resid_evidence: list[Evidence] = []
    if model is not None and len(wf) > 0:
        resid_w = model.residuals(wf)
        resid_r = model.residuals(rf) if len(rf) > 0 else np.array([], dtype=float)
        expected_w = model.predict(wf)
        std_val = float(model.evaluation.residual_std_validation)
        rw = resid_w[~np.isnan(resid_w)]
        rr = resid_r[~np.isnan(resid_r)]
        resid_mean = float(np.mean(rw)) if rw.size else float("nan")
        resid_std_w = float(np.std(rw, ddof=1)) if rw.size > 1 else float("nan")
        ref_resid_mean = float(np.mean(rr)) if rr.size else float("nan")
        z_raw = resid_mean / std_val if std_val > 0 else float("nan")
        z_ref = (resid_mean - ref_resid_mean) / std_val if (std_val > 0 and math.isfinite(ref_resid_mean)) else float("nan")
        synthetic_resid = scenario.synthetic and any(m in (*FEATURE_KEYS, TARGET_KEY) for m in scenario.affected_measurements)
        # z used for notability is the reference-adjusted one: the validation residual has a non-zero median
        # (year-to-year drift), so comparing against the reference window removes that bias.
        notable = _is_notable(z_ref)
        comp = (
            f"residual = observed TEY - expected TEY ({model_version}); mean_window={_f(resid_mean)} MWh "
            f"(observed mean {_f(float(np.nanmean(wf[TARGET_KEY])))} - expected mean {_f(float(np.nanmean(expected_w)))}); "
            f"mean_reference={_f(ref_resid_mean)} MWh; z_raw = {_f(resid_mean)} / residual_std_validation {_f(std_val)} = {_f(z_raw, 2)}; "
            f"z_vs_reference = ({_f(resid_mean)} - {_f(ref_resid_mean)}) / {_f(std_val)} = {_f(z_ref, 2)} (used for the notable flag); "
            f"std_window={_f(resid_std_w)}; n={rw.size}"
        )
        e1 = Evidence(
            evidence_id="ev_tey_residual_01", case_id=case_id, kind="model_derived", metric="TEY_residual", unit="MWh",
            title="TEY residual (observed - model expected): case window vs reference window",
            sample_range=window, reference_range=reference,
            observed_stat=_finite(resid_mean), comparison_stat=_finite(ref_resid_mean),
            delta=_finite(resid_mean - ref_resid_mean) if math.isfinite(ref_resid_mean) else None, delta_pct=None,
            z_score=_finite(z_raw),
            method="mean_residual_window_vs_reference; z=residual_mean/residual_std_validation (z_vs_reference in values)",
            computation=comp, is_synthetic=synthetic_resid, model_version=model_version,
            flags=[NOTABLE_FLAG] if notable else [],
            values={"residual_mean_window": _finite(resid_mean), "residual_mean_reference": _finite(ref_resid_mean),
                    "residual_std_window": _finite(resid_std_w), "residual_std_validation": std_val,
                    "z_raw": _finite(z_raw), "z_vs_reference": _finite(z_ref), "n": int(rw.size),
                    "features_used": list(model.features)},
        )
        resid_evidence.append(e1)

        # residual trend: slope and last-third mean vs reference (a progressive effect shows at the end of the window)
        slope = trend_slope(resid_w)
        n = int(rw.size)
        third = max(1, len(resid_w) // 3)
        last = resid_w[-third:]
        last = last[~np.isnan(last)]
        last_mean = float(np.mean(last)) if last.size else float("nan")
        z_last = (last_mean - ref_resid_mean) / std_val if (std_val > 0 and math.isfinite(ref_resid_mean)) else float("nan")
        fitted = slope * n if math.isfinite(slope) else float("nan")
        z_fit = fitted / std_val if (std_val > 0 and math.isfinite(fitted)) else float("nan")
        notable2 = _is_notable(z_last)
        comp2 = (
            f"residual slope = {_f(slope, 5)} MWh/sample -> fitted change over {n} samples = {_f(fitted)} MWh "
            f"(= {_f(z_fit, 2)} validation residual std); mean of last third (rows[{len(resid_w) - third},{len(resid_w)}) "
            f"= {_f(last_mean)} MWh; z_last_third_vs_reference = ({_f(last_mean)} - {_f(ref_resid_mean)}) / {_f(std_val)} = {_f(z_last, 2)}"
        )
        e2 = Evidence(
            evidence_id="ev_tey_residual_02", case_id=case_id, kind="model_derived", metric="TEY_residual_trend", unit="MWh",
            title="TEY residual: trend within the window and last-third mean vs reference",
            sample_range=SampleRange(source_year=window.source_year, start=window.start + len(resid_w) - third, end=window.end),
            reference_range=reference,
            observed_stat=_finite(last_mean), comparison_stat=_finite(ref_resid_mean),
            delta=_finite(last_mean - ref_resid_mean) if math.isfinite(ref_resid_mean) else None, delta_pct=None,
            z_score=_finite(z_last),
            method="residual_slope_and_last_third_mean; z=(last_third_mean-reference_mean)/residual_std_validation",
            computation=comp2, is_synthetic=synthetic_resid, model_version=model_version,
            flags=[NOTABLE_FLAG] if notable2 else [],
            values={"slope_per_sample": _finite(slope), "fitted_change": _finite(fitted), "z_fitted_change": _finite(z_fit),
                    "last_third_mean": _finite(last_mean), "z_last_third_vs_reference": _finite(z_last), "n": n},
        )
        resid_evidence.append(e2)

        caveats = [
            "Expected TEY is a statistical estimate from contemporaneous sensor readings (not a physics model); "
            "it is confounded by dispatch/load and by any synthetic overlay applied to its input features.",
            f"Validation residuals are biased (median {model.evaluation.residual_quantiles_validation.get('p50', float('nan')):.2f} MWh), "
            "so the reference-window residual mean is reported and used for the notable flag.",
            "No verified fault labels exist in the source data; residuals do not diagnose faults.",
            f"Holdout (2015) MAE {model.evaluation.holdout.mae:.2f} MWh, R2 {model.evaluation.holdout.r2:.3f}; "
            f"residual_std_validation {std_val:.2f} MWh.",
        ]
        if synthetic_resid:
            caveats.append("One or more model inputs or the target carry a synthetic overlay in this case; residuals are computed on the overlaid rows.")
        baseline = BaselineComparison(
            case_id=case_id, model_version=model_version, window=window, reference=reference,
            observed_tey_mean=float(np.nanmean(wf[TARGET_KEY])), expected_tey_mean=float(np.nanmean(expected_w)),
            residual_mean=resid_mean, residual_std_window=resid_std_w if math.isfinite(resid_std_w) else 0.0,
            residual_std_validation=std_val, residual_z=float(z_raw) if math.isfinite(z_raw) else 0.0,
            reference_residual_mean=ref_resid_mean if math.isfinite(ref_resid_mean) else 0.0,
            unit="MWh", holdout_mae=float(model.evaluation.holdout.mae), holdout_r2=float(model.evaluation.holdout.r2),
            caveats=caveats,
        )
    else:
        dq_notes.append("Baseline model not available: model-derived evidence (TEY residuals, OOD counts vs training range) was skipped.")
    ev.extend(resid_evidence)

    ev.append(_window_vs_ref_evidence("ev_tey_01", case_id, "TEY", wf, rf, window, reference, scenario))
    ev.append(_window_vs_ref_evidence("ev_cdp_01", case_id, "CDP", wf, rf, window, reference, scenario))
    cdp_seg = _segment_evidence("ev_cdp_02", case_id, "CDP", wf, window, reference, scenario, ["TEY", "AFDP", "TIT", "GTEP"])
    if cdp_seg is not None:
        ev.append(cdp_seg)
    for key in ("TIT", "TAT", "GTEP"):
        ev.append(_window_vs_ref_evidence(f"ev_{key.lower()}_01", case_id, key, wf, rf, window, reference, scenario))
    ev.append(_window_vs_ref_evidence("ev_at_01", case_id, "AT", wf, rf, window, reference, scenario))
    ev.append(_trend_evidence("ev_at_02", case_id, "AT", wf, rf, window, reference, scenario))
    ev.append(_window_vs_ref_evidence("ev_ah_01", case_id, "AH", wf, rf, window, reference, scenario))
    ev.append(_window_vs_ref_evidence("ev_ap_01", case_id, "AP", wf, rf, window, reference, scenario))

    by_id = {e.evidence_id: e for e in ev}

    # --- cross-sensor coherence (intake-restriction signature: AFDP up, TEY residual down, CDP down) ---
    afdp_z = by_id["ev_afdp_01"].z_score
    cdp_z = by_id["ev_cdp_01"].z_score
    resid_e = by_id.get("ev_tey_residual_01")
    resid_z = resid_e.values.get("z_vs_reference") if resid_e is not None else None
    tey_z = by_id["ev_tey_01"].z_score
    signs = {
        "AFDP": _sign(afdp_z), "TEY_residual": _sign(resid_z) if resid_z is not None else "n/a",
        "CDP": _sign(cdp_z), "TEY": _sign(tey_z),
    }
    corroborating = []
    if afdp_z is not None and afdp_z >= MOVING_Z:
        corroborating.append("AFDP_up")
    if resid_z is not None and resid_z <= -MOVING_Z:
        corroborating.append("TEY_residual_down")
    if cdp_z is not None and cdp_z <= -MOVING_Z:
        corroborating.append("CDP_down")
    coh_count = len(corroborating)
    corr_afdp_tey = correlation(wf["AFDP"], wf[TARGET_KEY])
    corr_cdp_tey = correlation(wf["CDP"], wf[TARGET_KEY])
    coh_flags = ["coherent_multi_sensor"] if coh_count >= 2 else ["no_coherent_pattern"]
    coh_kind = "model_derived" if model is not None else ("measured_plus_synthetic_overlay" if scenario.synthetic else "real_observation")
    ev.append(Evidence(
        evidence_id="ev_coherence_01", case_id=case_id, kind=coh_kind, metric="cross_sensor_coherence", unit="count",
        title="Cross-sensor coherence: do AFDP (up), TEY residual (down) and CDP (down) move together?",
        sample_range=window, reference_range=reference,
        observed_stat=float(coh_count), comparison_stat=3.0, delta=None, delta_pct=None, z_score=None,
        method=f"count of sensors with |z|>={MOVING_Z} in the intake-restriction direction (AFDP up, residual down, CDP down)",
        computation=(
            f"AFDP z={_f(afdp_z, 2)} ({signs['AFDP']}), TEY_residual z_vs_reference={_f(resid_z, 2)} ({signs['TEY_residual']}), "
            f"CDP z={_f(cdp_z, 2)} ({signs['CDP']}); corroborating={corroborating} -> count={coh_count}/3; "
            f"corr(AFDP,TEY)={_f(corr_afdp_tey, 2)}, corr(CDP,TEY)={_f(corr_cdp_tey, 2)} within window"
        ),
        is_synthetic=bool(scenario.synthetic), model_version=model_version if model is not None else None,
        flags=coh_flags,
        values={"signs": signs, "corroborating": corroborating, "count": coh_count, "afdp_z": _finite(afdp_z) if afdp_z is not None else None,
                "residual_z_vs_reference": resid_z, "cdp_z": _finite(cdp_z) if cdp_z is not None else None,
                "corr_afdp_tey": _finite(corr_afdp_tey), "corr_cdp_tey": _finite(corr_cdp_tey)},
    ))

    # --- out-of-training-range ---------------------------------------------------------
    ood: dict[str, int] = {}
    if model is not None:
        ood = model.out_of_range_counts(wf)
        total = int(sum(ood.values()))
        ranges = model.evaluation.feature_ranges_train
        per = ", ".join(f"{k}={v} (train range [{ranges[k][0]:.3f}, {ranges[k][1]:.3f}])" for k, v in ood.items() if v > 0) or "none"
        ev.append(Evidence(
            evidence_id="ev_ood_01", case_id=case_id, kind="model_derived", metric="out_of_training_range", unit="rows",
            title="Rows with feature values outside the model's training range",
            sample_range=window, reference_range=None,
            observed_stat=float(total), comparison_stat=0.0, delta=None, delta_pct=None, z_score=None,
            method="count rows per feature with value < train_min or > train_max (feature_ranges_train)",
            computation=f"out-of-range rows per feature: {per}; total={total} of {len(wf)} rows x {len(ood)} features",
            is_synthetic=bool(scenario.synthetic and any(k in scenario.affected_measurements for k, v in ood.items() if v > 0)),
            model_version=model_version, flags=["out_of_training_range"] if total > 0 else [],
            values={"counts": ood, "total": total, "n_rows": int(len(wf))},
        ))

    # --- data quality --------------------------------------------------------------------
    missing = {k: int(wf[k].isna().sum()) for k in MEASUREMENT_KEYS if k in wf.columns}
    consistency: list[str] = []
    by_id = {e.evidence_id: e for e in ev}
    others = {k: by_id[f"ev_{k.lower()}_01"].z_score for k in ("AFDP", "TEY", "TIT")}
    quiet = all(z is not None and abs(z) < 1.0 for z in others.values())
    if _is_notable(cdp_z) and quiet:
        consistency.append(f"CDP deviates (z={_f(cdp_z, 2)}) while AFDP/TEY/TIT do not (|z|<1)")
    if cdp_seg is not None and cdp_seg.values.get("isolated_segments", 0) > 0:
        rows_txt = ", ".join(f"[{r['absolute_rows'][0]},{r['absolute_rows'][1]})" for r in cdp_seg.values["segments"] if r["isolated"])
        consistency.append(f"CDP shows isolated step/spike segment(s) at rows {rows_txt} with no coincident change in TEY/AFDP/TIT/GTEP")
    if resid_e is not None and NOTABLE_FLAG in resid_e.flags and not _is_notable(afdp_z) and not _is_notable(tey_z):
        consistency.append("TEY residual deviates notably while raw TEY and AFDP do not: model inputs and output disagree")
    for key in ("TAT", "GTEP", "TIT"):
        z = by_id[f"ev_{key.lower()}_01"].z_score
        if _is_notable(z) and quiet and not _is_notable(cdp_z):
            consistency.append(f"{key} deviates (z={_f(z, 2)}) while AFDP/TEY/TIT-group readings stay within |z|<1")
    if any(v > 0 for v in missing.values()):
        dq_notes.append("Missing values present in the window: " + ", ".join(f"{k}={v}" for k, v in missing.items() if v))
    if scenario.synthetic:
        dq_notes.append(f"Synthetic overlay {scenario.scenario_id} (seed {scenario.seed}) applied to: {', '.join(scenario.affected_measurements)}; original rows unchanged.")
    dq_notes.append("Rows are hourly aggregates without timestamps (source_year + row_index only).")
    data_quality = DataQualityReport(
        case_id=case_id, missing_values=missing, out_of_training_range=ood, sensor_consistency_flags=consistency,
        scenario_label=scenario_label, synthetic_measurements=list(scenario.affected_measurements) if scenario.synthetic else [],
        source=UCI_SOURCE_ID, notes=dq_notes,
    )

    analysis = CaseAnalysis(
        case_id=case_id, window=window, reference=reference, window_frame=wf, reference_frame=rf, scenario=scenario,
        evidence=ev, data_quality=data_quality, baseline=baseline,
    )
    analysis.hypothesis_evals = _evaluate_hypotheses(analysis)
    _ = info  # scenario info is only used for its id/affected list; expected_behavior is never read here
    return analysis


def _sign(z: float | None) -> str:
    if z is None or not math.isfinite(z):
        return "n/a"
    if z >= MOVING_Z:
        return "up"
    if z <= -MOVING_Z:
        return "down"
    return "flat"


# --------------------------------------------------------------------------- deterministic hypothesis rules

def _evaluate_hypotheses(a: CaseAnalysis) -> dict[str, HypothesisEvaluation]:
    by_id = a.evidence_by_id()

    def notable(eid: str) -> bool:
        e = by_id.get(eid)
        return e is not None and NOTABLE_FLAG in e.flags

    def z(eid: str) -> float | None:
        e = by_id.get(eid)
        return e.z_score if e is not None else None

    afdp_notable = notable("ev_afdp_01") or notable("ev_afdp_02")
    afdp_up = any((z(e) or 0) > 0 for e in ("ev_afdp_01", "ev_afdp_02") if notable(e))
    resid1 = by_id.get("ev_tey_residual_01")
    resid2 = by_id.get("ev_tey_residual_02")
    resid_neg_notable = any(
        e is not None and NOTABLE_FLAG in e.flags and (e.values.get("z_vs_reference", e.values.get("z_last_third_vs_reference")) or 0) < 0
        for e in (resid1, resid2)
    )
    resid_notable = any(e is not None and NOTABLE_FLAG in e.flags for e in (resid1, resid2))
    resid_available = resid1 is not None
    coh = by_id["ev_coherence_01"]
    coh_count = int(coh.values.get("count", 0))
    cdp_seg = by_id.get("ev_cdp_02")
    isolated_segments = int(cdp_seg.values.get("isolated_segments", 0)) if cdp_seg is not None else 0
    ood = by_id.get("ev_ood_01")
    ood_total = int(ood.values.get("total", 0)) if ood is not None else 0
    ambient_ids = ["ev_at_01", "ev_at_02", "ev_ah_01", "ev_ap_01"]
    ambient_notable = [e for e in ambient_ids if notable(e)]
    single_sensor_ids = ["ev_cdp_01", "ev_tit_01", "ev_tat_01", "ev_gtep_01", "ev_tey_01", "ev_afdp_01"]
    single_notable = [e for e in single_sensor_ids if notable(e)]
    anything_notable = [e.evidence_id for e in a.evidence if NOTABLE_FLAG in e.flags]

    evals: dict[str, HypothesisEvaluation] = {}

    # intake_restriction ---------------------------------------------------------------
    sup, con, notes, score = [], [], [HEURISTIC_NOTE], 0.0
    if afdp_notable and afdp_up:
        sup += [e for e in ("ev_afdp_01", "ev_afdp_02") if notable(e)]
        score += 0.45
        notes.append("AFDP shows a notable upward deviation/trend vs reference (+0.45).")
    else:
        con += ["ev_afdp_01", "ev_afdp_02"]
        notes.append("AFDP is not notably elevated (|z|<2 for both level and trend): rule contradicts intake restriction.")
    if resid_neg_notable:
        sup += [e.evidence_id for e in (resid1, resid2) if e is not None and NOTABLE_FLAG in e.flags]
        score += 0.35
        notes.append("TEY residual is notably negative vs reference (+0.35).")
    elif resid_available:
        con += ["ev_tey_residual_01"]
        notes.append("TEY residual is not notably negative vs reference.")
    else:
        notes.append("No baseline model: residual evidence unavailable.")
    if coh_count >= 2:
        sup.append("ev_coherence_01")
        score += 0.2
        notes.append(f"{coh_count}/3 sensors move in the intake-restriction direction (+0.2).")
    else:
        con.append("ev_coherence_01")
        notes.append(f"Only {coh_count}/3 sensors move in the intake-restriction direction.")
    if not (afdp_notable and afdp_up):
        score = min(score, 0.15)
        notes.append("Score capped at 0.15 because AFDP is not notable.")
    evals["intake_restriction"] = HypothesisEvaluation(
        case_id=a.case_id, hypothesis_key="intake_restriction", supporting_evidence_ids=_dedupe(sup),
        contradicting_evidence_ids=_dedupe(con), deterministic_notes=notes, deterministic_support_score=round(min(1.0, score), 3),
    )

    # operating_condition --------------------------------------------------------------
    sup, con, notes, score = [], [], [HEURISTIC_NOTE], 0.0
    if ambient_notable:
        sup += ambient_notable
        score += 0.5
        notes.append(f"Ambient evidence notable: {', '.join(ambient_notable)} (+0.5).")
    else:
        con += ["ev_at_01", "ev_ah_01", "ev_ap_01"]
        notes.append("No notable ambient deviation (AT/AH/AP level, AT trend).")
    if resid_available and notable("ev_tey_01") and not resid_notable:
        sup += ["ev_tey_01", "ev_tey_residual_01"]
        score += 0.4
        notes.append("Raw TEY changed notably while the model residual did not: the change is explained by operating inputs (+0.4).")
    elif resid_available and not resid_notable and abs(z("ev_tey_01") or 0) >= MOVING_Z:
        sup += ["ev_tey_01", "ev_tey_residual_01"]
        score += 0.15
        notes.append("Raw TEY moved (|z|>=1) with no notable residual: consistent with a load/operating change (+0.15).")
    if coh_count >= 2:
        con.append("ev_coherence_01")
        score = min(score, 0.3)
        notes.append("A coherent multi-sensor fault-like pattern exists; operating-condition score capped at 0.3.")
    if resid_available and resid_notable and not ambient_notable:
        con.append("ev_tey_residual_01")
        notes.append("Residual is notable without an ambient explanation.")
    evals["operating_condition"] = HypothesisEvaluation(
        case_id=a.case_id, hypothesis_key="operating_condition", supporting_evidence_ids=_dedupe(sup),
        contradicting_evidence_ids=_dedupe(con), deterministic_notes=notes, deterministic_support_score=round(min(1.0, score), 3),
    )

    # sensor_issue ---------------------------------------------------------------------
    sup, con, notes, score = [], [], [HEURISTIC_NOTE], 0.0
    if isolated_segments > 0:
        sup.append("ev_cdp_02")
        score += 0.5
        notes.append(f"CDP has {isolated_segments} isolated spike/step segment(s) with no coincident change in TEY/AFDP/TIT/GTEP (+0.5).")
    elif cdp_seg is not None:
        con.append("ev_cdp_02")
        notes.append("CDP segments coincide with changes in other sensors (load changes), not isolated.")
    if ood_total > 0:
        sup.append("ev_ood_01")
        score += 0.15
        notes.append(f"{ood_total} feature value(s) outside the training range (+0.15).")
    if len(single_notable) == 1 and coh_count <= 1:
        sup.append(single_notable[0])
        score += 0.35
        notes.append(f"Exactly one sensor-level deviation is notable ({single_notable[0]}) and it is not corroborated (coherence count {coh_count}) (+0.35).")
    if resid_available and resid_notable and coh_count <= 1 and not afdp_notable and not ambient_notable:
        sup += [e.evidence_id for e in (resid1, resid2) if e is not None and NOTABLE_FLAG in e.flags]
        score += 0.2
        notes.append("Model residual is notable but AFDP, ambient and the coherence tally do not corroborate a mechanical cause (+0.2).")
    if coh_count >= 2:
        con.append("ev_coherence_01")
        score = min(score, 0.2)
        notes.append("Multiple sensors move coherently; sensor-issue score capped at 0.2.")
    if score == 0.0:
        con += [e for e in ("ev_cdp_01", "ev_coherence_01") if e in by_id]
        notes.append("No isolated single-sensor deviation, no isolated segments, no out-of-range values.")
    evals["sensor_issue"] = HypothesisEvaluation(
        case_id=a.case_id, hypothesis_key="sensor_issue", supporting_evidence_ids=_dedupe(sup),
        contradicting_evidence_ids=_dedupe(con), deterministic_notes=notes, deterministic_support_score=round(min(1.0, score), 3),
    )

    # unknown --------------------------------------------------------------------------
    best_other = max(e.deterministic_support_score for e in evals.values())
    sup, con, notes = [], [], [HEURISTIC_NOTE]
    if not anything_notable:
        score = 0.7
        sup += [e for e in ("ev_afdp_01", "ev_tey_residual_01", "ev_coherence_01") if e in by_id]
        notes.append("Nothing is notable (all |z|<2): no deviation to explain; 'unknown/no fault' receives default support 0.7.")
    else:
        score = max(0.05, round(1.0 - best_other, 3))
        con += anything_notable[:5]
        notes.append(f"Notable evidence exists ({len(anything_notable)} item(s)); unknown score = 1 - best other score ({best_other}).")
    evals["unknown"] = HypothesisEvaluation(
        case_id=a.case_id, hypothesis_key="unknown", supporting_evidence_ids=_dedupe(sup),
        contradicting_evidence_ids=_dedupe(con), deterministic_notes=notes, deterministic_support_score=round(min(1.0, score), 3),
    )
    return {k: evals[k] for k in HYPOTHESIS_KEYS}


def _dedupe(ids: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def top_hypothesis(evals: dict[str, HypothesisEvaluation]) -> str:
    """Key with the highest deterministic score (ties broken by HYPOTHESIS_KEYS order)."""
    return max(HYPOTHESIS_KEYS, key=lambda k: (evals[k].deterministic_support_score, -HYPOTHESIS_KEYS.index(k)))
