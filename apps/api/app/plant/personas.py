"""Demo personas for a combined-cycle plant (fake accounts, no authentication) and routing rules.

Selected per request via the ``X-Persona`` header or ``?persona=``. n+1: adding a role is one entry in
``PERSONAS`` (and optionally a routing rule).
"""
from __future__ import annotations

from typing import Any, Optional

from app.plant.schemas import Persona

DEFAULT_PERSONA = "reliability_engineer"
ALL = ["AT", "AP", "AH", "AFDP", "GTEP", "TIT", "TAT", "TEY", "CDP", "CO", "NOX"]


def _p(pid: str, name: str, role: str, subsystems: list[str], watched: list[str], supervisor: Optional[str],
       description: str, external: bool = False) -> Persona:
    return Persona(persona_id=pid, name=name, role=role, subsystems=subsystems, measurements_watched=watched,
                   supervisor=supervisor, external=external, description=description)


PERSONAS: dict[str, Persona] = {p.persona_id: p for p in [
    _p("plant_manager", "Demo Plant Manager", "Plant manager", [], ["TEY"], None,
       "Escalation point for urgent_review cases; supervisor of the shift supervisor."),
    _p("shift_supervisor", "Demo Shift Supervisor", "Shift supervisor (operations manager on shift)", [], ALL,
       "plant_manager", "Supervises the control-room operator and all technicians' work on shift; approves field work."),
    _p("control_room_operator", "Demo Control-Room Operator", "Control-room operator", [], ALL, "shift_supervisor",
       "First to see alerts; read-only acknowledgement in ThermoMind (no control actions)."),
    _p("performance_engineer", "Demo Performance Engineer", "Performance engineer", ["generator_output", "intake"],
       ["AT", "AP", "AH", "TEY"], "reliability_engineer",
       "TEY residuals, heat-rate and ambient effects; owns operating-condition questions."),
    _p("reliability_engineer", "Demo Reliability Engineer", "Reliability engineer (condition monitoring)",
       ["compressor", "combustion_turbine"], ALL, "plant_manager",
       "Owns investigations; default persona; supervises maintenance / I&C technicians' investigations."),
    _p("mechanical_maintenance_engineer", "Demo Mechanical Maintenance Engineer", "Mechanical maintenance engineer",
       ["intake", "compressor", "combustion_turbine"], ["AFDP", "CDP", "TIT", "TAT"], "shift_supervisor",
       "Intake filter house, compressor and hot-gas-path inspections."),
    _p("ic_engineer", "Demo I&C Engineer", "Instrumentation & controls (I&C) engineer",
       ["instrumentation"], ["CDP", "AFDP", "TIT"], "shift_supervisor",
       "Transmitter / sensor validity: calibration checks, impulse lines, redundant-channel comparison."),
    _p("electrical_engineer", "Demo Electrical Engineer", "Electrical engineer", ["generator_output"], ["TEY"],
       "shift_supervisor", "Generator and switchyard; output side."),
    _p("environmental_engineer", "Demo Environmental Engineer", "Environmental / emissions compliance engineer",
       ["exhaust_emissions"], ["CO", "NOX", "GTEP"], "plant_manager",
       "Emissions compliance; notified when CO/NOx deviate notably."),
    _p("hse_officer", "Demo HSE Officer", "Health, safety & environment officer", [], [], "plant_manager",
       "Permits to work and isolation per procedure; notified on any work request involving field inspection."),
    _p("oem_field_service", "Demo OEM Field Service Rep", "OEM field service representative (external)",
       ["combustion_turbine"], ["TIT", "TAT"], "reliability_engineer",
       "External OEM representative; notified (simulated) for hot-gas-path / TIT / TAT findings.", external=True),
]}

# hypothesis_key -> assignee, supervisor, cc. Supervisor and cc are always notified together with the assignee.
ROUTING_TABLE: dict[str, dict[str, Any]] = {
    "intake_restriction": {"assignee": "mechanical_maintenance_engineer", "supervisor": "shift_supervisor",
                           "cc": ["reliability_engineer", "hse_officer"], "field_inspection": True},
    "sensor_issue": {"assignee": "ic_engineer", "supervisor": "shift_supervisor", "cc": ["reliability_engineer"],
                     "field_inspection": False},
    "operating_condition": {"assignee": "performance_engineer", "supervisor": "reliability_engineer", "cc": [],
                            "field_inspection": False},
    "unknown": {"assignee": "reliability_engineer", "supervisor": "shift_supervisor", "cc": [],
                "field_inspection": False},
}
URGENT_ALSO_NOTIFY = ["plant_manager"]
EMISSIONS_PERSONA = "environmental_engineer"
HOT_GAS_PATH_PERSONA = "oem_field_service"
ALWAYS_INFO = ["control_room_operator"]  # first to see alerts (read-only acknowledgement)
ESCALATION_RULES = [
    "Every work request notifies the assignee AND their supervisor (simulated in-app).",
    "severity urgent_review -> also plant_manager.",
    "notable CO/NOx deviation (|z| >= 2, real rows, window vs reference) -> also environmental_engineer.",
    "notable TIT/TAT evidence (|z| >= 2) -> also oem_field_service (external, simulated).",
    "routing that involves field inspection (intake_restriction) -> also hse_officer (permit / isolation per procedure).",
    "control_room_operator gets an info notification for every work request (first to see alerts).",
]


def route(hypothesis_key: Optional[str]) -> dict[str, Any]:
    """Rule-based routing; unmapped keys use the 'unknown' rule (reliability engineer)."""
    return ROUTING_TABLE.get(hypothesis_key or "unknown", ROUTING_TABLE["unknown"])


def resolve_persona(value: Optional[str]) -> Persona:
    """Raises KeyError (API -> 404) for unknown persona ids; None/empty -> default."""
    pid = (value or "").strip() or DEFAULT_PERSONA
    if pid not in PERSONAS:
        raise KeyError(f"unknown persona '{pid}' (expected one of {', '.join(PERSONAS)})")
    return PERSONAS[pid]


def label(pid: Optional[str]) -> str:
    p = PERSONAS.get(pid or "")
    return p.role if p else (pid or "?")
