"""Deterministic emissions-watch engine. Pure pandas/numpy; no I/O, no randomness.

Inputs are the real measured CO / NOX columns of one source-year frame (``row_index`` ordered, no timestamps).
Everything here is SCREENING ONLY and not a compliance determination.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from app.features.emissions.schemas import (
    Correlation,
    Distribution,
    EmissionsResponse,
    Excursion,
    Kpis,
    ProfileBin,
    SeriesRow,
    Thresholds,
)

MIN_RUN = 3  # consecutive samples
MAX_SERIES_POINTS = 2000
MAX_EXCURSIONS = 500
N_BINS = 10
TIT_LOOKBACK = 3
TIT_TREND_C = 15.0  # degC change that counts as "rising"/"falling"

REQUIRED_COLUMNS = ("row_index", "CO", "NOX", "TEY", "TIT", "AT")

CONTEXT_RULES = [
    "part-load operation: excursion mean TEY <= P25 of the year's TEY",
    "high ambient: excursion mean AT >= P75 of the year's AT; low ambient: <= P25",
    "TIT trend = TIT(end of excursion) - TIT(3 samples before start): >= +15 degC is 'cold start-like transient' "
    "when mean TEY <= year median, else 'load ramp-up-like'; <= -15 degC is 'ramp-down-like'",
    "high load: excursion mean TEY >= P75 of the year's TEY (NOX only)",
    "Heuristic labels from simple thresholds on concurrent measurements; not a root-cause finding.",
]


def _f(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _quantile(s: pd.Series, q: float) -> float | None:
    v = s.dropna()
    return _f(v.quantile(q)) if len(v) else None


def p95(series: pd.Series) -> float | None:
    return _quantile(series, 0.95)


def distribution(series: pd.Series) -> Distribution:
    v = pd.to_numeric(series, errors="coerce").dropna()
    v = v[np.isfinite(v)]
    if v.empty:
        return Distribution(n=0)
    return Distribution(
        n=int(len(v)),
        mean=_f(v.mean()),
        min=_f(v.min()),
        p05=_f(v.quantile(0.05)),
        p25=_f(v.quantile(0.25)),
        p50=_f(v.quantile(0.50)),
        p75=_f(v.quantile(0.75)),
        p95=_f(v.quantile(0.95)),
        p99=_f(v.quantile(0.99)),
        max=_f(v.max()),
    )


def correlation(df: pd.DataFrame, x: str, y: str) -> Correlation:
    sub = df[[x, y]].dropna()
    n = int(len(sub))
    pear = spear = None
    if n >= 3 and sub[x].nunique() > 1 and sub[y].nunique() > 1:
        pear = _f(sub[x].corr(sub[y], method="pearson"))
        spear = _f(sub[x].corr(sub[y], method="spearman"))
    return Correlation(x=x, y=y, n=n, pearson=pear, spearman=spear)


def find_runs(values: np.ndarray, row_index: np.ndarray, threshold: float, min_run: int = MIN_RUN) -> list[tuple[int, int]]:
    """Positional (start, end_inclusive) runs of >= ``min_run`` consecutive samples with value > threshold.

    Consecutive means adjacent positions whose row_index differs by exactly 1; NaN breaks a run."""
    above = np.zeros(values.shape, dtype=bool)
    ok = np.isfinite(values)
    above[ok] = values[ok] > threshold
    runs: list[tuple[int, int]] = []
    i, n = 0, len(values)
    while i < n:
        if not above[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and above[j + 1] and row_index[j + 1] - row_index[j] == 1:
            j += 1
        if j - i + 1 >= min_run:
            runs.append((i, j))
        i = j + 1
    return runs


def _bin_edges(year_values: pd.Series, n_bins: int = N_BINS) -> np.ndarray:
    v = year_values.dropna().to_numpy(dtype=float)
    if v.size == 0:
        return np.array([])
    edges = np.unique(np.quantile(v, np.linspace(0.0, 1.0, n_bins + 1)))
    return edges


def profile(window: pd.DataFrame, year: pd.DataFrame, by: str, n_bins: int = N_BINS) -> list[ProfileBin]:
    """Binned medians of CO/NOX/TEY/TIT/AT vs ``by`` ('TEY' or 'TIT'); edges = deciles of the whole year."""
    edges = _bin_edges(year[by], n_bins)
    if edges.size < 2:
        return []
    w = window.dropna(subset=[by])
    idx = np.clip(np.searchsorted(edges, w[by].to_numpy(dtype=float), side="right") - 1, 0, len(edges) - 2)
    out: list[ProfileBin] = []
    for b in range(len(edges) - 1):
        g = w[idx == b]
        if g.empty:
            continue
        out.append(
            ProfileBin(
                bin=b + 1,
                lo=float(edges[b]),
                hi=float(edges[b + 1]),
                n=int(len(g)),
                tey_median=_quantile(g["TEY"], 0.5),
                tit_median=_quantile(g["TIT"], 0.5),
                at_median=_quantile(g["AT"], 0.5),
                co_median=_quantile(g["CO"], 0.5),
                co_p25=_quantile(g["CO"], 0.25),
                co_p75=_quantile(g["CO"], 0.75),
                co_p95=_quantile(g["CO"], 0.95),
                nox_median=_quantile(g["NOX"], 0.5),
                nox_p25=_quantile(g["NOX"], 0.25),
                nox_p75=_quantile(g["NOX"], 0.75),
                nox_p95=_quantile(g["NOX"], 0.95),
            )
        )
    return out


def _mean(a: np.ndarray) -> float | None:
    a = a[np.isfinite(a)]
    return _f(a.mean()) if a.size else None


def _context(pollutant: str, tey_mean, at_mean, tit_change, refs: dict[str, float | None]) -> tuple[list[str], str]:
    tags: list[str] = []
    if tit_change is not None and tit_change >= TIT_TREND_C:
        if tey_mean is not None and refs["tey_p50"] is not None and tey_mean <= refs["tey_p50"]:
            tags.append("cold start-like transient (TIT rising)")
        else:
            tags.append("load ramp-up-like (TIT rising)")
    elif tit_change is not None and tit_change <= -TIT_TREND_C:
        tags.append("ramp-down-like (TIT falling)")
    if tey_mean is not None and refs["tey_p25"] is not None and tey_mean <= refs["tey_p25"]:
        tags.append("part-load operation")
    if pollutant == "NOX" and tey_mean is not None and refs["tey_p75"] is not None and tey_mean >= refs["tey_p75"]:
        tags.append("high load")
    if at_mean is not None and refs["at_p75"] is not None and at_mean >= refs["at_p75"]:
        tags.append("high ambient")
    elif at_mean is not None and refs["at_p25"] is not None and at_mean <= refs["at_p25"]:
        tags.append("low ambient")
    if not tags:
        text = "no distinctive operating context (mid-range load and ambient) - heuristic"
    else:
        text = "Plausible context: " + ", ".join(tags) + " - heuristic"
    return tags, text


def _excursions(year: pd.DataFrame, lo_pos: int, hi_pos: int, thr: dict[str, float], refs) -> list[Excursion]:
    """Excursions within year-frame positions [lo_pos, hi_pos)."""
    ri_all = year["row_index"].to_numpy()
    tit_all = year["TIT"].to_numpy(dtype=float)
    out: list[Excursion] = []
    for pol, col in (("CO", "CO"), ("NOX", "NOX")):
        vals = year[col].to_numpy(dtype=float)[lo_pos:hi_pos]
        ri = ri_all[lo_pos:hi_pos]
        for a, b in find_runs(vals, ri, thr[pol]):
            pa, pb = lo_pos + a, lo_pos + b
            seg = vals[a : b + 1]
            k = int(np.nanargmax(seg))
            tey_m = _mean(year["TEY"].to_numpy(dtype=float)[pa : pb + 1])
            tit_m = _mean(tit_all[pa : pb + 1])
            at_m = _mean(year["AT"].to_numpy(dtype=float)[pa : pb + 1])
            before = tit_all[max(0, pa - TIT_LOOKBACK)]
            tit_change = _f(tit_all[pb] - before) if pa > 0 else None
            tags, text = _context(pol, tey_m, at_m, tit_change, refs)
            peak = float(seg[k])
            out.append(
                Excursion(
                    excursion_id=f"{pol}-{int(ri_all[pa])}",
                    pollutant=pol,  # type: ignore[arg-type]
                    start_index=int(ri_all[pa]),
                    end_index=int(ri_all[pb]),
                    n_samples=int(b - a + 1),
                    peak_value=peak,
                    peak_index=int(ri[a + k]),
                    mean_value=float(np.nanmean(seg)),
                    threshold=float(thr[pol]),
                    peak_ratio=float(peak / thr[pol]) if thr[pol] > 0 else float("nan"),
                    tey_mean=tey_m,
                    tit_mean=tit_m,
                    at_mean=at_m,
                    tit_change=tit_change,
                    context_tags=tags,
                    context=text,
                )
            )
    out.sort(key=lambda e: (e.start_index, e.pollutant))
    return out


def downsample_series(window: pd.DataFrame, thr: dict[str, float], max_points: int = MAX_SERIES_POINTS) -> tuple[list[SeriesRow], int]:
    """Peak-preserving downsample: each bucket keeps the row with the largest threshold exceedance ratio."""
    n = len(window)
    factor = max(1, math.ceil(n / max_points))
    w = window.reset_index(drop=True)
    if factor > 1:
        ratio = np.fmax(
            np.nan_to_num(w["CO"].to_numpy(dtype=float) / thr["CO"], nan=-1.0),
            np.nan_to_num(w["NOX"].to_numpy(dtype=float) / thr["NOX"], nan=-1.0),
        )
        keep = []
        for s in range(0, n, factor):
            seg = ratio[s : s + factor]
            keep.append(s + int(np.argmax(seg)))
        w = w.iloc[keep]
    rows = [
        SeriesRow(
            row_index=int(r.row_index),
            co=_f(r.CO),
            nox=_f(r.NOX),
            tey=_f(r.TEY),
            tit=_f(r.TIT),
            at=_f(r.AT),
        )
        for r in w.itertuples(index=False)
    ]
    return rows, factor


def analyze(
    year_frame: pd.DataFrame,
    *,
    dataset_id: str,
    source_year: int,
    start: int | None = None,
    end: int | None = None,
    co_threshold: float | None = None,
    nox_threshold: float | None = None,
    max_points: int = MAX_SERIES_POINTS,
) -> EmissionsResponse:
    """Analyse ``year_frame`` rows with row_index in [start, end) (default: whole year).

    Default thresholds are the p95 of CO / NOX over the WHOLE YEAR (also for sub-windows, so they stay comparable).
    Raises ValueError for unusable input."""
    missing = [c for c in REQUIRED_COLUMNS if c not in year_frame.columns]
    if missing:
        raise ValueError(f"dataset lacks required column(s): {', '.join(missing)}")
    yf = year_frame.sort_values("row_index", kind="stable").reset_index(drop=True)
    total = len(yf)
    if total == 0:
        raise ValueError("no rows for the requested year")
    ri = yf["row_index"].to_numpy()
    s = int(ri[0]) if start is None else int(start)
    e = int(ri[-1]) + 1 if end is None else int(end)
    if s < 0 or e <= s:
        raise ValueError(f"invalid window: start={s}, end={e} (need 0 <= start < end)")
    lo_pos = int(np.searchsorted(ri, s, side="left"))
    hi_pos = int(np.searchsorted(ri, e, side="left"))
    if hi_pos - lo_pos < MIN_RUN:
        raise ValueError(f"window [{s}, {e}) contains {hi_pos - lo_pos} rows; need at least {MIN_RUN}")
    win = yf.iloc[lo_pos:hi_pos]

    co_def, nox_def = p95(yf["CO"]), p95(yf["NOX"])
    if co_def is None or nox_def is None:
        raise ValueError("CO/NOX have no finite values in this year")
    co_thr = co_def if co_threshold is None else float(co_threshold)
    nox_thr = nox_def if nox_threshold is None else float(nox_threshold)
    if not (math.isfinite(co_thr) and co_thr > 0 and math.isfinite(nox_thr) and nox_thr > 0):
        raise ValueError("thresholds must be finite and > 0")
    thr = {"CO": co_thr, "NOX": nox_thr}
    thresholds = Thresholds(
        co=co_thr,
        nox=nox_thr,
        co_default_p95=co_def,
        nox_default_p95=nox_def,
        co_source="default_p95_of_year" if co_threshold is None else "user",
        nox_source="default_p95_of_year" if nox_threshold is None else "user",
    )

    refs = {
        "tey_p25": _quantile(yf["TEY"], 0.25),
        "tey_p50": _quantile(yf["TEY"], 0.50),
        "tey_p75": _quantile(yf["TEY"], 0.75),
        "at_p25": _quantile(yf["AT"], 0.25),
        "at_p75": _quantile(yf["AT"], 0.75),
    }
    excursions = _excursions(yf, lo_pos, hi_pos, thr, refs)
    truncated = len(excursions) > MAX_EXCURSIONS
    n_co = sum(1 for x in excursions if x.pollutant == "CO")
    n_nox = len(excursions) - n_co

    co = win["CO"].to_numpy(dtype=float)
    nox = win["NOX"].to_numpy(dtype=float)
    above_co = np.isfinite(co) & (co > co_thr)
    above_nox = np.isfinite(nox) & (nox > nox_thr)
    n_valid_co, n_valid_nox = int(np.isfinite(co).sum()), int(np.isfinite(nox).sum())
    kpis = Kpis(
        rows_analyzed=int(len(win)),
        hours_above_co=int(above_co.sum()),
        hours_above_nox=int(above_nox.sum()),
        hours_above_any=int((above_co | above_nox).sum()),
        pct_above_co=_f(100.0 * above_co.sum() / n_valid_co) if n_valid_co else None,
        pct_above_nox=_f(100.0 * above_nox.sum() / n_valid_nox) if n_valid_nox else None,
        excursions_co=n_co,
        excursions_nox=n_nox,
        excursions_total=len(excursions),
        longest_excursion_samples=max((x.n_samples for x in excursions), default=0),
        corr_co_tey=correlation(win, "CO", "TEY"),
        corr_co_at=correlation(win, "CO", "AT"),
        corr_nox_tey=correlation(win, "NOX", "TEY"),
        corr_nox_at=correlation(win, "NOX", "AT"),
    )

    series, factor = downsample_series(win, thr, max_points)
    whole_year = lo_pos == 0 and hi_pos == total
    return EmissionsResponse(
        dataset_id=dataset_id,
        source_year=int(source_year),
        start=int(ri[lo_pos]),
        end=int(ri[hi_pos - 1]) + 1,
        total_rows_in_year=int(total),
        thresholds=thresholds,
        kpis=kpis,
        distribution_co=distribution(win["CO"]),
        distribution_nox=distribution(win["NOX"]),
        profile_tey=profile(win, yf, "TEY"),
        profile_tit=profile(win, yf, "TIT"),
        profile_basis=(
            "bin edges = deciles of the whole year; statistics from "
            + ("the whole year" if whole_year else "the selected window")
        ),
        context_rules=CONTEXT_RULES,
        excursions=excursions[:MAX_EXCURSIONS],
        excursions_truncated=truncated,
        series=series,
        downsample_factor=factor,
        series_note=(
            "full resolution"
            if factor == 1
            else f"peak-preserving downsample, 1 of every {factor} samples (the one with the largest threshold ratio)"
        ),
    )
