"""FastAPI router for ops workflow features (prefix ``/ops``; main.py mounts it under ``/api``).

POST /ops/handover · GET /ops/handover · GET /ops/handover/{note_id}
GET  /ops/cmms/{case_id}.json · GET /ops/cmms/{case_id}.csv · GET /ops/metrics
All read-only with respect to investigations; only the ``handover_notes`` table is written.
"""
from __future__ import annotations

import logging
import re
import threading
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse, Response

from app import config, services
from app.features.ops import cmms, handover, metrics
from app.features.ops.schemas import HandoverNote, HandoverNoteSummary, HandoverRequest, OpsMetrics
from app.schemas import Investigation

router = APIRouter(prefix="/ops", tags=["ops"])
log = logging.getLogger("thermomind.ops.router")

_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
_PERSONA_RE = re.compile(r"^[A-Za-z0-9_\-\. ]{1,64}$")
DEFAULT_REQUESTER = "reliability_engineer"


# ----------------------------------------------------------------------------- providers (patched in tests)
def get_investigations() -> list[Investigation]:
    return services.get_store().list()


def get_investigation(case_id: str) -> Investigation:
    return services.get_store().get(case_id)  # KeyError when unknown


def get_meta_client() -> Any:
    try:
        client = services.get_meta_client()
        return client if client.configured else None
    except Exception as exc:  # noqa: BLE001 - offline fallback instead of failing
        log.warning("meta client unavailable: %s", type(exc).__name__)
        return None


def get_work_requests() -> tuple[list[Any], bool]:
    """Open work requests from the PLANT-OPS workstream if that module exists; never fails."""
    try:
        from app.plant import work_requests as wr_mod  # guarded: optional sibling workstream

        items = wr_mod.store.list_work_requests()
        return [w for w in items if getattr(w, "status", None) in ("open", "acknowledged")], True
    except Exception as exc:  # noqa: BLE001
        log.info("work requests unavailable: %s", type(exc).__name__)
        return [], False


def get_health_flags() -> dict[str, Any]:
    flags: dict[str, Any] = {}
    blockers: list[str] = []
    try:
        flags["data_ready"] = bool(services.data_ready())
    except Exception:  # noqa: BLE001
        flags["data_ready"] = False
    if not flags["data_ready"]:
        blockers.append("UCI dataset not loaded")
    try:
        flags["model_ready"] = services.get_model() is not None
    except Exception:  # noqa: BLE001
        flags["model_ready"] = False
    if not flags["model_ready"]:
        blockers.append("baseline model not trained")
    flags["meta_configured"] = bool(config.meta_configured())
    flags["meta_model"] = config.META_MODEL
    flags["blockers"] = blockers
    flags["ready_for_demo"] = not blockers
    return flags


_store_lock = threading.Lock()
_stores: dict[str, handover.HandoverStore] = {}


def get_handover_store() -> handover.HandoverStore:
    key = str(Path(config.DB_PATH))
    with _store_lock:
        if key not in _stores:
            _stores[key] = handover.HandoverStore(Path(key))
        return _stores[key]


def _check_id(value: str, what: str) -> str:
    if not _ID_RE.match(value or ""):
        raise HTTPException(status_code=404, detail=f"{what} '{str(value)[:64]}' not found")
    return value


def _load_case(case_id: str) -> Investigation:
    _check_id(case_id, "investigation")
    try:
        return get_investigation(case_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"investigation '{case_id}' not found") from None


def _requester(persona: Optional[str], x_persona: Optional[str]) -> str:
    for p in (persona, x_persona):
        if p and _PERSONA_RE.match(p):
            return p
    return DEFAULT_REQUESTER


# ----------------------------------------------------------------------------- handover
@router.post("/handover", response_model=HandoverNote, name="ops_create_handover")
def create_handover(req: HandoverRequest) -> HandoverNote:
    wrs, available = get_work_requests()
    return handover.generate_handover(
        hours=req.hours, persona=req.persona, investigations=get_investigations(), client=get_meta_client(),
        store=get_handover_store(), work_requests=wrs, work_requests_available=available,
        health=get_health_flags(),
    )


@router.get("/handover", response_model=list[HandoverNote], name="ops_list_handover")
def list_handover(limit: int = Query(20, ge=1, le=100)) -> list[HandoverNote]:
    return get_handover_store().list(limit=limit)


@router.get("/handover/{note_id}", response_model=HandoverNote, name="ops_get_handover")
def get_handover(note_id: str) -> HandoverNote:
    _check_id(note_id, "handover note")
    try:
        return get_handover_store().get(note_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"handover note '{note_id}' not found") from None


@router.get("/handover-summaries", response_model=list[HandoverNoteSummary], name="ops_list_handover_summaries")
def list_handover_summaries(limit: int = Query(20, ge=1, le=100)) -> list[HandoverNoteSummary]:
    return [handover.summarize(n) for n in get_handover_store().list(limit=limit)]


# ----------------------------------------------------------------------------- CMMS draft
@router.get("/cmms/{case_id}.json", name="ops_cmms_json")
def cmms_json(case_id: str, persona: Optional[str] = Query(None), x_persona: Optional[str] = Header(None)) -> JSONResponse:
    inv = _load_case(case_id)
    doc = cmms.build_work_order(inv, _requester(persona, x_persona))
    return JSONResponse(doc, headers={"Content-Disposition": f'attachment; filename="{case_id}_work_order_draft.json"'})


@router.get("/cmms/{case_id}.csv", name="ops_cmms_csv")
def cmms_csv(case_id: str, persona: Optional[str] = Query(None), x_persona: Optional[str] = Header(None)) -> Response:
    inv = _load_case(case_id)
    doc = cmms.build_work_order(inv, _requester(persona, x_persona))
    return Response(cmms.work_order_csv(doc), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{case_id}_work_order_draft.csv"'})


# ----------------------------------------------------------------------------- metrics
@router.get("/metrics", response_model=OpsMetrics, name="ops_metrics")
def ops_metrics() -> OpsMetrics:
    return metrics.compute_metrics(get_investigations())
