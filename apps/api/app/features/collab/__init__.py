"""Collaboration layer (read-only): autonomy policy ("who decides what"), case activity feed, domino map,
onboarding briefs. ``app.features.collab.router`` is the router MODULE; its ``.router`` is an
``APIRouter(prefix="/collab")`` that main.py mounts under ``/api``.
"""
from app.features.collab import router  # noqa: F401

__all__ = ["router"]
