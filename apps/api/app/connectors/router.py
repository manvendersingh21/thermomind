"""HTTP surface for the plant connectors. Mounted by the principal at prefix /api -> /api/connectors/*.

Everything here is labelled simulated. There is no endpoint that writes to a plant system.
"""
from __future__ import annotations

from typing import Any, Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.connectors.base import ControlSystem
from app.connectors.simulated_cmms import SimulatedCmms
from app.connectors.simulated_historian import TIME_AXIS, HistorianError, SimulatedHistorian
from app.connectors.simulated_notifier import SimulatedNotifier

router = APIRouter(prefix="/connectors", tags=["connectors"])


def _uci_year_frame(year: int) -> pd.DataFrame:
    from app import services

    repo = services.get_repo()
    try:
        bundle = repo.get(services.UCI_DATASET_ID)
    except KeyError:
        try:
            services.seed_uci_if_available()
            bundle = repo.get(services.UCI_DATASET_ID)
        except Exception:  # noqa: BLE001
            raise KeyError("UCI dataset is not loaded; run `make data` or POST /api/datasets/seed-uci") from None
    return bundle.year_frame(year)


_historian = SimulatedHistorian(_uci_year_frame)
_cmms = SimulatedCmms()
_notifier = SimulatedNotifier()
_control = ControlSystem()


def get_historian() -> SimulatedHistorian:
    return _historian


def get_cmms() -> SimulatedCmms:
    return _cmms


def get_notifier() -> SimulatedNotifier:
    return _notifier


# --- request models -----------------------------------------------------------------------
class HistorianStart(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    year: int = Field(2014, ge=2000, le=2100)
    advance_rate: float = Field(1.0, ge=0, le=1000, description="rows per real second; 0 = manual ticks only")
    start_index: int = Field(0, ge=0, le=100_000)


class DraftRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field("", max_length=2000)
    case_id: Optional[str] = Field(None, max_length=64)
    subsystem: Optional[str] = Field(None, max_length=64)


class NotifyRequest(BaseModel):
    persona: str = Field(..., min_length=1, max_length=64)
    message: str = Field(..., min_length=1, max_length=1000)


# --- status ---------------------------------------------------------------------------------
def build_status(hist: SimulatedHistorian, cmms: SimulatedCmms, notifier: SimulatedNotifier) -> dict[str, Any]:
    control = _control.capabilities()
    connectors = [
        {
            "name": "Historian", "kind": "historian", "mode": "simulated",
            "description": "Replays real UCI rows in order, as if a historian were feeding them. Read-only. "
                           "No wall-clock timestamps are attached.",
            "real_adapter_needs": [
                "Read-only OSIsoft PI Web API / AVEVA historian export, or an OPC UA read-only client",
                "Tag mapping from plant tag names to the 11 ThermoMind measurements",
                "A read-only service account on a DMZ replica",
            ],
            "detail": hist.status(),
        },
        {
            "name": "CMMS", "kind": "cmms", "mode": "simulated",
            "description": "Keeps DRAFT work orders in memory. Nothing is submitted anywhere.",
            "real_adapter_needs": [
                "SAP PM / IBM Maximo REST endpoint that accepts DRAFT work orders",
                "Mapping of ThermoMind subsystems to CMMS functional locations",
                "A human approves and submits inside the CMMS; ThermoMind never does",
            ],
            "detail": {"drafts": len(cmms.drafts()), "simulated": True},
        },
        {
            "name": "Notifications", "kind": "notifier", "mode": "simulated",
            "description": "In-app outbox only. No email or SMS leaves this process.",
            "real_adapter_needs": [
                "Email (SMTP) or SMS gateway approved by plant IT",
                "Persona-to-recipient directory",
            ],
            "detail": {"delivery": "in_app_simulated", "simulated": True},
        },
        {
            "name": "Control system", "kind": "control_system", "mode": "not_connected",
            "description": "Not connected, no write path. By design ThermoMind never reads from or writes to "
                           "PLC/DCS/SCADA.",
            "real_adapter_needs": [
                "Nothing. A future OPC UA / PI adapter would be a read-only historian source, never a write path.",
            ],
            "detail": control,
        },
    ]
    return {"simulated": True, "read_only": True, "time_axis": TIME_AXIS, "connectors": connectors}


@router.get("/status")
def status(h: SimulatedHistorian = Depends(get_historian), c: SimulatedCmms = Depends(get_cmms),
           n: SimulatedNotifier = Depends(get_notifier)) -> dict[str, Any]:
    return build_status(h, c, n)


# --- historian --------------------------------------------------------------------------------
@router.post("/historian/start")
def historian_start(req: HistorianStart, h: SimulatedHistorian = Depends(get_historian)) -> dict[str, Any]:
    try:
        cursor = h.start(req.year, req.advance_rate, req.start_index)
    except HistorianError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return {"simulated": True, "cursor": cursor}


@router.post("/historian/stop")
def historian_stop(h: SimulatedHistorian = Depends(get_historian)) -> dict[str, Any]:
    return {"simulated": True, "cursor": h.stop()}


@router.post("/historian/tick")
def historian_tick(h: SimulatedHistorian = Depends(get_historian)) -> dict[str, Any]:
    try:
        return {"simulated": True, "cursor": h.tick()}
    except HistorianError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.get("/historian/latest")
def historian_latest(n: int = Query(60, ge=1, le=2000), h: SimulatedHistorian = Depends(get_historian)) -> dict[str, Any]:
    return h.latest(n)


@router.get("/historian/tags")
def historian_tags(h: SimulatedHistorian = Depends(get_historian)) -> dict[str, Any]:
    return {"simulated": True, "source": h.describe(), "tags": h.tags()}


# --- CMMS / notifications ----------------------------------------------------------------------
@router.get("/cmms/drafts")
def cmms_drafts(c: SimulatedCmms = Depends(get_cmms)) -> dict[str, Any]:
    return {"simulated": True, "submit_supported": False, "drafts": c.drafts()}


@router.post("/cmms/drafts")
def cmms_create_draft(req: DraftRequest, c: SimulatedCmms = Depends(get_cmms)) -> dict[str, Any]:
    return {"simulated": True, **c.draft_work_order(req.model_dump())}


@router.get("/notifications/outbox")
def notifications_outbox(limit: int = Query(100, ge=1, le=500),
                         n: SimulatedNotifier = Depends(get_notifier)) -> dict[str, Any]:
    return {"simulated": True, "delivery": "in_app_simulated", "notifications": n.outbox(limit)}


@router.post("/notifications/send")
def notifications_send(req: NotifyRequest, n: SimulatedNotifier = Depends(get_notifier)) -> dict[str, Any]:
    from app.plant.personas import PERSONAS

    if req.persona not in PERSONAS:
        raise HTTPException(status_code=422, detail=f"unknown persona '{req.persona}' (expected one of "
                                                    f"{', '.join(PERSONAS)})")
    return n.notify(req.persona, req.message)
