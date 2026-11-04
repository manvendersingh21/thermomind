"""Maintenance planner endpoints. Mount with ``app.include_router(router, prefix="/api")`` → ``/api/planner/...``.

Errors are mapped here (not via app-level handlers) so the router behaves the same in any FastAPI app:
model missing / unknown dataset → 404, bad inputs → 422 (Pydantic validation or ValueError).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.features.planner import engine
from app.features.planner.schemas import (
    DEFAULT_DATASET_ID,
    CompressorWashRequest,
    CompressorWashResult,
    FilterChangeoutRequest,
    FilterChangeoutResult,
    PlannerOptions,
)

router = APIRouter(prefix="/planner", tags=["planner"])


def _call(fn, req):
    try:
        return fn(req)
    except engine.ModelMissingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except KeyError as exc:
        detail = exc.args[0] if exc.args and isinstance(exc.args[0], str) else "not found"
        raise HTTPException(status_code=404, detail=str(detail)[:500]) from None
    except (ValueError, IndexError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)[:500] or "invalid input") from None


@router.get("/options", response_model=PlannerOptions)
def planner_options(dataset_id: str = Query(default=DEFAULT_DATASET_ID, min_length=1, max_length=128)) -> PlannerOptions:
    return engine.planner_options(dataset_id)


@router.post("/compressor-wash", response_model=CompressorWashResult)
def compressor_wash(req: CompressorWashRequest) -> CompressorWashResult:
    return _call(engine.run_compressor_wash, req)


@router.post("/filter-changeout", response_model=FilterChangeoutResult)
def filter_changeout(req: FilterChangeoutRequest) -> FilterChangeoutResult:
    return _call(engine.run_filter_changeout, req)
