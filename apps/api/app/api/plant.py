"""Plant-ops endpoints: demo personas, simulated in-app inbox / work requests, "Ask the plant" what-if
console, reviewed precedents. Read-only decision support; no email/SMS/paging, no control actions."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, Query
from fastapi.concurrency import run_in_threadpool

from app import config, services
from app.plant import store, whatif, work_requests
from app.plant.memory import recall_similar
from app.plant.personas import DEFAULT_PERSONA, ESCALATION_RULES, PERSONAS, ROUTING_TABLE, resolve_persona
from app.plant.schemas import (InboxResponse, Notification, PersonasResponse, PrecedentsResponse,
                               StatusUpdateRequest, Subsystem, WhatIfRequest, WhatIfSession, WorkRequest)
from app.plant.sensitivity import measurement_info, resolve_base, simulate_change
from app.plant.subsystems import list_subsystems

router = APIRouter(prefix="/plant", tags=["plant"])


def _persona(query: Optional[str], header: Optional[str]) -> str:
    return resolve_persona(query or header).persona_id  # KeyError -> 404


def _client():
    """Meta client for the what-if agents (None when no key is configured -> offline)."""
    if not config.meta_configured():
        return None
    try:
        c = services.get_meta_client()
        return c if c.configured else None
    except Exception:  # noqa: BLE001
        return None


@router.get("/personas", response_model=PersonasResponse)
def personas() -> PersonasResponse:
    return PersonasResponse(personas=list(PERSONAS.values()), default_persona=DEFAULT_PERSONA,
                            routing_table=ROUTING_TABLE, escalation_rules=ESCALATION_RULES)


@router.get("/subsystems", response_model=list[Subsystem])
def subsystems() -> list[Subsystem]:
    return list_subsystems()


@router.get("/measurements")
def measurements(case_id: Optional[str] = None) -> list[dict]:
    return measurement_info(resolve_base(case_id).dataset_id)


@router.get("/inbox", response_model=InboxResponse)
def inbox(persona: Optional[str] = None, x_persona: Optional[str] = Header(default=None)) -> InboxResponse:
    p = resolve_persona(persona or x_persona)
    notes = store.list_notifications(p.persona_id)
    wrs = store.list_work_requests(persona=p.persona_id)
    # supervisors / cc also see the work requests they were notified about
    seen = {w.id for w in wrs}
    for w in store.list_work_requests():
        if w.id not in seen and p.persona_id in w.notified_personas:
            wrs.append(w)
    wrs.sort(key=lambda w: w.created_at_utc, reverse=True)
    return InboxResponse(persona=p, notifications=notes, work_requests=wrs,
                         unread_count=sum(1 for n in notes if not n.read),
                         open_count=sum(1 for w in wrs if w.status in ("open", "acknowledged")
                                        and w.assigned_persona == p.persona_id))


@router.post("/notifications/{notification_id}/read", response_model=Notification)
def read_notification(notification_id: str) -> Notification:
    return work_requests.mark_read(notification_id)


@router.get("/work-requests", response_model=list[WorkRequest])
def list_work_requests(persona: Optional[str] = None, status: Optional[str] = None,
                       case_id: Optional[str] = None) -> list[WorkRequest]:
    if persona:
        resolve_persona(persona)
    return store.list_work_requests(persona=persona, status=status, case_id=case_id)


@router.post("/work-requests/{wr_id}/status", response_model=WorkRequest)
def set_status(wr_id: str, body: StatusUpdateRequest, persona: Optional[str] = None,
               x_persona: Optional[str] = Header(default=None)) -> WorkRequest:
    return work_requests.update_status(wr_id, body.status, body.comment, _persona(persona, x_persona))


@router.get("/sensitivity")
def sensitivity(measurement: str, delta: float, case_id: Optional[str] = None) -> dict:
    return simulate_change(measurement, delta, resolve_base(case_id))


@router.post("/whatif", response_model=WhatIfSession)
async def create_whatif(req: WhatIfRequest, wait: bool = Query(default=False), persona: Optional[str] = None,
                        x_persona: Optional[str] = Header(default=None)) -> WhatIfSession:
    """Starts the multi-agent what-if. Default: returns at once with status "running" (poll GET
    /plant/whatif/{id}); ``?wait=true`` blocks until done (scripts/tests)."""
    client = _client()
    return await run_in_threadpool(whatif.run_whatif, req, client, persona or x_persona, not wait)


@router.get("/whatif", response_model=list[WhatIfSession])
def list_whatif(limit: int = Query(default=20, ge=1, le=100)) -> list[WhatIfSession]:
    return store.list_sessions(limit)


@router.get("/whatif/{session_id}", response_model=WhatIfSession)
def get_whatif(session_id: str) -> WhatIfSession:
    return whatif.get_session(session_id)


@router.get("/precedents", response_model=PrecedentsResponse)
def precedents(case_id: str, k: int = Query(default=3, ge=1, le=10)) -> PrecedentsResponse:
    return recall_similar(case_id=case_id, k=k)
