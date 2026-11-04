"""Executive view: CEO-level aggregation of what ThermoMind measures, plus an AI-drafted executive brief.

``router`` is exported as a MODULE (main.py resolves ``.router``); prefix ``/executive`` -> ``/api/executive/...``.
Read-only: this package only writes its own ``executive_briefs`` table.
"""
from app.features.executive import router  # noqa: F401
