/**
 * "Where to look" logic for the 3D twin: maps the rank-1 hypothesis, thermal flags and emissions
 * excursions to plant equipment. Pure functions (no React / three) so they can be unit-tested.
 * Read-only decision support: wording describes what to inspect, never how to operate.
 */
import type { Evidence, Hypothesis, Investigation } from "../../api/types";
import { guideFor } from "../../lib/subsystems";
import type { EmissionsResponse } from "../emissions/types";
import type { ThermalEvaluateResponse } from "../thermal/types";
import { EQUIPMENT_BY_ID, THERMAL_ASSET_EQUIPMENT } from "./layout";
import type { EquipmentId, Hotspot, InvolvedEquipment } from "./types";

export const NO_COMMANDS =
  "Switching is performed only by authorised personnel per permit; this software issues no commands.";

/** Hypothesis key → primary equipment and the measurement that defines the finding. */
const AREA: Record<string, { equipment: EquipmentId; metric: string; title: string }> = {
  intake_restriction: { equipment: "filter_house", metric: "AFDP", title: "Intake filter house" },
  sensor_issue: { equipment: "cdp_tx", metric: "CDP", title: "Compressor CDP transmitter" },
  operating_condition: { equipment: "ambient_station", metric: "AT", title: "Ambient station" },
};

/** Measurement → equipment that carries it (for SYNTHETIC rings). */
export const MEASURE_EQUIPMENT: Record<string, EquipmentId> = {
  AFDP: "filter_house",
  CDP: "compressor",
  TEY: "generator",
  TIT: "combustor",
  TAT: "turbine",
  GTEP: "exhaust_diffuser",
  AT: "ambient_station",
  AP: "ambient_station",
  AH: "ambient_station",
  CO: "stack",
  NOX: "stack",
};

export interface CaseLocation {
  /** true when the case points to a plant area. */
  located: boolean;
  /** Message when nothing is located. */
  nothingMessage: string | null;
  top: Hypothesis | null;
  unconfirmed: boolean;
  primary: EquipmentId | null;
  hotspots: Hotspot[];
  rings: EquipmentId[];
  involved: InvolvedEquipment[];
  /** hypothesis key used for routing (or "electrical" / "emissions"). */
  routingKey: string | null;
  checks: string[];
  synthetic: boolean;
}

function arrowFor(evidence: Evidence[], metric: string): string {
  const ev = evidence.find((e) => e.metric === metric && e.delta !== null) ?? evidence.find((e) => e.metric.startsWith(metric) && e.delta !== null);
  if (!ev || ev.delta === null) return "";
  if (Math.abs(ev.delta) < 1e-9) return " ≈";
  return ev.delta > 0 ? " ↑" : " ↓";
}

function sortedHypotheses(inv: Investigation | null): Hypothesis[] {
  return [...(inv?.report?.hypotheses ?? [])].sort((a, b) => a.rank - b.rank);
}

