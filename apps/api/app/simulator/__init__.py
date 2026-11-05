"""SIMULATED gas-turbine plant (0-D physics, RK4) driven by replayed real UCI ambient + dispatch inputs.

Software model only: no endpoint touches a real plant. Synthetic faults are labelled ``synthetic: true``.
"""
from app.simulator.router import router

__all__ = ["router"]
