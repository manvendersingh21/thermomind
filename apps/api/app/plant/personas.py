"""Demo personas (fake accounts, no authentication) and the hypothesis -> persona routing table."""
from __future__ import annotations

from typing import Optional

from app.plant.schemas import Persona

DEFAULT_PERSONA = "reliability_engineer"

PERSONAS: dict[str, Persona] = {p.persona_id: p for p in [
    Persona(persona_id="reliability_engineer", name="Demo Reliability Engineer", role="Reliability engineer",
            subsystems=["compressor", "combustion_turbine", "generator_output"],
            description="Owns operating-condition questions and anything the rules cannot attribute; "
                        "default reviewer of investigations."),
    Persona(persona_id="intake_technician", name="Demo Intake Technician", role="Air-intake / filter-house technician",
            subsystems=["intake"],
            description="Owns air-intake and filter-house checks (AFDP, inlet conditions)."),
    Persona(persona_id="instrumentation_technician", name="Demo Instrumentation Technician",
            role="Instrumentation & control technician (read-only checks)",
            subsystems=["exhaust_emissions", "instrumentation"],
            description="Owns transmitter / sensor validity checks and emissions instrumentation."),
    Persona(persona_id="plant_manager", name="Demo Plant Manager", role="Plant manager",
            subsystems=[],
            description="Receives an info notification for every urgent_review case; no technical tasks."),
]}

# hypothesis_key -> persona_id. Adding a hypothesis/persona is one entry here (n+1).
ROUTING_TABLE: dict[str, str] = {
    "intake_restriction": "intake_technician",
    "sensor_issue": "instrumentation_technician",
    "operating_condition": "reliability_engineer",
    "unknown": "reliability_engineer",
}
URGENT_ALSO_NOTIFY = ["plant_manager"]


def route(hypothesis_key: Optional[str]) -> str:
    """Rule-based routing; unknown/unmapped keys go to the default reliability engineer."""
    return ROUTING_TABLE.get(hypothesis_key or "unknown", DEFAULT_PERSONA)


def resolve_persona(value: Optional[str]) -> Persona:
    """Raises KeyError (API -> 404) for unknown persona ids; None/empty -> default."""
    pid = (value or "").strip() or DEFAULT_PERSONA
    if pid not in PERSONAS:
        raise KeyError(f"unknown persona '{pid}' (expected one of {', '.join(PERSONAS)})")
    return PERSONAS[pid]
