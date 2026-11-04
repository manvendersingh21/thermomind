"""Baseline TEY model training (``train_baseline``).

The model learns the *contemporaneous* relation between operating/ambient
sensor readings and turbine energy yield (TEY). It is a statistical
"expected TEY given the other readings" reference, not a physics model and not
a fault detector. See ``_NOTES`` for the caveats that travel with every
``ModelEvaluation``.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from app.schemas import FEATURE_KEYS, TARGET_KEY, MetricSet, ModelEvaluation, SplitInfo

MODEL_ID = "baseline_tey_hgbr"
MODEL_VERSION = "baseline_v1"
ALGORITHM = "sklearn.ensemble.HistGradientBoostingRegressor"
JOBLIB_NAME = f"{MODEL_VERSION}.joblib"
JSON_NAME = f"{MODEL_VERSION}.json"

HGBR_PARAMS = dict(
    max_iter=300,
    learning_rate=0.05,
    max_leaf_nodes=31,
    min_samples_leaf=40,
    l2_regularization=1.0,
    early_stopping=False,
)

_NOTES = [
    "Model learns the contemporaneous statistical relation between operating/ambient sensor readings "
    "and TEY in the UCI 551 data set; it is NOT a physics or thermodynamic model of the turbine.",
    "Features are hourly aggregates recorded at the same time as the target; the model cannot forecast and "
    "its residuals are confounded by dispatch/load changes that are not observed as a separate signal.",
    "The data set contains no verified fault labels; residuals indicate deviation from the learned relation, "
    "not a diagnosed fault. Any fault interpretation requires engineer review.",
    "CDP unit is 'mbar' as published by UCI and is under validation (values ~10-15 look like bar); the model "
    "uses it as an unscaled numeric feature so the unit question does not affect predictions.",
    "Leakage review: TEY (target) is excluded from the features. CO and NOX are excluded because they are "
    "emission outputs of the combustion process, not operating inputs, and would leak target-correlated "
    "information. Remaining features: " + ", ".join(FEATURE_KEYS) + ".",
    "Split is chronological by source_year (train 2011-2013, validation 2014, holdout 2015); the holdout year "
    "is never used for fitting or threshold selection. Rows have no timestamps; order within a year is file order.",
    "Naive baselines: 'train_mean' predicts the training-set mean TEY; 'previous_observation' predicts each "
    "row's TEY from the previous row of the same year (first row of each year dropped). Both are evaluated on the holdout.",
    "TEY is in MWh as published (hourly aggregate); it is not converted to MW.",
]


def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> MetricSet:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    return MetricSet(
        mae=float(mean_absolute_error(y_true, y_pred)),
        rmse=float(np.sqrt(mean_squared_error(y_true, y_pred))),
        r2=float(r2_score(y_true, y_pred)),
        n=int(len(y_true)),
    )


def chronological_split(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, SplitInfo, list[str]]:
    """Split by source_year (train = all but the last two years, validation = second last, holdout = last).

    With the UCI data this gives 2011-2013 / 2014 / 2015. If fewer than three distinct years exist the
    frame is split 70/15/15 in order (a note is returned)."""
    notes: list[str] = []
    years = sorted(int(y) for y in frame["source_year"].dropna().unique())
    if len(years) >= 3:
        val_year, test_year = years[-2], years[-1]
        train_years = years[:-2]
        train = frame[frame["source_year"].isin(train_years)]
        val = frame[frame["source_year"] == val_year]
        test = frame[frame["source_year"] == test_year]
        split = SplitInfo(
            train_years=train_years, validation_years=[val_year], test_years=[test_year],
            train_rows=int(len(train)), validation_rows=int(len(val)), test_rows=int(len(test)),
            method="chronological_by_source_year",
        )
    else:
        ordered = frame.sort_values(["source_year", "row_index"], kind="stable")
        n = len(ordered)
        n_train = int(n * 0.70)
        n_val = int(n * 0.15)
        train = ordered.iloc[:n_train]
        val = ordered.iloc[n_train:n_train + n_val]
        test = ordered.iloc[n_train + n_val:]
        split = SplitInfo(
            train_years=years, validation_years=years, test_years=years,
            train_rows=int(len(train)), validation_rows=int(len(val)), test_rows=int(len(test)),
            method="ordered_70_15_15_fallback",
        )
        notes.append(
            f"Only {len(years)} distinct source_year value(s) present; fell back to an ordered 70/15/15 split "
            "(train/validation/holdout share years, so holdout is not an untouched year)."
        )
    return train, val, test, split, notes


def _previous_observation_metrics(test: pd.DataFrame) -> MetricSet:
    """Predict TEY[i] = TEY[i-1] within each year; the first row of each year is dropped."""
    ordered = test.sort_values(["source_year", "row_index"], kind="stable")
    y_true, y_pred = [], []
    for _, grp in ordered.groupby("source_year", sort=True):
        vals = grp[TARGET_KEY].to_numpy(dtype=float)
        if len(vals) < 2:
            continue
        y_true.append(vals[1:])
        y_pred.append(vals[:-1])
    yt = np.concatenate(y_true) if y_true else np.array([])
    yp = np.concatenate(y_pred) if y_pred else np.array([])
    mask = ~(np.isnan(yt) | np.isnan(yp))
    return _metrics(yt[mask], yp[mask])


def train_baseline(frame: pd.DataFrame, model_dir: Path, seed: int = 42) -> ModelEvaluation:
    """Train the baseline TEY model and write ``baseline_v1.joblib`` + ``baseline_v1.json`` to ``model_dir``."""
    model_dir = Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)

    required = ["source_year", "row_index", *FEATURE_KEYS, TARGET_KEY]
    missing = [c for c in required if c not in frame.columns]
    if missing:
        raise ValueError(f"frame is missing required columns: {missing}")

    usable = frame.dropna(subset=[*FEATURE_KEYS, TARGET_KEY])
    dropped = len(frame) - len(usable)
    train, val, test, split, notes = chronological_split(usable)
    if dropped:
        notes.append(f"Dropped {dropped} row(s) with missing feature/target values before training.")
    if len(train) == 0 or len(val) == 0 or len(test) == 0:
        raise ValueError("train/validation/holdout split produced an empty partition")

    X_tr, y_tr = train[FEATURE_KEYS].to_numpy(dtype=float), train[TARGET_KEY].to_numpy(dtype=float)
    X_va, y_va = val[FEATURE_KEYS].to_numpy(dtype=float), val[TARGET_KEY].to_numpy(dtype=float)
    X_te, y_te = test[FEATURE_KEYS].to_numpy(dtype=float), test[TARGET_KEY].to_numpy(dtype=float)

    model = HistGradientBoostingRegressor(random_state=seed, **HGBR_PARAMS)
    model.fit(X_tr, y_tr)

    pred_va = model.predict(X_va)
    pred_te = model.predict(X_te)
    validation = _metrics(y_va, pred_va)
    holdout = _metrics(y_te, pred_te)

    train_mean = float(np.mean(y_tr))
    naive = {
        "train_mean": _metrics(y_te, np.full_like(y_te, train_mean)),
        "previous_observation": _previous_observation_metrics(test),
    }

    resid_va = y_va - pred_va
    residual_std = float(np.std(resid_va, ddof=1)) if len(resid_va) > 1 else 0.0
    quantiles = {
        f"p{int(q * 100):02d}": float(np.quantile(resid_va, q)) for q in (0.01, 0.05, 0.50, 0.95, 0.99)
    }
    feature_ranges = {
        k: [float(train[k].min()), float(train[k].max())] for k in FEATURE_KEYS
    }

    evaluation = ModelEvaluation(
        model_id=MODEL_ID,
        model_version=MODEL_VERSION,
        algorithm=ALGORITHM,
        features=list(FEATURE_KEYS),
        target=TARGET_KEY,
        target_unit="MWh",
        seed=int(seed),
        split=split,
        validation=validation,
        holdout=holdout,
        naive_baselines=naive,
        residual_std_validation=residual_std,
        residual_quantiles_validation=quantiles,
        feature_ranges_train=feature_ranges,
        trained_at_utc=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        notes=[*_NOTES, f"HistGradientBoostingRegressor params: {HGBR_PARAMS}, random_state={seed}.", *notes],
    )

    # Atomic publish: write each file to a temp name and os.replace() it. The JSON goes first and the joblib
    # last, so a reader keyed on the joblib mtime never pairs a new model with a stale evaluation.
    json_tmp = model_dir / f".{JSON_NAME}.tmp"
    json_tmp.write_text(evaluation.model_dump_json(indent=2), encoding="utf-8")
    os.replace(json_tmp, model_dir / JSON_NAME)
    joblib_tmp = model_dir / f".{JOBLIB_NAME}.tmp"
    joblib.dump(
        {"model": model, "features": list(FEATURE_KEYS), "version": MODEL_VERSION, "model_id": MODEL_ID,
         "target": TARGET_KEY, "seed": int(seed)},
        joblib_tmp,
    )
    os.replace(joblib_tmp, model_dir / JOBLIB_NAME)
    return evaluation
