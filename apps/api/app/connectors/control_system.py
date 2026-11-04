"""Control-system boundary: intentionally nothing here but a re-export.

``ControlSystem`` (see base.py) has exactly one method, ``capabilities()``. There is no
read adapter and no write adapter to simulate, and none will be added.
"""
from app.connectors.base import CONTROL_NOTE, ControlSystem

__all__ = ["CONTROL_NOTE", "ControlSystem"]
