""""Propose an action": advisory multi-agent deliberation over deterministic pre-checks.

The human decides; ThermoMind executes nothing. ``router`` is the router MODULE (``router.router`` is the
APIRouter with prefix ``/deliberation``); main.py resolves either form.
"""
from app.features.deliberation import router  # noqa: F401
