"""FastAPI router for emissions watch (prefix ``/emissions``; main.py mounts it under ``/api``)."""
from __future__ import annotations

import math

from fastapi import APIRouter, HTTPException, Query

from app import services
from app.features.emissions import engine
from app.features.emissions.schemas import EmissionsResponse

router = APIRouter(prefix="/emissions", tags=["emissions"])

DEFAULT_DATASET = "ds_uci_551"


def _threshold(name: str, v: float | None) -> float | None:
    if v is None:
        return None
    if not math.isfinite(v) or v <= 0:
        raise HTTPException(status_code=422, detail=f"{name} must be a finite number > 0 (got {v})")
    return float(v)


def _run(dataset_id: str, year: int, start: int | None, end: int | None, co_t: float | None, nox_t: float | None) -> EmissionsResponse:
    co_t, nox_t = _threshold("co_threshold", co_t), _threshold("nox_threshold", nox_t)
    try:
        bundle = services.get_repo().get(dataset_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' not found") from None
    frame = bundle.year_frame(year)
    if len(frame) == 0:
        raise HTTPException(status_code=404, detail=f"dataset '{dataset_id}' has no rows for year {year}")
    try:
        return engine.analyze(
            frame,
            dataset_id=dataset_id,
            source_year=year,
            start=start,
            end=end,
            co_threshold=co_t,
            nox_threshold=nox_t,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.get("/overview", response_model=EmissionsResponse)
def overview(
    year: int = Query(..., ge=2000, le=2100, description="source year"),
    dataset_id: str = Query(DEFAULT_DATASET),
    co_threshold: float | None = Query(None, le=1e5, description="screening threshold for CO, mg/m³ (default: p95 of the year)"),
    nox_threshold: float | None = Query(None, le=1e5, description="screening threshold for NOX, mg/m³ (default: p95 of the year)"),
) -> EmissionsResponse:
    """Whole-year emissions screening: KPIs, binned regime profile, excursions, downsampled series."""
    return _run(dataset_id, year, None, None, co_threshold, nox_threshold)


@router.get("/window", response_model=EmissionsResponse)
def window(
    year: int = Query(..., ge=2000, le=2100),
    start: int = Query(..., ge=0, le=100_000, description="first row_index (inclusive)"),
    end: int = Query(..., ge=1, le=100_000, description="last row_index (exclusive)"),
    dataset_id: str = Query(DEFAULT_DATASET),
    co_threshold: float | None = Query(None, le=1e5),
    nox_threshold: float | None = Query(None, le=1e5),
) -> EmissionsResponse:
    """Same payload for a row_index window; default thresholds stay the whole-year p95."""
    if end <= start:
        raise HTTPException(status_code=422, detail=f"end ({end}) must be greater than start ({start})")
    return _run(dataset_id, year, start, end, co_threshold, nox_threshold)
