"""Deterministic instrument-health screening. Pure functions of the data; no I/O, no randomness.

Score formula (per sensor, n = rows in the selected window):
    score = clamp(100 - P_missing - P_ood - P_flat - P_spike - P_coupling, 0, 100)
    P_missing  = min(30, 6.0 x missing%)
    P_ood      = min(25, 2.5 x out_of_training_range%)
    P_flat     = min(25, 5.0 x rows_inside_flatline_runs%)        (run = >= 6 identical consecutive values)
    P_spike    = min(20, 4.0 x max(0, spike_samples% - training_spike_samples%))
                 (Hampel test: |x - rolling median(24)| / max(local MAD, global residual MAD) >= 4; only the EXCESS over the
                  same sensor's 2011-2013 spike rate is penalised, because this process is inherently spiky)
    P_coupling = min(30, sum over drifted pairs of min(20, 10 + 40 x (|r_year - r_train| - 0.25)))
status: ok >= 80, watch >= 60, check < 60. A sensor with no valid readings scores 0.
"""
from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np
import pandas as pd

from app.schemas import MEASUREMENTS, MEASUREMENT_KEYS
from app.features.instruments.schemas import (
    DISCLAIMER,
    CouplingPair,
    ScorecardSummary,
    SensorHealth,
)

TRAIN_YEARS = (2011, 2012, 2013)
FLATLINE_MIN_RUN = 6
SPIKE_WINDOW = 24
SPIKE_Z = 4.0
COUPLING_DRIFT = 0.25
STATUS_OK = 80.0
STATUS_WATCH = 60.0

# (a, b, expected relationship). Sign/strength only describes what is physically expected.
COUPLING_PAIRS: list[tuple[str, str, str]] = [
    ("CDP", "TEY", "strong positive"),
    ("CDP", "TIT", "strong positive"),
    ("AFDP", "TEY", "weak positive"),
    ("TIT", "TAT", "positive"),
    ("GTEP", "TEY", "strong positive"),
    ("AT", "TEY", "negative"),
]

CAPS = {"missing": 30.0, "ood": 25.0, "flatline": 25.0, "spikes": 20.0, "coupling": 30.0}

METHOD_NOTES = [
    DISCLAIMER,
    "Computed deterministically from the real UCI Gas Turbine rows of the selected year/window; no model or LLM is involved in the scores.",
    "Missing = NaN readings. Out-of-range = readings outside the training-years (2011-2013) min/max: model.feature_ranges_train for AT, AP, AH, AFDP, GTEP, TIT, TAT, CDP; "
    "min/max over the 2011-2013 rows for TEY, CO, NOX.",
    f"Flatline = a run of >= {FLATLINE_MIN_RUN} consecutive identical readings (hourly aggregates, so >= {FLATLINE_MIN_RUN} hours). Spike = Hampel test, robust MAD z >= {SPIKE_Z:g} of the residual against a centred rolling median of {SPIKE_WINDOW} samples (scale = local MAD, floored at the global residual MAD); "
    "adjacent flagged samples count as one spike event. This process is inherently spiky, so the score penalises only the spike-sample rate in EXCESS of the same sensor's 2011-2013 rate (reported as spike_baseline_pct).",
    f"Coupling check: Pearson r in the selected window vs r over 2011-2013 for physically coupled pairs ({', '.join(f'{a}~{b}' for a, b, _ in COUPLING_PAIRS)}); "
    f"'coupling drift' when |r_window - r_train| >= {COUPLING_DRIFT}. A drifting pair implicates both sensors (or a genuine process/operating-mode change), so it is a prompt to cross-check, not a verdict.",
    "Score = 100 - P_missing - P_ood - P_flat - P_spike - P_coupling, clamped to 0-100. P_missing = min(30, 6 x missing%); P_ood = min(25, 2.5 x OOD%); P_flat = min(25, 5 x flatline-row%); "
    "P_spike = min(20, 4 x max(0, spike-sample% - training spike-sample%)); P_coupling = min(30, sum per drifted pair of min(20, 10 + 40 x (|dr| - 0.25))). Status: ok >= 80, watch >= 60, check < 60.",
    "Rows are ordered hourly aggregates with no row-level timestamps; windows are sample indices within a source year. No verified fault labels exist, so scores cannot be validated against known sensor faults.",
    "This tool is read-only decision support: it never writes to any control system and recommends no control actions.",
]

