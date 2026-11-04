"""GET /agents/tree -> the agent organisation with live stats (read-only; main.py mounts under /api)."""
from __future__ import annotations

from fastapi import APIRouter

from app.features.agents_tree import registry

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("/tree")
def get_tree() -> dict:
    return registry.tree_payload()
