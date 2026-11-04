"""Maintenance planner: compressor-wash and inlet-filter change-out break-even from real UCI data.

Wire in main.py with ``from app.features.planner import router as planner_router`` and
``app.include_router(planner_router, prefix="/api")`` → ``/api/planner/{options,compressor-wash,filter-changeout}``.
"""
from app.features.planner.router import router

__all__ = ["router"]
