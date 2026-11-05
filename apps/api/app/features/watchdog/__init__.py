"""Watchdog: SIMULATED plant auxiliaries (pumps, fans, lube-oil pump) + a monitoring agent + honest autonomy routing.

* ``auxiliaries``  — lumped electrical / winding-thermal / bearing models of plant auxiliary motors (SIMULATED).
* ``monitor``      — detectors with explicit rules and provenance, proposals, deliberation, event log, thread.
* ``policy``       — action classes; auto-execution exists ONLY inside the simulated auxiliaries model.
* ``router``       — FastAPI router (prefix ``/watchdog``; main.py mounts it under ``/api``).

ThermoMind has no write path to any real plant. Nothing here writes to a PLC, DCS, SCADA or historian.
"""
from app.features.watchdog import router  # noqa: F401  (main.py resolves ``router.router``)
