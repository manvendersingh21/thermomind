"""Subsystem registry for the "Ask the plant" agents.

n+1: adding a plant area agent is appending one entry here (key, measurements, description, owner).
Each entry becomes one parallel Muse Spark agent in ``whatif.run_whatif``.
"""
from __future__ import annotations

from app.plant.schemas import Subsystem

SUBSYSTEM_REGISTRY: list[dict] = [
    {"key": "intake", "name": "Air intake & filter house", "measurements": ["AFDP", "AT", "AH", "AP"],
     "description": "Inlet air path: filter differential pressure and ambient conditions at the intake.",
     "owner_persona": "intake_technician"},
    {"key": "compressor", "name": "Compressor", "measurements": ["CDP", "AFDP"],
     "description": "Axial compressor: discharge pressure (CDP, unit as published / under validation).",
     "owner_persona": "reliability_engineer"},
    {"key": "combustion_turbine", "name": "Combustion & turbine section", "measurements": ["TIT", "TAT", "TEY"],
     "description": "Turbine inlet / after temperatures and the resulting energy yield.",
     "owner_persona": "reliability_engineer"},
    {"key": "exhaust_emissions", "name": "Exhaust & emissions", "measurements": ["GTEP", "CO", "NOX"],
     "description": "Exhaust pressure and measured CO / NOx emissions.",
     "owner_persona": "instrumentation_technician"},
    {"key": "generator_output", "name": "Generator output", "measurements": ["TEY"],
     "description": "Turbine energy yield (TEY, MWh as published) delivered to the generator.",
     "owner_persona": "reliability_engineer"},
]


def list_subsystems() -> list[Subsystem]:
    return [Subsystem(**s) for s in SUBSYSTEM_REGISTRY]


def get_subsystem(key: str) -> Subsystem:
    for s in SUBSYSTEM_REGISTRY:
        if s["key"] == key:
            return Subsystem(**s)
    raise KeyError(f"unknown subsystem '{key}'")
