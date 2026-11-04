"""Executive view endpoints (prefix ``/executive``; main.py mounts under ``/api``).

GET  /executive/overview?year=2014   CEO-level KPIs with provenance + rule-based attention list
POST /executive/brief                ONE Muse Spark call (+1 bounded rewrite) -> validated draft or labelled fallback
GET  /executive/briefs               stored briefs (newest first) · GET /executive/briefs/{brief_id}
Read-only with respect to every other table; only ``executive_briefs`` is written.
"""
from __future__ import annotations

import logging
import re
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from app import config
from app.features.executive import brief as brief_mod
from app.features.executive import overview as ov_mod
from app.features.executive.schemas import BriefRequest, ExecutiveBrief, ExecutiveOverview

router = APIRouter(prefix="/executive", tags=["executive"])
log = logging.getLogger("thermomind.executive.router")
_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


# ----------------------------------------------------------------------------- providers (patched in tests)
def get_sources() -> ov_mod.Sources:
    return ov_mod.Sources()


def get_meta_client() -> Any:
    try:
        from app import services

        client = services.get_meta_client()
        return client if client.configured else None
    except Exception as exc:  # noqa: BLE001 - offline fallback, never 500
        log.warning("meta client unavailable: %s", type(exc).__name__)
        return None


def now_utc() -> str:
    from app import services

    return services.now_utc()


_store_lock = threading.Lock()
_stores: dict[str, brief_mod.BriefStore] = {}


def get_store() -> brief_mod.BriefStore:
    key = str(Path(config.DB_PATH))
    with _store_lock:
        if key not in _stores:
            _stores[key] = brief_mod.BriefStore(Path(key))
        return _stores[key]


def _overview(year: int, dataset_id: str) -> ExecutiveOverview:
    try:
        return ov_mod.compute_overview(year, dataset_id, sources=get_sources(), now_utc=now_utc())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0]) if exc.args else "not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)[:500]) from None


@router.get("/overview", response_model=ExecutiveOverview)
def overview(year: int = Query(2014, ge=2000, le=2100),
             dataset_id: str = Query(ov_mod.DEFAULT_DATASET_ID, min_length=1, max_length=128)) -> ExecutiveOverview:
    return _overview(year, dataset_id)


@router.post("/brief", response_model=ExecutiveBrief)
async def create_brief(req: BriefRequest) -> ExecutiveBrief:
    def _run() -> ExecutiveBrief:
        ov = _overview(req.year, req.dataset_id)
        return brief_mod.generate_brief(ov, client=get_meta_client(), store=get_store(), now_utc=now_utc())

    return await run_in_threadpool(_run)


@router.get("/briefs", response_model=list[ExecutiveBrief])
def list_briefs(limit: int = Query(20, ge=1, le=100)) -> list[ExecutiveBrief]:
    return get_store().list(limit)


@router.get("/briefs/{brief_id}", response_model=ExecutiveBrief)
def get_brief(brief_id: str) -> ExecutiveBrief:
    if not _ID_RE.match(brief_id or ""):
        raise HTTPException(status_code=404, detail="executive brief not found")
    try:
        return get_store().get(brief_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"executive brief '{brief_id}' not found") from None
