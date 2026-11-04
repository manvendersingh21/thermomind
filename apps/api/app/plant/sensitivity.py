"""Deterministic what-if sensitivity: ``simulate_change`` and ``train_range_check``.

* Model effect: apply ``delta`` to ONE measurement over the real rows of the base window (ceteris paribus),
  re-run the production BaselineModel and report Δ expected TEY (mean/min/max). Model-derived, not physics.
* Co-movement: Pearson r and least-squares slope of every other measurement vs the perturbed one over the
  training years (2011–2013) — statistical association in this plant's historical data, not causation.
"""
from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np
import pandas as pd

from app.plant.schemas import ASSOCIATION_LABEL
from app.schemas import FEATURE_KEYS, MEASUREMENT_KEYS, MEASUREMENTS, TARGET_KEY

DEFAULT_DATASET = "ds_uci_551"
DEFAULT_YEAR, DEFAULT_START, DEFAULT_END = 2014, 1200, 1320
TRAINING_YEARS = (2011, 2012, 2013)
MAX_DELTA_STD = 3.0  # |delta| <= 3 x training-years std of the measurement


@dataclass
class BaseWindow:
    dataset_id: str
    year: int
    start: int
    end: int
    case_id: Optional[str]
    basis: str

    def as_dict(self) -> dict[str, Any]:
        return {"dataset_id": self.dataset_id, "source_year": self.year, "start": self.start, "end": self.end,
                "case_id": self.case_id, "basis": self.basis}


def _r(x: Any, nd: int = 4) -> Optional[float]:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return round(f, nd) if math.isfinite(f) else None


def resolve_base(case_id: Optional[str]) -> BaseWindow:
    if case_id:
        from app import services

        inv = services.get_store().get(case_id)  # KeyError -> 404
        return BaseWindow(inv.request.dataset_id, inv.window.source_year, inv.window.start, inv.window.end, case_id,
                          "real observed rows of the case window (any synthetic overlay of the case is NOT applied)")
    return BaseWindow(DEFAULT_DATASET, DEFAULT_YEAR, DEFAULT_START, DEFAULT_END, None,
                      "real observed rows of the default demo window (2014, samples 1200–1319)")


def _bundle(dataset_id: str) -> Any:
    from app import services

    try:
        return services.get_repo().get(dataset_id)
    except KeyError:
        if dataset_id != DEFAULT_DATASET or not services.seed_uci_if_available():  # local files only
            raise
        return services.get_repo().get(dataset_id)


def _frame(dataset_id: str) -> pd.DataFrame:
    return _bundle(dataset_id).frame


def _window(base: BaseWindow) -> pd.DataFrame:
    return _bundle(base.dataset_id).window(base.year, base.start, base.end)


# ----------------------------------------------------------------------------- historical stats (cached)
_stats_lock = threading.Lock()
_stats_cache: dict[tuple[str, int], dict[str, Any]] = {}


def training_stats(dataset_id: str = DEFAULT_DATASET) -> dict[str, Any]:
    """Per-measurement std/min/max and the full correlation/slope tables over the training years."""
    frame = _frame(dataset_id)
    key = (dataset_id, len(frame))
    with _stats_lock:
        if key in _stats_cache:
            return _stats_cache[key]
    train = frame[frame["source_year"].isin(TRAINING_YEARS)]
    years = list(TRAINING_YEARS)
    if len(train) < 50:  # tiny/uploaded datasets: fall back to all rows, say so
        train, years = frame, sorted(int(y) for y in frame["source_year"].unique())
    cols = [m for m in MEASUREMENT_KEYS if m in train.columns]
    x = train[cols].astype(float)
    std = x.std(ddof=0)
    out = {
        "years": years, "n_rows": int(len(x)),
        "std": {m: float(std[m]) for m in cols},
        "mean": {m: float(x[m].mean()) for m in cols},
        "min": {m: float(x[m].min()) for m in cols},
        "max": {m: float(x[m].max()) for m in cols},
        "corr": x.corr(method="pearson").to_dict(),
        # slope of column B regressed on column A: cov(A,B)/var(A)
        "cov": x.cov(ddof=0).to_dict(),
    }
    with _stats_lock:
        _stats_cache[key] = out
    return out


def measurement_info(dataset_id: str = DEFAULT_DATASET) -> list[dict[str, Any]]:
    st = training_stats(dataset_id)
    out = []
    for m in MEASUREMENT_KEYS:
        if m not in st["std"]:
            continue
        sd = st["std"][m]
        max_abs = MAX_DELTA_STD * sd
        mag = 10 ** math.floor(math.log10(max_abs)) if max_abs > 0 else 1.0
        out.append({"key": m, "name": MEASUREMENTS[m]["name"], "unit": MEASUREMENTS[m]["unit"],
                    "train_std": _r(sd), "max_abs_delta": _r(math.ceil(max_abs / mag) * mag),
                    "step": _r(mag / 10), "is_model_feature": m in FEATURE_KEYS})
    return out


