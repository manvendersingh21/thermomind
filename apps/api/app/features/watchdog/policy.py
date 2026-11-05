"""Autonomy routing for watchdog proposals — honest by construction.

Only ONE action class may ever execute automatically, and only inside the SIMULATED auxiliaries model:
``simulated_auxiliary_switchover`` (reversible, low risk). Everything else is ``human_required``: it is recorded and
the responsible persona plus their supervisor are notified (simulated in-app). ThermoMind has no write path to any
real plant, so "execute" below always means "change the in-memory simulation".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

HONESTY_STATEMENT = ("Auto-execution exists only inside the simulated auxiliaries model. "
                     "ThermoMind has no write path to any real plant.")
EXECUTION_WHERE = "SIMULATED auxiliaries subsystem"
OPERATOR = "control_room_operator"
SUPERVISOR = "shift_supervisor"


@dataclass(frozen=True)
class ActionClass:
    key: str
    description: str
    reversible: bool
    risk: str
    auto_executable_in_simulator: bool
    policy_id: str
    responsible: tuple[str, ...]
    where: str


ACTION_CLASSES: dict[str, ActionClass] = {a.key: a for a in [
    ActionClass("simulated_auxiliary_switchover",
                "Duty moves to the standby auxiliary and the duty auxiliary is released — inside the SIMULATED "
                "auxiliaries model only (2 × 100 % pump pairs).",
                True, "low", True, "WD-POL-001", ("mechanical_maintenance_engineer",), EXECUTION_WHERE),
    ActionClass("auxiliary_maintenance",
                "Field inspection / maintenance work on an auxiliary without a standby (fans, lube-oil pump), or any "
                "work order. People do this through plant procedures (permit, isolation).",
                False, "medium", False, "WD-POL-010", ("mechanical_maintenance_engineer", "hse_officer"),
                "real plant (human only)"),
    ActionClass("unit_commitment",
                "Second-unit commitment for +X MWh per hourly sample. Grid/dispatch decision (human only).",
                False, "high", False, "WD-POL-020", ("electrical_engineer", "plant_manager"),
                "real plant / dispatch (human only)"),
    ActionClass("redispatch_request",
                "Re-dispatch question for the TSO / dispatcher (dispatch target vs available output; human only).",
                False, "high", False, "WD-POL-021", ("electrical_engineer", "plant_manager"),
                "dispatch / TSO (human only)"),
    ActionClass("investigation_request",
                "Open an engineering investigation into a measurement departing from the baseline model expectation.",
                True, "low", False, "WD-POL-030", ("performance_engineer", "reliability_engineer"),
                "ThermoMind investigation (human review)"),
    ActionClass("real_plant_action",
                "Anything that would act on a real plant system. ThermoMind has no write path: never executed.",
                False, "high", False, "WD-POL-099", ("shift_supervisor",), "real plant (human only)"),
]}

AUTO_RECOMMENDATION = "proceed_with_conditions"
RECOMMENDATIONS = ("proceed_with_conditions", "hold_for_human", "do_not_proceed")


@dataclass
class PolicyConfig:
    auto_execute_simulated_switchover: bool = True


@dataclass
class Routing:
    route: str  # "auto_execute_simulated" | "human_required"
    policy_id: str
    reason: str
    notify: list[str]


def action_class(key: Optional[str]) -> ActionClass:
    return ACTION_CLASSES.get(key or "", ACTION_CLASSES["real_plant_action"])


def decide(action_class_key: str, recommendation: Optional[str], cfg: PolicyConfig) -> Routing:
    """Pure routing rule.

    auto_execute_simulated iff ALL hold:
      1. class == simulated_auxiliary_switchover (auto_executable_in_simulator), AND
      2. deliberation recommendation == proceed_with_conditions, AND
      3. the policy toggle 'auto-execute low-risk switchovers in simulator' is on.
    Otherwise human_required (responsible personas + operator + supervisor are notified)."""
    ac = action_class(action_class_key)
    notify = list(dict.fromkeys([*ac.responsible, OPERATOR, SUPERVISOR]))
    if not ac.auto_executable_in_simulator:
        return Routing("human_required", ac.policy_id,
                       f"class '{ac.key}' is never auto-executed ({ac.where}); human decision required", notify)
    if recommendation != AUTO_RECOMMENDATION:
        return Routing("human_required", "WD-POL-002",
                       f"deliberation recommendation is '{recommendation}', not '{AUTO_RECOMMENDATION}'", notify)
    if not cfg.auto_execute_simulated_switchover:
        return Routing("human_required", "WD-POL-002",
                       "policy toggle 'auto-execute low-risk switchovers in simulator' is off", notify)
    return Routing("auto_execute_simulated", ac.policy_id,
                   "reversible low-risk switchover, recommendation proceed_with_conditions, policy toggle on — "
                   f"executed in the {EXECUTION_WHERE} only", [OPERATOR, SUPERVISOR, *ac.responsible])


def policy_table(cfg: PolicyConfig) -> list[dict[str, Any]]:
    out = []
    for ac in ACTION_CLASSES.values():
        auto = ac.auto_executable_in_simulator and cfg.auto_execute_simulated_switchover
        out.append({
            "action_class": ac.key, "policy_id": ac.policy_id, "description": ac.description,
            "reversible": ac.reversible, "risk": ac.risk, "where": ac.where,
            "route": ("auto-execute in simulator when recommendation is proceed_with_conditions" if auto
                      else "human_required (record + notify; never executed by ThermoMind)"),
            "responsible": list(ac.responsible),
        })
    return out
