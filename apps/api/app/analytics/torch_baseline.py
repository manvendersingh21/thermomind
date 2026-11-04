"""GPU-trained challenger model for expected TEY (``train_torch_baseline`` / ``TorchBaselineModel``).

This is a *benchmark challenger* to the production HistGradientBoostingRegressor in
``app.analytics.train``. It is evaluated on exactly the same chronological split
(train 2011-2013, validation 2014, holdout 2015), the same ``FEATURE_KEYS`` and the
same ``MetricSet`` definitions so the two can be compared honestly. It does not
replace the production model: ``role == "challenger"``.

``torch`` is imported lazily inside the functions that need it, so importing this
module (and the API) works without torch installed; ``apps/api/requirements-gpu.txt``
lists the optional dependency.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.schemas import FEATURE_KEYS, TARGET_KEY, MetricSet, ModelEvaluation, SplitInfo

MODEL_ID = "challenger_tey_mlp"
MODEL_VERSION = "mlp_v1"
HIDDEN = (256, 256, 128)
DROPOUT = 0.05
ALGORITHM = f"torch.nn MLP ({len(FEATURE_KEYS)}-{'-'.join(str(h) for h in HIDDEN)}-1)"
WEIGHTS_NAME = f"{MODEL_VERSION}.pt"
JSON_NAME = f"{MODEL_VERSION}.json"

DEFAULT_EPOCHS = 300
DEFAULT_PATIENCE = 40
DEFAULT_BATCH_SIZE = 512
DEFAULT_LR = 2e-3
DEFAULT_WEIGHT_DECAY = 1e-4

_CHALLENGER_NOTES = [
    "CHALLENGER model: reported for benchmarking only on the identical chronological split as the production "
    "HistGradientBoostingRegressor; it is not used for investigations or thresholds unless explicitly swapped in.",
    "Training is non-convex (mini-batch AdamW on an MLP); results depend on initialisation and data order. "
    "Seeds and deterministic cuDNN are fixed, but small differences between models are not meaningful.",
    "Early stopping monitors 2014 validation MAE (the holdout year 2015 is never used for fitting or stopping).",
    "Features are standardised with training-set mean/std only; the target is standardised with training-set "
    "statistics for optimisation and predictions are mapped back to MWh.",
]

# ---------------------------------------------------------------------------------------------------------------------
# Shared pieces: reuse the ML agent's split/notes when importable, otherwise fall back to equivalent local copies so
# this module is never blocked on train.py being refactored.
# ---------------------------------------------------------------------------------------------------------------------
try:  # pragma: no cover - exercised implicitly
    from app.analytics.train import _NOTES as _HGBR_NOTES
    from app.analytics.train import chronological_split
except Exception:  # noqa: BLE001  pragma: no cover
    _HGBR_NOTES = [
        "Model learns the contemporaneous statistical relation between operating/ambient sensor readings and TEY; "
        "it is NOT a physics model, cannot forecast, and the data set contains no verified fault labels.",
        "CDP unit is 'mbar' as published by UCI and is under validation.",
        "Leakage review: TEY (target), CO and NOX are excluded from the features.",
        "Split is chronological by source_year (train 2011-2013, validation 2014, holdout 2015).",
        "TEY is in MWh as published (hourly aggregate); it is not converted to MW.",
    ]

    def chronological_split(frame: pd.DataFrame):  # type: ignore[no-redef]
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
            n_train, n_val = int(n * 0.70), int(n * 0.15)
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


def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> MetricSet:
    """MAE / RMSE / R² exactly as sklearn defines them (same values as ``train._metrics``)."""
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    err = y_true - y_pred
    mae = float(np.mean(np.abs(err)))
    rmse = float(np.sqrt(np.mean(err ** 2)))
    ss_res = float(np.sum(err ** 2))
    ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return MetricSet(mae=mae, rmse=rmse, r2=float(r2), n=int(len(y_true)))


def _previous_observation_metrics(test: pd.DataFrame) -> MetricSet:
    """Predict TEY[i] = TEY[i-1] within each year; the first row of each year is dropped (same as train.py)."""
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


# ---------------------------------------------------------------------------------------------------------------------
# torch helpers (lazy import)
# ---------------------------------------------------------------------------------------------------------------------


def _torch():
    try:
        import torch  # noqa: WPS433
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "torch is required for the challenger model; install apps/api/requirements-gpu.txt"
        ) from exc
    return torch


def resolve_device(device: str | None = None):
    """Return a ``torch.device`` (explicit, else cuda:0 if available, else cpu)."""
    torch = _torch()
    if device is not None:
        return torch.device(device)
    return torch.device("cuda:0" if torch.cuda.is_available() else "cpu")


def device_label(dev) -> str:
    """Human-readable device string, e.g. ``"cuda:0 Tesla V100-PCIE-32GB"`` or ``"cpu"``."""
    torch = _torch()
    if dev.type == "cuda":
        idx = dev.index if dev.index is not None else torch.cuda.current_device()
        try:
            return f"cuda:{idx} {torch.cuda.get_device_name(idx)}"
        except Exception:  # noqa: BLE001  pragma: no cover
            return f"cuda:{idx}"
    return str(dev)


def seed_everything(seed: int) -> None:
    """Best-effort full determinism: python/numpy/torch seeds + deterministic cuDNN/cuBLAS."""
    import random

    torch = _torch()
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    try:
        torch.use_deterministic_algorithms(True, warn_only=True)
    except Exception:  # noqa: BLE001  pragma: no cover
        pass


def build_mlp(n_in: int, hidden: tuple[int, ...] = HIDDEN, dropout: float = DROPOUT):
    """``n_in -> hidden... -> 1`` MLP with SiLU activations and dropout after each hidden layer."""
    torch = _torch()
    nn = torch.nn
    layers: list[Any] = []
    prev = n_in
    for h in hidden:
        layers += [nn.Linear(prev, h), nn.SiLU(), nn.Dropout(dropout)]
        prev = h
    layers.append(nn.Linear(prev, 1))
    return nn.Sequential(*layers)


def _predict_array(net, X_std: np.ndarray, dev, y_mean: float, y_std: float, batch: int = 8192) -> np.ndarray:
    """Run the network on already-standardised features and return predictions in MWh."""
    torch = _torch()
    net.eval()
    out = np.empty(len(X_std), dtype=float)
    with torch.no_grad():
        for i in range(0, len(X_std), batch):
            xb = torch.as_tensor(X_std[i:i + batch], dtype=torch.float32, device=dev)
            out[i:i + batch] = net(xb).squeeze(-1).to("cpu").double().numpy() * y_std + y_mean
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------------------------------------------------


def train_torch_baseline(
    frame: pd.DataFrame,
    model_dir: Path,
    seed: int = 42,
    epochs: int = DEFAULT_EPOCHS,
    device: str | None = None,
    *,
    patience: int = DEFAULT_PATIENCE,
    batch_size: int = DEFAULT_BATCH_SIZE,
    lr: float = DEFAULT_LR,
    weight_decay: float = DEFAULT_WEIGHT_DECAY,
    hidden: tuple[int, ...] = HIDDEN,
    dropout: float = DROPOUT,
    verbose: bool = False,
) -> ModelEvaluation:
    """Train the MLP challenger and write ``mlp_v1.pt`` + ``mlp_v1.json`` into ``model_dir``.

    Same split, features, target, metrics, naive baselines and residual statistics as ``train_baseline``;
    the returned ``ModelEvaluation`` has ``role="challenger"``, the device used and the measured training seconds.
    """
    torch = _torch()
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

    # Train-only standardisation statistics (never computed on validation/holdout).
    x_mean = X_tr.mean(axis=0)
    x_std = X_tr.std(axis=0)
    x_std[x_std == 0] = 1.0
    y_mean = float(y_tr.mean())
    y_std = float(y_tr.std()) or 1.0

    seed_everything(seed)
    dev = resolve_device(device)
    dev_label = device_label(dev)
    net = build_mlp(len(FEATURE_KEYS), hidden, dropout).to(dev)

    Xtr_t = torch.as_tensor((X_tr - x_mean) / x_std, dtype=torch.float32, device=dev)
    ytr_t = torch.as_tensor((y_tr - y_mean) / y_std, dtype=torch.float32, device=dev)
    Xva_std = (X_va - x_mean) / x_std
    Xte_std = (X_te - x_mean) / x_std

    opt = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=weight_decay)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=max(1, epochs), eta_min=lr * 0.01)
    loss_fn = torch.nn.MSELoss()
    gen = torch.Generator(device="cpu").manual_seed(seed)

    best_mae = float("inf")
    best_state = {k: v.detach().clone() for k, v in net.state_dict().items()}
    best_epoch = 0
    epochs_run = 0
    n = len(Xtr_t)
    t0 = time.perf_counter()
    for epoch in range(1, epochs + 1):
        net.train()
        perm = torch.randperm(n, generator=gen).to(dev)
        for i in range(0, n, batch_size):
            idx = perm[i:i + batch_size]
            opt.zero_grad(set_to_none=True)
            loss = loss_fn(net(Xtr_t[idx]).squeeze(-1), ytr_t[idx])
            loss.backward()
            opt.step()
        sched.step()
        epochs_run = epoch
        val_mae = float(np.mean(np.abs(y_va - _predict_array(net, Xva_std, dev, y_mean, y_std))))
        if verbose:
            print(f"[torch] epoch {epoch:4d} train_loss={loss.item():.5f} val_mae={val_mae:.4f} "
                  f"lr={sched.get_last_lr()[0]:.2e}", flush=True)
        if val_mae < best_mae - 1e-6:
            best_mae = val_mae
            best_epoch = epoch
            best_state = {k: v.detach().clone() for k, v in net.state_dict().items()}
        elif epoch - best_epoch >= patience:
            if verbose:
                print(f"[torch] early stop at epoch {epoch} (best epoch {best_epoch}, val_mae={best_mae:.4f})")
            break
    if dev.type == "cuda":
        torch.cuda.synchronize(dev)
    training_seconds = float(time.perf_counter() - t0)
    net.load_state_dict(best_state)

    pred_va = _predict_array(net, Xva_std, dev, y_mean, y_std)
    pred_te = _predict_array(net, Xte_std, dev, y_mean, y_std)
    validation = _metrics(y_va, pred_va)
    holdout = _metrics(y_te, pred_te)

    naive = {
        "train_mean": _metrics(y_te, np.full_like(y_te, y_mean)),
        "previous_observation": _previous_observation_metrics(test),
    }
    resid_va = y_va - pred_va
    residual_std = float(np.std(resid_va, ddof=1)) if len(resid_va) > 1 else 0.0
    quantiles = {f"p{int(q * 100):02d}": float(np.quantile(resid_va, q)) for q in (0.01, 0.05, 0.50, 0.95, 0.99)}
    feature_ranges = {k: [float(train[k].min()), float(train[k].max())] for k in FEATURE_KEYS}

    hparams = dict(hidden=list(hidden), dropout=dropout, epochs_max=epochs, epochs_run=epochs_run,
                   best_epoch=best_epoch, patience=patience, batch_size=batch_size, lr=lr,
                   weight_decay=weight_decay, optimizer="AdamW", schedule="CosineAnnealingLR", loss="MSE")
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
        notes=[*_HGBR_NOTES, *_CHALLENGER_NOTES, f"MLP hyper-parameters: {hparams}, seed={seed}, device={dev_label}.",
               *notes],
        device=dev_label,
        training_seconds=training_seconds,
        role="challenger",
    )

    torch.save(
        {
            "state_dict": {k: v.detach().to("cpu") for k, v in net.state_dict().items()},
            "features": list(FEATURE_KEYS),
            "x_mean": torch.as_tensor(x_mean, dtype=torch.float64),
            "x_std": torch.as_tensor(x_std, dtype=torch.float64),
            "y_mean": y_mean,
            "y_std": y_std,
            "hidden": list(hidden),
            "dropout": float(dropout),
            "version": MODEL_VERSION,
            "model_id": MODEL_ID,
            "target": TARGET_KEY,
            "seed": int(seed),
        },
        model_dir / WEIGHTS_NAME,
    )
    (model_dir / JSON_NAME).write_text(evaluation.model_dump_json(indent=2), encoding="utf-8")
    return evaluation


# ---------------------------------------------------------------------------------------------------------------------
# Inference wrapper with the same interface as ``BaselineModel``
# ---------------------------------------------------------------------------------------------------------------------


class TorchBaselineModel:
    """Drop-in equivalent of ``BaselineModel`` backed by the MLP challenger (inference on CPU by default)."""

    def __init__(self, net, features: list[str], evaluation: ModelEvaluation,
                 x_mean: np.ndarray, x_std: np.ndarray, y_mean: float, y_std: float, device=None):
        self._net = net
        self._device = device
        self.features = list(features)
        self.evaluation = evaluation
        self.version: str = evaluation.model_version
        self._x_mean = np.asarray(x_mean, dtype=float)
        self._x_std = np.asarray(x_std, dtype=float)
        self._y_mean = float(y_mean)
        self._y_std = float(y_std)

    @classmethod
    def load(cls, model_dir: Path, device: str | None = "cpu") -> "TorchBaselineModel":
        torch = _torch()
        model_dir = Path(model_dir)
        weights_path = model_dir / WEIGHTS_NAME
        json_path = model_dir / JSON_NAME
        if not weights_path.exists() or not json_path.exists():
            raise FileNotFoundError(
                f"challenger model not found in {model_dir} (expected {WEIGHTS_NAME} and {JSON_NAME})"
            )
        bundle = torch.load(weights_path, map_location="cpu", weights_only=True)
        evaluation = ModelEvaluation.model_validate_json(json_path.read_text(encoding="utf-8"))
        features = list(bundle.get("features", FEATURE_KEYS))
        dev = resolve_device(device)
        net = build_mlp(len(features), tuple(bundle["hidden"]), float(bundle["dropout"]))
        net.load_state_dict(bundle["state_dict"])
        net.to(dev).eval()
        return cls(net, features, evaluation, bundle["x_mean"].numpy(), bundle["x_std"].numpy(),
                   bundle["y_mean"], bundle["y_std"], device=dev)

    def _matrix(self, frame: pd.DataFrame) -> np.ndarray:
        missing = [c for c in self.features if c not in frame.columns]
        if missing:
            raise ValueError(f"frame is missing feature columns: {missing}")
        return frame[self.features].to_numpy(dtype=float)

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        """Expected TEY (MWh) per row given the FEATURE_KEYS readings. NaN features yield NaN predictions."""
        if len(frame) == 0:
            return np.array([], dtype=float)
        X = self._matrix(frame)
        bad = np.isnan(X).any(axis=1)
        out = np.full(len(X), np.nan, dtype=float)
        if (~bad).any():
            X_std = (X[~bad] - self._x_mean) / self._x_std
            out[~bad] = _predict_array(self._net, X_std, self._device, self._y_mean, self._y_std)
        return out

    def residuals(self, frame: pd.DataFrame) -> np.ndarray:
        """observed TEY - expected TEY, per row."""
        observed = frame[TARGET_KEY].to_numpy(dtype=float)
        return observed - self.predict(frame)

    def out_of_range_counts(self, frame: pd.DataFrame) -> dict[str, int]:
        """Rows per feature whose value lies outside the training min/max (``feature_ranges_train``)."""
        counts: dict[str, int] = {}
        for key, (lo, hi) in self.evaluation.feature_ranges_train.items():
            if key not in frame.columns:
                continue
            vals = frame[key].to_numpy(dtype=float)
            counts[key] = int(np.sum((vals < lo) | (vals > hi)))
        return counts
