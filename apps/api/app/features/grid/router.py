"""Grid-resilience endpoints (mounted under /api by the principal): /grid/readiness, /grid/drill, /grid/drills,
/grid/contingency. Read-only decision support; nothing here issues a control action."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app import config, services
from app.features.grid import drill as drill_mod
from app.features.grid import readiness as rd
from app.features.grid.schemas import ContingencyRequest, ContingencyResult, DrillRequest, GridDrill, GridReadiness

router = APIRouter(prefix="/grid", tags=["grid"])

_store_lock = threading.Lock()
_stores: dict[str, drill_mod.DrillStore] = {}


def get_drill_store() -> drill_mod.DrillStore:
    key = str(Path(config.DB_PATH))
    with _store_lock:
        if key not in _stores:
            _stores[key] = drill_mod.DrillStore(Path(config.DB_PATH))
        return _stores[key]


def get_grid_meta_client() -> Any:
    try:
        client = services.get_meta_client()
        return client if client.configured else None
    except Exception:  # noqa: BLE001 - offline fallback, never 500
        return None


def _bundle(dataset_id: str):
    try:
        return services.get_repo().get(dataset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0]) if exc.args else "dataset not found")


@router.get("/readiness", response_model=GridReadiness)
def grid_readiness(
    dataset_id: str = Query(services.UCI_DATASET_ID),
    year: int = Query(..., ge=2000, le=2100),
    start: Optional[int] = Query(None, ge=0, le=100_000, description="window start row_index (inclusive); default 0"),
    end: Optional[int] = Query(None, ge=0, le=100_000, description="window end row_index (exclusive); default end of year"),
    nameplate_mw: float = Query(rd.DEFAULT_NAMEPLATE_MW, gt=0, le=2000, description="ASSUMPTION"),
    h_constant_s: float = Query(rd.DEFAULT_H_S, gt=0, le=20, description="ASSUMPTION (inertia constant H, s)"),
    power_factor: float = Query(rd.DEFAULT_PF, gt=0.5, le=1.0, description="ASSUMPTION"),
) -> GridReadiness:
    bundle = _bundle(dataset_id)
    try:
        return rd.compute_readiness(bundle, year, start, end, nameplate_mw, h_constant_s, power_factor,
                                    computed_at_utc=services.now_utc())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0]) if exc.args else "not found")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/drill", response_model=GridDrill)
def grid_drill(req: DrillRequest, store: drill_mod.DrillStore = Depends(get_drill_store),
               client: Any = Depends(get_grid_meta_client)) -> GridDrill:
    bundle = _bundle(req.dataset_id)
    try:
        return drill_mod.run_drill(bundle, req, client=client if req.use_meta else None,
                                   now_utc=services.now_utc(), store=store)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0]) if exc.args else "not found")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/drills", response_model=list[GridDrill])
def grid_drills(limit: int = Query(20, ge=1, le=200),
                store: drill_mod.DrillStore = Depends(get_drill_store)) -> list[GridDrill]:
    return store.list(limit)


@router.get("/drills/{drill_id}", response_model=GridDrill)
def grid_drill_get(drill_id: str, store: drill_mod.DrillStore = Depends(get_drill_store)) -> GridDrill:
    try:
        return store.get(drill_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0]))


@router.post("/contingency", response_model=ContingencyResult)
def grid_contingency(req: ContingencyRequest) -> ContingencyResult:
    bundle = _bundle(req.dataset_id)
    try:
        return rd.compute_contingency(bundle, req, computed_at_utc=services.now_utc())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0]) if exc.args else "not found")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
