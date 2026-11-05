"""FastAPI router for "Propose an action" (prefix ``/deliberation``; main.py mounts it under ``/api``).

Advisory only: every endpoint reads data, runs software agents or records a human decision. Nothing here writes
to any plant system or issues any command.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.routing import APIRoute
from pydantic import ValidationError as PydanticValidationError

from app import config, services
from app.features.deliberation import decisions, deliberate
from app.features.deliberation.intents import list_intents
from app.features.deliberation.schemas import DecisionRequest, DeliberationSession, IntentInfo, ProposeRequest


class _Route(APIRoute):
    """KeyError -> 404, ValueError/IndexError -> 422 (or the error's status_code, e.g. 409), busy -> 429."""

    def get_route_handler(self) -> Callable[[Request], Any]:
        handler = super().get_route_handler()

        async def _safe(request: Request) -> Response:
            try:
                return await handler(request)
            except deliberate.DeliberationBusy as exc:
                raise HTTPException(status_code=429, detail=str(exc) or deliberate.BUSY_DETAIL) from None
            except PydanticValidationError:
                raise
            except KeyError as exc:
                detail = exc.args[0] if exc.args and isinstance(exc.args[0], str) else "not found"
                raise HTTPException(status_code=404, detail=str(detail)[:500]) from None
            except (ValueError, IndexError) as exc:
                status = getattr(exc, "status_code", None)
                raise HTTPException(status_code=status if isinstance(status, int) else 422,
                                    detail=str(exc)[:500] or "invalid input") from None

        return _safe


router = APIRouter(prefix="/deliberation", tags=["deliberation"], route_class=_Route)


def _client():
    """Meta client (None when no key is configured -> offline deterministic deliberation)."""
    if not config.meta_configured():
        return None
    try:
        c = services.get_meta_client()
        return c if c.configured else None
    except Exception:  # noqa: BLE001
        return None


@router.get("/intents", response_model=list[IntentInfo])
def intents() -> list[IntentInfo]:
    return list_intents()


@router.post("/propose", response_model=DeliberationSession)
async def propose(req: ProposeRequest, wait: bool = Query(default=False), persona: Optional[str] = None,
                  x_persona: Optional[str] = Header(default=None)) -> DeliberationSession:
    """Starts a deliberation in a background thread (poll GET /deliberation/{id}); ``?wait=true`` blocks."""
    return await run_in_threadpool(deliberate.propose, req, _client(), persona or x_persona, not wait)


@router.get("", response_model=list[DeliberationSession])
def list_deliberations(case_id: Optional[str] = None,
                       limit: int = Query(default=20, ge=1, le=100)) -> list[DeliberationSession]:
    return deliberate.list_sessions(case_id, limit)


@router.get("/{deliberation_id}", response_model=DeliberationSession)
def get_deliberation(deliberation_id: str) -> DeliberationSession:
    return deliberate.get_session(deliberation_id)


@router.post("/{deliberation_id}/decision", response_model=DeliberationSession)
def decide(deliberation_id: str, req: DecisionRequest, persona: Optional[str] = None,
           x_persona: Optional[str] = Header(default=None)) -> DeliberationSession:
    return decisions.record_decision(deliberation_id, req, persona or x_persona)
