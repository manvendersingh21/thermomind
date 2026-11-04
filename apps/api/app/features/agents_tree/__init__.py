"""Agent organisation tree (read-only): how ThermoMind's agents are organised, what each may do, live stats.

``from app.features.agents_tree import router`` yields the *module* ``router`` (it holds the APIRouter as
``router.router``, prefix ``/agents``; main.py mounts it under ``/api``).
"""
from app.features.agents_tree import registry, router  # noqa: F401
