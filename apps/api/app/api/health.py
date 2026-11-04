"""GET /api/health — never includes the API key."""
from __future__ import annotations

from fastapi import APIRouter

from app import config, services
from app.schemas import Health

router = APIRouter(tags=["health"])


@router.get("/health", response_model=Health)
def health() -> Health:
    data_ok = services.data_ready()
    model_ok = services.get_model(recheck=True) is not None
    return Health(
        status="ok" if data_ok else "degraded",
        version=config.APP_VERSION,
        build=config.BUILD,
        data_ready=data_ok,
        model_ready=model_ok,
        meta_configured=config.meta_configured(),
        meta_model=config.META_MODEL,
        meta_base_url=config.META_BASE_URL,
    )