_CHECKS = {
    "missing": "check the data-acquisition/historian path and the transmitter's signal quality flags for the gaps",
    "ood": "verify calibration records and the transmitter range/scaling configuration against the training-period envelope",
    "flatline": "inspect for a frozen or held signal (transmitter/IO card/historian compression) and compare with a redundant sensor if one exists",
    "spikes": "inspect impulse/sensing lines and wiring for noise or intermittent connections, and compare with a redundant or neighbouring sensor",
    "coupling": "compare against the coupled sensor(s) and the process operating mode before suspecting either instrument",
}
_SENSOR_HINT = {
    "AFDP": "air-filter dP: inspect impulse lines and the differential transmitter zero",
    "AT": "ambient temperature: compare with a second ambient probe or site weather record",
    "AP": "ambient pressure: compare with a barometric reference",
    "AH": "ambient humidity: verify the sensor's calibration date (humidity elements drift)",
    "GTEP": "exhaust pressure: inspect impulse lines for blockage or condensate",
    "CDP": "compressor discharge pressure (unit under validation): verify the unit/scaling in the calibration record",
    "TIT": "turbine inlet temperature: compare against TAT and any redundant thermocouple channels",
    "TAT": "turbine after temperature: compare against redundant thermocouples and TIT",
    "TEY": "energy yield is a derived/metered quantity: verify the metering/calculation chain and its calibration records",
    "CO": "emission analyser: verify the latest span/zero check and sample-line condition",
    "NOX": "emission analyser: verify the latest span/zero check and sample-line condition",
}


def _num(x: Any) -> float | None:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def flatline_runs(values: np.ndarray, min_run: int = FLATLINE_MIN_RUN) -> tuple[int, int]:
    """(number of runs, rows inside runs) of >= min_run identical consecutive non-NaN values."""
    runs = rows = 0
    n = len(values)
    i = 0
    while i < n:
        if np.isnan(values[i]):
            i += 1
            continue
        j = i + 1
        while j < n and values[j] == values[i]:
            j += 1
        if j - i >= min_run:
            runs += 1
            rows += j - i
        i = j
    return runs, rows


