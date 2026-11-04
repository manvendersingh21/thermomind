"""Second opinion from the GPU-trained challenger MLP (``compute_second_opinion``).

The production baseline (HGBR ``baseline_v1``) stays the model of record for every investigation. When the
challenger (``mlp_v1``, ``TorchBaselineModel``) is available, its residual for the same window/reference rows
is computed as an *independent second opinion* and compared with the production residual:

* both |z| >= 2 with the same sign  -> ``agree_notable``  (the two baselines corroborate a deviation)
* both |z| <  2                     -> ``agree_normal``   (neither baseline sees a notable deviation)
* anything else                     -> ``disagree``       (treat the residual as uncertain)

z for each model is ``(residual_mean_window - residual_mean_reference) / residual_std_validation`` using that
model's own validation residual std, i.e. the same reference-adjusted definition the production evidence uses
for its notable flag. Nothing here asserts a fault; the challenger never replaces the production model.

``torch`` is only touched through the challenger object, so importing this module never requires torch.
"""
from __future__ import annotations

import math
import threading
import time
from typing import Any

import numpy as np
import pandas as pd

from app.schemas import TARGET_KEY

NOTABLE_Z = 2.0
ROLE_DESCRIPTION = (
    "independent GPU-trained MLP baseline (challenger, not production); used only as a second opinion on the "
    "production baseline's TEY residual"
)
AGREEMENT_NOTES = {
    "agree_notable": "Both baselines show a notable residual deviation (|z|>=2) in the same direction: "
                     "the residual deviation is corroborated by two independently trained models.",
    "agree_normal": "Neither baseline shows a notable window-mean residual deviation vs the reference (both |z|<2); "
                    "this compares window means only and says nothing about trends within the window.",
    "disagree": "Treat the residual as uncertain; the two baselines do not corroborate.",
}
AGREEMENT_LABELS = tuple(AGREEMENT_NOTES)

_infer_lock = threading.Lock()  # one GPU inference at a time (the API serves requests from a thread pool)


def _finite(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def classify_agreement(production_z: float | None, challenger_z: float | None,
                       threshold: float = NOTABLE_Z) -> tuple[str, str]:
    """(label, plain-language note) for two reference-adjusted residual z values.

    Missing/non-finite z values cannot corroborate anything, so they classify as ``disagree``."""
    pz, cz = _finite(production_z), _finite(challenger_z)
    if pz is None or cz is None:
        return "disagree", AGREEMENT_NOTES["disagree"] + " (one of the residual z values is unavailable)"
    p_notable, c_notable = abs(pz) >= threshold, abs(cz) >= threshold
    if p_notable and c_notable and (pz > 0) == (cz > 0):
        return "agree_notable", AGREEMENT_NOTES["agree_notable"]
    if not p_notable and not c_notable:
        return "agree_normal", AGREEMENT_NOTES["agree_normal"]
    return "disagree", AGREEMENT_NOTES["disagree"]


def _device_string(challenger: Any) -> str:
    dev = getattr(challenger, "_device", None)
    if dev is None:
        return "cpu"
    try:
        from app.analytics.torch_baseline import device_label

        return device_label(dev)
    except Exception:  # noqa: BLE001
        return str(dev)


def compute_second_opinion(
    window_frame: pd.DataFrame,
    reference_frame: pd.DataFrame,
    challenger: Any,
    production_z: float | None = None,
) -> dict[str, Any]:
    """Challenger residual statistics for the case window vs the reference window.

    ``production_z`` (the production residual's z_vs_reference) is optional; when given, the result also carries
    the ``agreement`` label and note. All floats are finite or ``None``.
    """
    wf = window_frame.reset_index(drop=True)
    rf = reference_frame.reset_index(drop=True)
    ev = challenger.evaluation
    std_val = float(ev.residual_std_validation)

    with _infer_lock:
        t0 = time.perf_counter()
        expected_w = challenger.predict(wf) if len(wf) else np.array([], dtype=float)
        expected_r = challenger.predict(rf) if len(rf) else np.array([], dtype=float)
        inference_ms = (time.perf_counter() - t0) * 1000.0  # predictions are copied back to host, so this is synced

    obs_w = wf[TARGET_KEY].to_numpy(dtype=float) if len(wf) else np.array([], dtype=float)
    obs_r = rf[TARGET_KEY].to_numpy(dtype=float) if len(rf) else np.array([], dtype=float)
    resid_w = obs_w - expected_w
    resid_r = obs_r - expected_r
    rw = resid_w[np.isfinite(resid_w)]
    rr = resid_r[np.isfinite(resid_r)]
    resid_mean = float(np.mean(rw)) if rw.size else float("nan")
    ref_resid_mean = float(np.mean(rr)) if rr.size else float("nan")
    resid_std_w = float(np.std(rw, ddof=1)) if rw.size > 1 else float("nan")
    z_raw = resid_mean / std_val if std_val > 0 else float("nan")
    z_ref = (resid_mean - ref_resid_mean) / std_val if std_val > 0 else float("nan")

    out: dict[str, Any] = {
        "available": True,
        "role": "challenger",
        "description": ROLE_DESCRIPTION,
        "model_id": ev.model_id,
        "model_version": challenger.version,
        "algorithm": ev.algorithm,
        "unit": "MWh",
        "observed_tey_mean": _finite(np.nanmean(obs_w)) if obs_w.size else None,
        "expected_tey_mean": _finite(np.nanmean(expected_w)) if expected_w.size else None,
        "reference_observed_tey_mean": _finite(np.nanmean(obs_r)) if obs_r.size else None,
        "reference_expected_tey_mean": _finite(np.nanmean(expected_r)) if expected_r.size else None,
        "residual_mean_window": _finite(resid_mean),
        "residual_mean_reference": _finite(ref_resid_mean),
        "residual_std_window": _finite(resid_std_w),
        "residual_std_validation": _finite(std_val),
        "z_raw": _finite(z_raw),
        "z_vs_reference": _finite(z_ref),
        "notable": bool(_finite(z_ref) is not None and abs(z_ref) >= NOTABLE_Z),
        "n_window": int(rw.size),
        "n_reference": int(rr.size),
        "holdout_mae": _finite(ev.holdout.mae),
        "holdout_r2": _finite(ev.holdout.r2),
        "validation_mae": _finite(ev.validation.mae),
        "device": _device_string(challenger),
        "inference_ms": round(float(inference_ms), 3),
        "production_z_vs_reference": _finite(production_z),
        "agreement": None,
        "agreement_note": None,
    }
    if production_z is not None:
        label, note = classify_agreement(production_z, z_ref)
        out["agreement"] = label
        out["agreement_note"] = note
    return out
