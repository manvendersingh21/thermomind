"""FastAPI router for the watchdog (prefix ``/watchdog``; main.py mounts it under ``/api``).

Every control here acts on the SIMULATED auxiliaries model and the monitor only. ThermoMind has no write path to
any real plant.
"""
from __future__ import annotations

import json
import math
import time
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.features.watchdog import monitor
from app.features.watchdog.auxiliaries import FAULT_KINDS, SPEC_BY_ID
from app.features.watchdog.policy import HONESTY_STATEMENT

router = APIRouter(prefix="/watchdog", tags=["watchdog"])

Action = Literal["start", "stop", "reset", "step", "inject_fault", "clear_fault", "demand_step", "set_policy",
                 "tag_out", "decide"]


class RunRequest(BaseModel):
    action: Action
    speed: Optional[float] = Field(None, gt=0, le=monitor.MAX_SPEED, description="simulated seconds per real second")
    source: Optional[Literal["auto", "replay", "simulator", "nominal"]] = None
    year: Optional[int] = Field(None, ge=2011, le=2015)
    start_index: Optional[int] = Field(None, ge=0, le=20000)
    seed: Optional[int] = Field(None, ge=0, le=2**31 - 1)
    steps: Optional[int] = Field(None, ge=1, le=36000)
    asset: Optional[str] = Field(None, max_length=16)
    fault: Optional[str] = Field(None, max_length=40)
    rate_per_min: float = Field(0.05, ge=0, le=1)
    initial_severity: float = Field(0.0, ge=0, le=1)
    mwh: Optional[float] = Field(None, ge=-200, le=200, description="dispatch step, MWh per hourly sample")
    auto_execute: Optional[bool] = None
    deliberation_backend: Optional[Literal["auto", "builtin", "shared"]] = None
    tagged: Optional[bool] = None
    task_id: Optional[str] = Field(None, max_length=40)
    decision: Optional[Literal["approve", "reject"]] = None
    persona: Optional[str] = Field(None, max_length=60)
    comment: Optional[str] = Field(None, max_length=1000)


def _need(cond: bool, msg: str) -> None:
    if not cond:
        raise HTTPException(status_code=422, detail=msg)


def _asset(req: RunRequest) -> str:
    _need(req.asset is not None, f"'{req.action}' requires 'asset'")
    _need(req.asset in SPEC_BY_ID, f"unknown asset '{req.asset}' (expected one of {', '.join(SPEC_BY_ID)})")
    return req.asset  # type: ignore[return-value]


@router.post("/run")
def run(req: RunRequest) -> dict:
    """Control the SIMULATED auxiliaries + monitor: start | stop | reset | step | inject_fault | clear_fault |
    demand_step | set_policy | tag_out | decide."""
    w = monitor.get_watchdog()
    a = req.action
    result: dict = {}
    if a == "start":
        if req.source is not None or req.year is not None or req.start_index is not None or req.seed is not None:
            w.reset(req.source, req.year, req.start_index, req.seed)
        w.start(req.speed)
    elif a == "stop":
        result["stopped_cleanly"] = w.stop()
    elif a == "reset":
        w.reset(req.source, req.year, req.start_index, req.seed)
    elif a == "step":
        _need(not w.running, "stop the background simulation before stepping manually")
        w.step_n(req.steps or 1)
    elif a == "inject_fault":
        asset = _asset(req)
        _need(req.fault in FAULT_KINDS, f"'fault' must be one of {', '.join(FAULT_KINDS)}")
        try:
            result["fault"] = w.inject_fault(asset, req.fault, req.rate_per_min, req.seed or 11, req.initial_severity)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
    elif a == "clear_fault":
        w.clear_fault(_asset(req))
    elif a == "demand_step":
        _need(req.mwh is not None and math.isfinite(req.mwh), "'demand_step' requires a finite 'mwh'")
        w.set_demand_step(req.mwh)  # type: ignore[arg-type]
    elif a == "set_policy":
        _need(req.auto_execute is not None or req.deliberation_backend is not None,
              "'set_policy' requires 'auto_execute' (bool) and/or 'deliberation_backend' (auto | builtin | shared)")
        w.set_policy(req.auto_execute, req.deliberation_backend)
    elif a == "tag_out":
        asset = _asset(req)
        _need(req.tagged is not None, "'tag_out' requires 'tagged' (bool)")
        try:
            w.tag_out(asset, bool(req.tagged))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
    elif a == "decide":
        _need(bool(req.task_id), "'decide' requires 'task_id'")
        _need(req.decision is not None, "'decide' requires 'decision' (approve | reject)")
        persona = (req.persona or "shift_supervisor").strip()
        try:
            from app.plant.personas import PERSONAS
            _need(persona in PERSONAS, f"unknown persona '{persona}'")
        except ImportError:
            pass
        try:
            result["task"] = w.decide(req.task_id, req.decision, persona, req.comment)  # type: ignore[arg-type]
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc.args[0])) from None
        except ValueError as exc:
            raise HTTPException(status_code=getattr(exc, "status_code", 422), detail=str(exc)) from None
    return {"ok": True, "action": a, **result, "running": w.running, "sim_time_s": w.aux.t_s,
            "honesty_statement": HONESTY_STATEMENT}


@router.get("/state")
def state(history_points: int = Query(60, ge=2, le=600), n_events: int = Query(60, ge=1, le=500)) -> dict:
    return monitor.get_watchdog().state(history_points, n_events)


@router.get("/events")
def events(n: int = Query(100, ge=1, le=monitor.BUF["events"]), since_seq: int = Query(0, ge=0)) -> dict:
    w = monitor.get_watchdog()
    return {"events": w.events_since(n, since_seq), "last_seq": w.seq, "honesty_statement": HONESTY_STATEMENT}


@router.get("/stream")
def stream(interval_s: float = Query(1.0, ge=0.5, le=10.0), max_events: int = Query(1200, ge=1, le=7200)):
    """Server-sent events: one compact state snapshot per ``interval_s`` (≤ 2 Hz). Clients may fall back to polling
    GET /state."""
    w = monitor.get_watchdog()

    def gen():
        for i in range(max_events):
            payload = json.dumps(w.stream_snapshot(), default=str, allow_nan=False)
            yield f"id: {i}\nevent: state\ndata: {payload}\n\n"
            if i + 1 < max_events:
                time.sleep(interval_s)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
