"""FastAPI router for the simulated plant (prefix ``/simulator``; main.py mounts it under ``/api``).

Every action here acts on the in-process software model only (SIMULATED_PLANT). Nothing is written to a
real plant, PLC, DCS or historian.
"""
from __future__ import annotations

import asyncio
import json
import math
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app import services
from app.data.repository import DatasetBundle
from app.schemas import MEASUREMENT_KEYS
from app.simulator import calibration as cal
from app.simulator.engine import BUFFER_MAX, SimError, get_engine

router = APIRouter(prefix="/simulator", tags=["simulator"])

SIM_SOURCE = "SIMULATED_PLANT"
SIM_WARNINGS = ["simulated physics model; synthetic faults may be present"]
Channel = Literal["AT", "AP", "AH", "AFDP", "GTEP", "TIT", "TAT", "TEY", "CDP", "CO", "NOX"]
FaultKind = Literal["intake_fouling", "compressor_fouling", "hot_day",
                    "sensor_bias", "sensor_drift", "sensor_spike", "sensor_stuck"]


class RunRequest(BaseModel):
    action: Literal["start", "pause", "resume", "stop", "reset", "speed"]
    year: Optional[int] = Field(default=None, ge=2011, le=2015)
    start_index: Optional[int] = Field(default=None, ge=0)
    speed: Optional[float] = Field(default=None, gt=0, le=1000)
    rows_per_hour: Optional[int] = Field(default=None, ge=1, le=3600)


class FaultRequest(BaseModel):
    kind: FaultKind
    magnitude: float
    channel: Optional[Channel] = None

    @field_validator("magnitude")
    @classmethod
    def _finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("magnitude must be finite")
        return v


class RegisterRequest(BaseModel):
    last_n: int = Field(ge=24, le=BUFFER_MAX)


@router.post("/run")
def run(req: RunRequest) -> dict:
    """Control the SIMULATED plant's replay (software model only)."""
    try:
        return get_engine().action(req.action, req.year, req.start_index, req.speed, req.rows_per_hour)
    except SimError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None




def _flat(rec: dict | None) -> dict | None:
    """UI-shaped StepRecord: channels flattened to top level + internal block (keeps every original field)."""
    if not rec:
        return None
    out = dict(rec)
    out.update(rec.get("channels") or {})
    out["t_s"] = rec.get("sim_time_s")
    out["internal"] = {
        "mass_flow_kg_s": rec.get("air_kg_s"),
        "fuel_kg_s": rec.get("fuel_kg_s"),
        "shaft_mw": rec.get("dispatch_setpoint_mw"),
        "freq_hz": (rec.get("omega_pu") or 1.0) * 50.0,
        "available_capacity_mw": rec.get("available_capacity_mw"),
    }
    out["active_faults"] = rec.get("active_fault_ids") or []
    return out


@router.get("/state")
def state() -> dict:
    st = get_engine().state()
    st["record"] = _flat(st.get("last"))
    return st


@router.get("/history")
def history(n: int = Query(default=600, ge=1, le=BUFFER_MAX)) -> dict:
    recs = [_flat(r) for r in get_engine().history(n)]
    return {"n": len(recs), "records": recs, "simulated": True, "source": SIM_SOURCE}


@router.get("/stream")
async def stream(max_events: int = Query(default=0, ge=0, le=100_000), hz: float = Query(default=4.0, gt=0, le=4.0)):
    """Server-sent events with the latest StepRecord, at most 4 Hz. ``max_events`` > 0 ends the stream."""
    eng = get_engine()

    async def gen():
        sent = 0
        last_step = -1
        while True:
            st = eng.state()
            if st["steps"] != last_step or sent == 0:
                last_step = st["steps"]
                payload = {"status": st["status"], "record": _flat(st.get("last")), "simulated": True}
                yield f"data: {json.dumps(payload)}\n\n"
                sent += 1
                if max_events and sent >= max_events:
                    return
            await asyncio.sleep(1.0 / hz)

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/faults")
def add_fault(req: FaultRequest) -> dict:
    try:
        return get_engine().add_fault(req.kind, req.magnitude, req.channel)
    except SimError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.delete("/faults/{fault_id}")
def delete_fault(fault_id: str) -> dict:
    if not get_engine().remove_fault(fault_id):
        raise HTTPException(status_code=404, detail=f"fault '{fault_id}' not found")
    return {"deleted": fault_id}


def build_bundle(records: list[dict]) -> DatasetBundle:
    """Buffer records -> DatasetBundle (row_index = 0-based position in the simulated window; no timestamps)."""
    rows = []
    for i, r in enumerate(records):
        row = {"source_year": int(r["source_year"]), "row_index": i}
        row.update({k: float(r["channels"][k]) for k in MEASUREMENT_KEYS})
        rows.append(row)
    frame = pd.DataFrame(rows, columns=["source_year", "row_index", *MEASUREMENT_KEYS])
    return DatasetBundle(
        dataset_id="ds_sim_" + uuid.uuid4().hex[:12],
        frame=frame,
        source=SIM_SOURCE,
        source_files=[],
        warnings=list(SIM_WARNINGS),
        created_at_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        has_timestamps=False,
    )


@router.post("/register-window")
def register_window(req: RegisterRequest) -> dict:
    """Register the last N simulated records as a dataset so investigations can run on it."""
    recs = get_engine().history(req.last_n)
    if len(recs) < req.last_n:
        raise HTTPException(status_code=422, detail=f"buffer holds only {len(recs)} records (asked for {req.last_n})")
    years = {r["source_year"] for r in recs}
    if len(years) != 1:
        raise HTTPException(status_code=422, detail="window spans more than one replay year")
    bundle = services.get_repo().register(build_bundle(recs))
    return {
        "dataset_id": bundle.dataset_id,
        "source": bundle.source,
        "rows": int(len(bundle.frame)),
        "year": next(iter(years)),
        "synthetic_records": int(sum(1 for r in recs if r["synthetic"])),
        "warnings": bundle.warnings,
        "row_index_note": "row_index is the position within this simulated window (1 simulated second per row)",
    }


@router.get("/calibration")
def calibration() -> dict:
    _, report = cal.get_calibration()
    return report