def spike_flags(series: pd.Series, window: int = SPIKE_WINDOW, z_thresh: float = SPIKE_Z) -> np.ndarray:
    """Hampel-style test: |x - centred rolling median| / robust scale >= z_thresh.

    Robust scale = 1.4826 x MAD of the residual, taken locally (rolling ``window``) but never smaller than the
    global residual MAD (so quiet steady-state stretches do not turn tiny noise into spikes).
    """
    s = pd.Series(np.asarray(series, dtype=float))
    med = s.rolling(window, center=True, min_periods=max(3, window // 4)).median()
    resid = s - med
    ok = resid.dropna()
    if len(ok) < 3:
        return np.zeros(len(s), dtype=bool)
    g_center = float(np.median(ok))
    g_mad = float(np.median(np.abs(ok - g_center))) * 1.4826
    if g_mad <= 0.0:
        g_mad = float(np.std(ok, ddof=1))
    if g_mad <= 0.0:
        return np.zeros(len(s), dtype=bool)
    local = np.abs(resid - g_center).rolling(window, center=True, min_periods=max(3, window // 4)).median() * 1.4826
    scale = np.maximum(local.to_numpy(dtype=float), g_mad)
    z = (resid.to_numpy(dtype=float) - g_center) / scale
    return np.abs(np.nan_to_num(z, nan=0.0)) >= z_thresh


def _events(flags: np.ndarray) -> int:
    if flags.size == 0:
        return 0
    padded = np.concatenate([[False], flags, [False]])
    return int(np.sum(padded[1:] & ~padded[:-1]))


def pearson(a: pd.Series, b: pd.Series) -> float | None:
    x = np.asarray(a, dtype=float)
    y = np.asarray(b, dtype=float)
    m = ~(np.isnan(x) | np.isnan(y))
    x, y = x[m], y[m]
    if x.size < 3 or np.std(x) == 0.0 or np.std(y) == 0.0:
        return None
    return _num(np.corrcoef(x, y)[0, 1])


def coupling_checks(window: pd.DataFrame, train: pd.DataFrame | None) -> list[CouplingPair]:
    out: list[CouplingPair] = []
    for a, b, expected in COUPLING_PAIRS:
        r_year = pearson(window[a], window[b]) if a in window and b in window else None
        r_train = pearson(train[a], train[b]) if train is not None and len(train) and a in train and b in train else None
        delta = (r_year - r_train) if (r_year is not None and r_train is not None) else None
        out.append(
            CouplingPair(
                pair=f"{a}~{b}", a=a, b=b, expected=expected,
                r_year=None if r_year is None else round(r_year, 4),
                r_train=None if r_train is None else round(r_train, 4),
                delta=None if delta is None else round(delta, 4),
                drift=bool(delta is not None and abs(delta) >= COUPLING_DRIFT),
            )
        )
    return out


def training_ranges(train: pd.DataFrame | None, model_ranges: dict[str, Iterable[float]] | None) -> dict[str, tuple[float, float, str]]:
    """key -> (lo, hi, source). Model ranges for features, training-years min/max otherwise."""
    out: dict[str, tuple[float, float, str]] = {}
    for key in MEASUREMENT_KEYS:
        if model_ranges and key in model_ranges:
            lo, hi = list(model_ranges[key])[:2]
            out[key] = (float(lo), float(hi), "model.feature_ranges_train")
        elif train is not None and key in train and train[key].notna().any():
            out[key] = (float(train[key].min()), float(train[key].max()), "training_years_min_max")
    return out


def _penalties(n: int, missing: int, ood: int, flat_rows: int, spike_points: int, drift_pairs: list[CouplingPair], train_spike_pct: float = 0.0) -> dict[str, float]:
    pct = lambda c: 100.0 * c / n if n else 0.0  # noqa: E731
    coupling = sum(min(20.0, 10.0 + 40.0 * (abs(p.delta or 0.0) - COUPLING_DRIFT)) for p in drift_pairs)
    raw = {
        "missing": 6.0 * pct(missing),
        "ood": 2.5 * pct(ood),
        "flatline": 5.0 * pct(flat_rows),
        "spikes": 4.0 * max(0.0, pct(spike_points) - train_spike_pct),
        "coupling": coupling,
    }
    return {k: round(min(CAPS[k], v), 2) for k, v in raw.items()}


def _status(score: float) -> str:
    return "ok" if score >= STATUS_OK else "watch" if score >= STATUS_WATCH else "check"


def _what_to_check(key: str, status: str, n_valid: int, m: dict[str, Any]) -> str:
    if n_valid == 0:
        return f"No valid {key} readings in this window: verify the signal path and calibration records before using it."
    reasons = []
    if m["missing"]:
        reasons.append("missing")
    if m["ood"]:
        reasons.append("ood")
    if m["flat_rows"]:
        reasons.append("flatline")
    if m["spikes"]:
        reasons.append("spikes")
    if m["drift"]:
        reasons.append("coupling")
    hint = _SENSOR_HINT.get(key, "")
    if status == "ok" and not reasons:
        return f"No screening flags. Routine only: confirm the latest calibration record is in date ({hint})." if hint else "No screening flags. Routine only: confirm the latest calibration record is in date."
    if status == "ok":
        reasons = reasons[:2]
    acts = "; ".join(_CHECKS[r] for r in reasons)
    lead = {"ok": "Minor flags", "watch": "Cross-check before relying on it", "check": "Verify before relying on it"}[status]
    drift_txt = f" Drifting pairs: {', '.join(m['drift'])}." if m["drift"] else ""
    return f"{lead}: {acts}.{drift_txt} Read-only checks only; {hint}." if hint else f"{lead}: {acts}.{drift_txt} Read-only checks only."


def compute_sensor_health(
    window: pd.DataFrame,
    train: pd.DataFrame | None,
    model_ranges: dict[str, Iterable[float]] | None = None,
) -> list[SensorHealth]:
    ranges = training_ranges(train, model_ranges)
    pairs = coupling_checks(window, train)
    n = len(window)
    sensors: list[SensorHealth] = []
    for key in MEASUREMENT_KEYS:
        info = MEASUREMENTS[key]
        vals = window[key].to_numpy(dtype=float) if key in window else np.full(n, np.nan)
        valid = ~np.isnan(vals)
        n_valid = int(valid.sum())
        missing = n - n_valid
        rng = ranges.get(key)
        ood = int(np.sum(valid & ((vals < rng[0]) | (vals > rng[1])))) if rng else 0
        f_runs, f_rows = flatline_runs(vals)
        flags = spike_flags(pd.Series(vals))
        spike_pts = int(flags.sum())
        spike_ev = _events(flags)
        my_pairs = [p for p in pairs if key in (p.a, p.b)]
        drift = [p for p in my_pairs if p.drift]
        train_spike_pct = 0.0
        if train is not None and len(train) and key in train:
            tf = spike_flags(train[key])
            train_spike_pct = round(100.0 * float(tf.mean()), 2)
        pen = _penalties(n, missing, ood, f_rows, spike_pts, drift, train_spike_pct)
        score = 0.0 if n_valid == 0 else max(0.0, min(100.0, 100.0 - sum(pen.values())))
        score = round(score, 1)
        status = _status(score)
        computation = (
            f"100 - missing {pen['missing']} - ood {pen['ood']} - flatline {pen['flatline']} - spikes {pen['spikes']} - coupling {pen['coupling']} = {score} "
            f"(n={n}; missing={missing}, ood={ood}, flatline_rows={f_rows}, spike_samples={spike_pts} vs training rate {train_spike_pct}%, drifted_pairs={len(drift)}; caps 30/25/25/20/30)"
            if n_valid
            else "No valid readings in the window: score forced to 0."
        )
        m = {"missing": missing, "ood": ood, "flat_rows": f_rows, "spikes": spike_ev, "drift": [p.pair for p in drift]}
        sensors.append(
            SensorHealth(
                key=key, name=info["name"], unit=info["unit"], rows=n, missing=missing, out_of_range=ood,
                range_source=rng[2] if rng else "unavailable",
                range_lo=rng[0] if rng else None, range_hi=rng[1] if rng else None,
                flatline_runs=f_runs, flatline_rows=f_rows, spikes=spike_ev, spike_points=spike_pts, spike_baseline_pct=train_spike_pct,
                coupling=my_pairs, coupling_drift_pairs=[p.pair for p in drift],
                penalties=pen, score=score, status=status, computation=computation,  # type: ignore[arg-type]
                what_to_check=_what_to_check(key, status, n_valid, m),
            )
        )
    return sensors


def build_summary(sensors: list[SensorHealth], label: str = "this window") -> ScorecardSummary:
    ok = [s.key for s in sensors if s.status == "ok"]
    watch = [s.key for s in sensors if s.status == "watch"]
    check = [s.key for s in sensors if s.status == "check"]
    drift = sorted({p for s in sensors for p in s.coupling_drift_pairs})
    mean = round(float(np.mean([s.score for s in sensors])), 1) if sensors else 0.0
    parts = [f"Screening of {label}: {len(ok)} sensor(s) look consistent ({', '.join(ok) or 'none'})"]
    if watch:
        parts.append(f"{len(watch)} to use with a cross-check ({', '.join(watch)})")
    if check:
        parts.append(f"{len(check)} to verify before relying on them ({', '.join(check)})")
    headline = "; ".join(parts) + ". " + DISCLAIMER
    return ScorecardSummary(
        headline=headline, trust=ok, use_with_cross_check=watch, verify_first=check,
        mean_score=mean, coupling_drift_pairs=drift,
    )


def compute_scorecard(
    window: pd.DataFrame,
    train: pd.DataFrame | None,
    model_ranges: dict[str, Iterable[float]] | None = None,
    label: str = "this window",
) -> tuple[list[SensorHealth], ScorecardSummary]:
    sensors = compute_sensor_health(window, train, model_ranges)
    return sensors, build_summary(sensors, label)
