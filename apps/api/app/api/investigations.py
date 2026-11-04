"""Investigation endpoints: synchronous pipeline, retrieval, evidence, review, export."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Response
from fastapi.concurrency import run_in_threadpool

from app import services
from app.schemas import (
    Evidence,
    Investigation,
    InvestigationCreated,
    InvestigationRequest,
    ReviewRecord,
    ReviewRequest,
)

router = APIRouter(prefix="/investigations", tags=["investigations"])
log = logging.getLogger("thermomind.api.investigations")


@router.post("", response_model=InvestigationCreated)
async def create_investigation(req: InvestigationRequest) -> InvestigationCreated:
    """Runs the whole pipeline synchronously (the Meta call is blocking, hence the threadpool)."""
    inv = await run_in_threadpool(services.run_investigation_pipeline, req)
    return InvestigationCreated(case_id=inv.case_id, status=inv.status)


@router.get("", response_model=list[Investigation])
def list_investigations() -> list[Investigation]:
    return services.get_store().list()


@router.get("/{case_id}", response_model=Investigation)
def get_investigation(case_id: str) -> Investigation:
    return services.get_store().get(case_id)  # KeyError -> 404


@router.get("/{case_id}/evidence", response_model=list[Evidence])
def list_evidence(case_id: str) -> list[Evidence]:
    return services.get_store().get(case_id).evidence


@router.get("/{case_id}/evidence/{evidence_id}", response_model=Evidence)
def get_evidence(case_id: str, evidence_id: str) -> Evidence:
    inv = services.get_store().get(case_id)
    for ev in inv.evidence:
        if ev.evidence_id == evidence_id:
            return ev
    raise HTTPException(status_code=404, detail=f"evidence '{evidence_id}' not found in case '{case_id}'")


@router.post("/{case_id}/review", response_model=Investigation)
def review_investigation(case_id: str, body: ReviewRequest) -> Investigation:
    """Records a human review decision. Never touches dataset rows, evidence or the report."""
    record = ReviewRecord(
        decision=body.decision,
        reviewer=(body.reviewer or "demo-engineer").strip()[:120] or "demo-engineer",
        comment=(body.comment.strip()[:4000] if body.comment else None),
        ts_utc=services.now_utc(),
    )
    inv = services.get_store().set_review(case_id, record)  # KeyError -> 404
    log.info("case %s reviewed: %s by %s", case_id, record.decision, record.reviewer)
    return inv


@router.get("/{case_id}/export.json")
def export_investigation(case_id: str) -> Response:
    inv = services.get_store().get(case_id)
    return Response(
        content=inv.model_dump_json(indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{case_id}.json"'},
    )