def validate_change(measurement: str, delta: Any, dataset_id: str = DEFAULT_DATASET) -> tuple[str, float]:
    if not isinstance(measurement, str) or measurement not in MEASUREMENT_KEYS:
        raise ValueError(f"measurement must be one of {MEASUREMENT_KEYS}")
    if isinstance(delta, bool):
        raise ValueError("delta must be a number")
    try:
        d = float(delta)
    except (TypeError, ValueError):
        raise ValueError("delta must be a number") from None
    if not math.isfinite(d):
        raise ValueError("delta must be finite")
    limit = next((i["max_abs_delta"] for i in measurement_info(dataset_id) if i["key"] == measurement), None)
    if limit is not None and abs(d) > limit:
        raise ValueError(f"|delta| for {measurement} must be <= {limit} {MEASUREMENTS[measurement]['unit']} "
                         f"(3 x training-years std); larger what-ifs are pure extrapolation")
    return measurement, d


def train_range_check(measurement: str, delta: float, window: pd.DataFrame, model: Any,
                      dataset_id: str = DEFAULT_DATASET) -> dict[str, Any]:
    vals = window[measurement].astype(float).to_numpy() + delta
    ranges = getattr(getattr(model, "evaluation", None), "feature_ranges_train", None) or {}
    if measurement in ranges:
        lo, hi = ranges[measurement]
        basis = "production model feature_ranges_train (training years)"
    else:
        st = training_stats(dataset_id)
        lo, hi = st["min"][measurement], st["max"][measurement]
        basis = f"historical min/max over {st['years']}"
    outside = int(np.sum((vals < lo) | (vals > hi)))
    return {"measurement": measurement, "train_min": _r(lo), "train_max": _r(hi),
            "perturbed_min": _r(np.nanmin(vals)), "perturbed_max": _r(np.nanmax(vals)),
            "rows_outside": outside, "rows": int(len(vals)), "within_training_range": outside == 0,
            "ood_flag": outside > 0, "basis": basis}


def co_movement(measurement: str, delta: float, dataset_id: str = DEFAULT_DATASET) -> dict[str, Any]:
    st = training_stats(dataset_id)
    var = st["cov"][measurement][measurement]
    items = []
    for m in st["std"]:
        if m == measurement:
            continue
        r = st["corr"][measurement][m]
        slope = st["cov"][measurement][m] / var if var > 0 else float("nan")
        items.append({"measurement": m, "unit": MEASUREMENTS[m]["unit"], "pearson_r": _r(r, 3),
                      "slope_per_unit": _r(slope), "implied_change_for_delta": _r(slope * delta)})
    items.sort(key=lambda i: -abs(i["pearson_r"] or 0))
    return {"label": ASSOCIATION_LABEL, "training_years": st["years"], "n_rows": st["n_rows"],
            "method": "Pearson r and least-squares slope (cov/var) of each measurement on the perturbed one",
            "items": items}


def simulate_change(measurement: str, delta: Any, base: Optional[BaseWindow] = None,
                    model: Any = None) -> dict[str, Any]:
    """Deterministic what-if. Raises ValueError for bad input."""
    from app import services

    base = base or resolve_base(None)
    measurement, delta = validate_change(measurement, delta, base.dataset_id)
    window = _window(base)
    model = model if model is not None else services.get_model()
    unit = MEASUREMENTS[measurement]["unit"]
    caveats = [
        "Ceteris paribus: only this one measurement is shifted; in the real plant coupled measurements would "
        "move together, so the model effect is a sensitivity of the statistical baseline, not a prediction.",
        "The production baseline is a gradient-boosted tree model: its response is piecewise constant and flat "
        "outside the training range (no extrapolation).",
        "Co-movement numbers are " + ASSOCIATION_LABEL + ".",
        "No timestamps exist; rows are hourly samples identified by source_year + row_index.",
    ]
    model_effect: dict[str, Any] = {"applicable": False, "target": TARGET_KEY, "unit": "MWh",
                                    "model_version": getattr(model, "version", None)}
    if model is None:
        model_effect["note"] = "baseline model not loaded; no model effect computed"
    elif measurement not in getattr(model, "features", FEATURE_KEYS):
        model_effect["note"] = (f"{measurement} is not an input of the baseline model "
                                f"(inputs: {', '.join(getattr(model, 'features', FEATURE_KEYS))}); "
                                "only historical co-movement is available")
    else:
        pert = window.copy()  # never mutate repository rows
        pert[measurement] = pert[measurement].astype(float) + delta
        base_pred = model.predict(window)
        new_pred = model.predict(pert)
        d = new_pred - base_pred
        model_effect.update({
            "applicable": True,
            "expected_tey_base_mean": _r(np.nanmean(base_pred)),
            "expected_tey_perturbed_mean": _r(np.nanmean(new_pred)),
            "delta_tey_mean": _r(np.nanmean(d)), "delta_tey_min": _r(np.nanmin(d)),
            "delta_tey_max": _r(np.nanmax(d)),
            "delta_tey_pct_of_base": _r(100 * np.nanmean(d) / np.nanmean(base_pred), 3),
            "note": "MODEL-DERIVED: expected TEY(perturbed rows) - expected TEY(real rows), per row",
        })
    return {
        "tool": "simulate_change", "measurement": measurement, "delta": delta, "unit": unit,
        "base": {**base.as_dict(), "rows": int(len(window)),
                 "observed_mean": _r(window[measurement].astype(float).mean())},
        "model_effect": model_effect,
        "train_range_check": train_range_check(measurement, delta, window, model, base.dataset_id),
        "co_movement": co_movement(measurement, delta, base.dataset_id),
        "caveats": caveats,
    }
