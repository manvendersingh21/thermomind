"""Subsystem registry for the "Ask the plant" agents.

n+1: adding a plant area agent is appending one entry here (key, measurements, description, owner).
Each entry becomes one parallel Muse Spark agent in ``whatif.run_whatif``.
"""
from __future__ import annotations

from app.plant.schemas import Subsystem

SUBSYSTEM_REGISTRY: list[dict] = [
    {"key": "intake", "how_it_works": "Ambient air is drawn through the filter house; AFDP is the pressure drop across the filter elements, which rises as the filters load. AT/AH/AP describe the air entering, which sets air density and therefore mass flow.", "name": "Air intake & filter house", "measurements": ["AFDP", "AT", "AH", "AP"],
     "description": "Inlet air path: filter differential pressure and ambient conditions at the intake.",
     "owner_persona": "mechanical_maintenance_engineer"},
    {"key": "compressor", "how_it_works": "The axial compressor raises the pressure of the filtered air before combustion; CDP is its discharge pressure and depends on inlet conditions and load.", "name": "Compressor", "measurements": ["CDP", "AFDP"],
     "description": "Axial compressor: discharge pressure (CDP, unit as published / under validation).",
     "owner_persona": "mechanical_maintenance_engineer"},
    {"key": "combustion_turbine", "how_it_works": "Fuel burns in the compressed air and the hot gas expands through the turbine; TIT and TAT are the gas temperatures before and after the turbine, and their balance relates to how much energy is extracted (TEY).", "name": "Combustion & turbine section", "measurements": ["TIT", "TAT", "TEY"],
     "description": "Turbine inlet / after temperatures and the resulting energy yield.",
     "owner_persona": "reliability_engineer"},
    {"key": "exhaust_emissions", "how_it_works": "Exhaust gas leaves the turbine at GTEP back-pressure; CO and NOx are measured emissions that depend on combustion temperature and load.", "name": "Exhaust & emissions", "measurements": ["GTEP", "CO", "NOX"],
     "description": "Exhaust pressure and measured CO / NOx emissions.",
     "owner_persona": "environmental_engineer"},
    {"key": "generator_output", "how_it_works": "The turbine shaft drives the generator; TEY is the energy yield (MWh as published) and is the quantity the baseline model predicts from the other measurements.", "name": "Generator output", "measurements": ["TEY"],
     "description": "Turbine energy yield (TEY, MWh as published) delivered to the generator.",
     "owner_persona": "electrical_engineer"},
]


def list_subsystems() -> list[Subsystem]:
    return [Subsystem(**s) for s in SUBSYSTEM_REGISTRY]


def registry_entry(key: str) -> dict:
    return next((s for s in SUBSYSTEM_REGISTRY if s["key"] == key), {})


def get_subsystem(key: str) -> Subsystem:
    for s in SUBSYSTEM_REGISTRY:
        if s["key"] == key:
            return Subsystem(**s)
    raise KeyError(f"unknown subsystem '{key}'")