export function locateCase(
  inv: Investigation | null,
  thermal: ThermalEvaluateResponse | null,
  emissions: EmissionsResponse | null,
  syntheticMeasures: string[],
): CaseLocation {
  const hotspots: Hotspot[] = [];
  const involved: InvolvedEquipment[] = [];
  const synthetic = inv?.scenario_label === "synthetic_overlay";
  const hyps = sortedHypotheses(inv);
  const top = hyps[0] ?? null;
  const report = inv?.report ?? null;
  const noPossible = !hyps.some((h) => h.status === "possible");

  let located = false;
  let nothingMessage: string | null = null;
  let primary: EquipmentId | null = null;
  let routingKey: string | null = null;
  let checks: string[] = [];
  const unconfirmed = top ? top.status === "inconclusive" || top.status === "not_supported" : false;

  if (!inv) {
    nothingMessage = "No case selected — the twin shows live data only. Pick a case to locate a finding.";
  } else if (!report) {
    nothingMessage = "Nothing to locate — no report was produced for this case.";
  } else if (!top || !top.key || !AREA[top.key] || (report.severity === "informational" && noPossible)) {
    nothingMessage = "No notable deviation — nothing to locate";
  } else {
    const area = AREA[top.key];
    located = true;
    primary = area.equipment;
    routingKey = top.key;
    const metricSynthetic = syntheticMeasures.includes(area.metric) || inv.evidence.some((e) => e.metric.startsWith(area.metric) && e.is_synthetic);
    const arrow = arrowFor(inv.evidence, area.metric);
    hotspots.push({
      id: `case-${top.key}`,
      equipment: area.equipment,
      kind: "primary",
      label: `${unconfirmed ? "CANDIDATE (unconfirmed)" : "LOOK HERE"} — ${area.title} · ${area.metric}${arrow}${metricSynthetic ? " synthetic overlay" : ""}`,
      synthetic: metricSynthetic,
      reason: `Rank-1 hypothesis: ${top.name} (${top.status.replace(/_/g, " ")}).`,
      source: metricSynthetic ? "synthetic" : "real",
    });
    const guide = guideFor(top.key);
    checks = [...guide.engineer_checks];
    if (top.key === "intake_restriction") {
      involved.push(
        { equipment: "filter_house", name: "Inlet filter house — filter elements", note: "Inspect loading / condition (AFDP measured across the stages).", provenance: metricSynthetic ? "synthetic" : "real" },
        { equipment: "afdp_tx", name: "AFDP differential-pressure transmitter + impulse lines", note: "Verify calibration before attributing the rise to the filters.", provenance: "real" },
        { equipment: "compressor", name: "Inlet duct, bellmouth and compressor inlet", note: "Corroborate with CDP / TEY over the same rows.", provenance: "real" },
      );
    } else if (top.key === "sensor_issue") {
      involved.push(
        { equipment: "cdp_tx", name: "CDP pressure transmitter + impulse line", note: "Cross-check against redundant sensors; review calibration record.", provenance: metricSynthetic ? "synthetic" : "real" },
        { equipment: "compressor", name: "Compressor discharge casing tapping", note: "Inspect for plugging, freezing or leaks at the tapping.", provenance: "real" },
        { equipment: null, name: "Historian tag configuration (CDP)", note: "Review compression / deadband settings — information only.", provenance: "illustrative" },
      );
    } else if (top.key === "operating_condition") {
      involved.push(
        { equipment: "ambient_station", name: "Ambient station (AT / AP / AH)", note: "Establish ambient context for the window.", provenance: syntheticMeasures.some((m) => ["AT", "AP", "AH"].includes(m)) ? "synthetic" : "real" },
        { equipment: "generator", name: "Generator output / load dispatch (TEY)", note: "Part-load vs base-load context.", provenance: "real" },
        { equipment: null, name: "Inlet-air conditioning (evaporative cooler / anti-icing)", note: "Status as recorded by the site — not in the data.", provenance: "illustrative" },
      );
    }
  }

  // Thermal / electrical flags → hottest flagged electrical asset (SIMULATED).
  if (thermal && thermal.flags.length > 0) {
    const flagged = new Set(thermal.flags.map((f) => f.asset_id));
    const hottest = [...thermal.status].filter((s) => flagged.has(s.asset_id)).sort((a, b) => a.margin_to_alarm_k - b.margin_to_alarm_k)[0];
    if (hottest) {
      const eq = THERMAL_ASSET_EQUIPMENT[hottest.asset_id];
      const flag = thermal.flags.find((f) => f.asset_id === hottest.asset_id);
      hotspots.push({
        id: `thermal-${hottest.asset_id}`,
        equipment: eq,
        kind: located ? "secondary" : "primary",
        label: `LOOK HERE — ${hottest.name} · ${hottest.peak_c.toFixed(0)} °C peak (SIMULATED)`,
        synthetic: thermal.synthetic,
        reason: flag?.message ?? `${hottest.name} flagged by the simulated thermal model.`,
        source: thermal.synthetic ? "synthetic" : "simulated",
      });
      if (!routingKey) routingKey = "electrical";
      involved.push(
        { equipment: eq, name: `${hottest.name} (hottest flagged asset)`, note: `Peak ${hottest.peak_c.toFixed(1)} °C vs alarm ${hottest.alarm_c.toFixed(0)} °C — SIMULATED temperature.`, provenance: thermal.synthetic ? "synthetic" : "simulated" },
        { equipment: "breaker_52g", name: "Generator breaker 52G", note: `State shown is SIMULATED. ${NO_COMMANDS}`, provenance: "simulated" },
        { equipment: "hv_switchgear", name: "HV breaker 52H", note: `State shown is SIMULATED. ${NO_COMMANDS}`, provenance: "simulated" },
      );
    }
  }

  // Emissions excursions in the window → stack (screening only).
  if (emissions && emissions.excursions.length > 0) {
    const ex = emissions.excursions;
    const pollutants = [...new Set(ex.map((e) => (e.pollutant === "NOX" ? "NOx" : "CO")))].join(" / ");
    const first = ex[0];
    hotspots.push({
      id: "emissions-stack",
      equipment: "stack",
      kind: "secondary", // screening flag, never the case finding
      label: `Stack · ${pollutants} above screening threshold (${ex.length} excursion${ex.length > 1 ? "s" : ""})`,
      synthetic: false,
      reason: `${ex.length} excursion(s) in this window, first at rows ${first.start_index}–${first.end_index}. Screening only; not a compliance determination.`,
      source: "real",
    });
    involved.push({ equipment: "stack", name: "Stack CEMS analysers (CO / NOx)", note: "Screening only — permit limits and averaging are site-specific.", provenance: "real" });
  }

  // SYNTHETIC rings around equipment whose measurements carry an overlay.
  const rings: EquipmentId[] = [];
  if (synthetic) {
    const affected = new Set([...(inv?.scenario.affected_measurements ?? []), ...syntheticMeasures]);
    for (const m of affected) {
      const eq = MEASURE_EQUIPMENT[m];
      if (eq && !rings.includes(eq)) rings.push(eq);
    }
  }
  if (thermal?.synthetic_defect) {
    const eq = THERMAL_ASSET_EQUIPMENT[thermal.synthetic_defect.asset_id];
    if (eq && !rings.includes(eq)) rings.push(eq);
  }

  return { located, nothingMessage, top, unconfirmed, primary, hotspots, rings, involved, routingKey, checks, synthetic };
}

export function equipmentLabel(id: EquipmentId): string {
  return EQUIPMENT_BY_ID[id].label;
}
