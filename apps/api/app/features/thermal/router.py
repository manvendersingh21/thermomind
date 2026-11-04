"""FastAPI router for thermal monitoring (prefix ``/thermal``; main.py mounts it under ``/api``).

Read-only: evaluates a SIMULATED thermal feed derived from real load (TEY) and ambient (AT) data. No endpoint
here writes to any plant system.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import services
from app.features.thermal import engine
from app.features.thermal.schemas import (
    ThermalAssetsResponse,
    ThermalAssumptions,
    ThermalEvaluateRequest,
    ThermalEvaluateResponse,
)

router = APIRouter(prefix="/thermal", tags=["thermal"])


@router.get("/assets", response_model=ThermalAssetsResponse)
def list_assets() -> ThermalAssetsResponse:
    """Balance-of-plant assets in one-line order, model/standard per asset, default assumptions."""
    return ThermalAssetsResponse(
        assets=engine.ASSETS,
        default_assumptions=ThermalAssumptions(),
        scenarios=["none", "T01_HOT_CONNECTION"],
        demand_profiles=engine.DEMAND_PROFILES,
    )


@router.post("/evaluate", response_model=ThermalEvaluateResponse)
def evaluate(req: ThermalEvaluateRequest) -> ThermalEvaluateResponse:
    """Simulated thermal status, screening flags, transformer ageing and read-only advisories for a window."""
    if req.end <= req.start:
        raise HTTPException(status_code=422, detail=f"end ({req.end}) must be greater than start ({req.start})")
    n = req.end - req.start
    if n < engine.MIN_WINDOW or n > engine.MAX_WINDOW:
        raise HTTPException(status_code=422, detail=f"window must contain {engine.MIN_WINDOW}..{engine.MAX_WINDOW} samples (got {n})")
    try:
        bundle = services.get_repo().get(req.dataset_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"dataset '{req.dataset_id}' not found") from None
    try:
        frame = bundle.window(req.year, req.start, req.end)
    except IndexError as exc:
        raise HTTPException(status_code=422, detail=str(exc) or "window out of range") from None
    if len(frame) == 0:
        raise HTTPException(status_code=422, detail=f"no rows for year {req.year} in [{req.start}, {req.end})")
    if len(frame) != n:
        raise HTTPException(status_code=422, detail=f"window [{req.start}, {req.end}) exceeds the {req.year} rows available")
    try:
        return engine.evaluate(
            frame, dataset_id=req.dataset_id, year=req.year, start=req.start, end=req.end,
            assumptions=req.assumptions, scenario=req.scenario, scenario_seed=req.scenario_seed,
            demand_multiplier=req.demand_multiplier, demand_profile=req.demand_profile,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
