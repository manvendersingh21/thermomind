"""Thermal monitoring of the electrical balance of plant (generator, generator breaker, step-up transformer,
HV switchgear, busbar) from a SIMULATED thermal feed derived from real load (TEY) and ambient (AT) data.
Read-only decision support: advisories only, no control actions.

The FastAPI router lives in ``app.features.thermal.router`` (attribute ``router``, prefix ``/thermal``).
"""
