"""Deterministic statistical helpers used by ``evidence.py``.

All functions are NaN-tolerant and return plain floats (``nan`` when undefined).
"""
from __future__ import annotations

import numpy as np


def _clean(x) -> np.ndarray:
    arr = np.asarray(x, dtype=float).ravel()
    return arr[~np.isnan(arr)]


def window_vs_reference(series_w, series_r) -> dict[str, float]:
    """Compare a case window against a reference window.

    Returns median/mean of each, ``delta`` (= median_w - median_r), ``delta_pct`` relative to the
    reference median, and ``z`` = (mean_w - mean_r) / std(reference, ddof=1)."""
    w = _clean(series_w)
    r = _clean(series_r)
    out = {
        "median_w": float(np.median(w)) if w.size else float("nan"),
        "median_r": float(np.median(r)) if r.size else float("nan"),
        "mean_w": float(np.mean(w)) if w.size else float("nan"),
        "mean_r": float(np.mean(r)) if r.size else float("nan"),
        "std_r": float(np.std(r, ddof=1)) if r.size > 1 else float("nan"),
        "n": int(w.size),
        "n_ref": int(r.size),
    }
    out["delta"] = out["median_w"] - out["median_r"]
    out["delta_pct"] = (100.0 * out["delta"] / out["median_r"]) if out["median_r"] not in (0.0,) and np.isfinite(out["median_r"]) else float("nan")
    std_r = out["std_r"]
    if np.isfinite(std_r) and std_r > 0:
        out["z"] = (out["mean_w"] - out["mean_r"]) / std_r
    else:
        out["z"] = float("nan")
    return out


def trend_slope(series) -> float:
    """Least-squares slope per sample (units of the series per row). NaNs are skipped."""
    arr = np.asarray(series, dtype=float).ravel()
    idx = np.arange(arr.size, dtype=float)
    mask = ~np.isnan(arr)
    if mask.sum() < 2:
        return float("nan")
    x = idx[mask]
    y = arr[mask]
    x = x - x.mean()
    denom = float(np.sum(x * x))
    if denom == 0.0:
        return float("nan")
    return float(np.sum(x * (y - y.mean())) / denom)


def robust_z(series) -> np.ndarray:
    """Robust z-score vs the series' own median using MAD (scaled by 1.4826). NaN stays NaN."""
    arr = np.asarray(series, dtype=float).ravel()
    clean = arr[~np.isnan(arr)]
    if clean.size == 0:
        return np.full(arr.shape, np.nan)
    med = float(np.median(clean))
    mad = float(np.median(np.abs(clean - med))) * 1.4826
    if mad == 0.0:
        # degenerate scale: fall back to std so constant series return 0 and real steps still register
        sd = float(np.std(clean, ddof=1)) if clean.size > 1 else 0.0
        if sd == 0.0:
            return np.where(np.isnan(arr), np.nan, 0.0)
        return (arr - med) / sd
    return (arr - med) / mad


def spike_segments(series, z_thresh: float = 3.0) -> list[tuple[int, int, float]]:
    """Contiguous runs of |robust z| >= z_thresh. Returns [(start, end_exclusive, peak_z), ...]."""
    z = robust_z(series)
    flagged = np.abs(np.nan_to_num(z, nan=0.0)) >= z_thresh
    segments: list[tuple[int, int, float]] = []
    i = 0
    n = flagged.size
    while i < n:
        if flagged[i]:
            j = i
            while j < n and flagged[j]:
                j += 1
            seg = z[i:j]
            peak = seg[np.nanargmax(np.abs(seg))]
            segments.append((int(i), int(j), float(peak)))
            i = j
        else:
            i += 1
    return segments


def correlation(a, b) -> float:
    """Pearson correlation of two equal-length series (NaN pairs dropped); nan if undefined."""
    x = np.asarray(a, dtype=float).ravel()
    y = np.asarray(b, dtype=float).ravel()
    if x.size != y.size:
        raise ValueError("series must have equal length")
    mask = ~(np.isnan(x) | np.isnan(y))
    x, y = x[mask], y[mask]
    if x.size < 3 or np.std(x) == 0.0 or np.std(y) == 0.0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])
