/**
 * Plant layout for the generic combined-cycle 3D twin (scene units ≈ 2 m).
 * Y is up; ground at y = 0. The gas-turbine train runs along +X at z = 0.
 * No three.js imports: plain tuples so UI code and the scene share one source of truth.
 *
 * Equipment descriptions are generic text written for ThermoMind (not plant documentation and
 * not copied from third-party material). The layout is NOT the UCI facility.
 */
import type { AssetId } from "../thermal/types";
import type { EquipmentId, FlowKind, Provenance, Vec3 } from "./types";

/** Gas-turbine shaft centreline height. */
export const GT_AXIS_Y = 2.2;
/** Steam-turbine shaft centreline height. */
export const ST_AXIS_Y = 3.2;

export interface EquipmentSpec {
  id: EquipmentId;
  label: string;
  /** Hit-box centre and size (w = x, h = y, d = z) used for hover/click picking and hot-spot anchoring. */
  pos: Vec3;
  size: Vec3;
  /** Live measurements shown on hover (keys of MEASUREMENTS), in order. */
  measures: string[];
  /** Simulated thermal asset whose temperature is shown on hover (electrical assets only). */
  thermalAsset?: AssetId;
  /** What drives the visuals of this item. */
  provenance: Provenance;
  description: string;
}

export const EQUIPMENT: EquipmentSpec[] = [
  {
    id: "ambient_station",
    label: "Ambient station (AT / AP / AH)",
    pos: [-18, 2.2, -6],
    size: [2, 4.4, 2],
    measures: ["AT", "AP", "AH"],
    provenance: "real",
    description:
      "Weather mast measuring ambient temperature, pressure and humidity at the air intake. Ambient conditions set air density and therefore how much mass flow — and power — the gas turbine can produce.",
  },
  {
    id: "filter_house",
    label: "Intake filter house",
    pos: [-10.5, 7.5, 0],
    size: [3.6, 3.2, 5.2],
    measures: ["AFDP"],
    provenance: "real",
    description:
      "Rows of filter elements clean the combustion air before it reaches the compressor. As filters load with dust, pollen or moisture, the air filter differential pressure (AFDP) rises and the compressor breathes less easily.",
  },
  {
    id: "afdp_tx",
    label: "AFDP differential-pressure transmitter",
    pos: [-10.5, 6.2, 2.85],
    size: [0.6, 0.6, 0.5],
    measures: ["AFDP"],
    provenance: "real",
    description:
      "Differential-pressure transmitter across the filter stages. Its impulse lines and calibration matter as much as the filters: a drifting transmitter can look like a loading filter.",
  },
  {
    id: "compressor",
    label: "Axial compressor",
    pos: [-8, GT_AXIS_Y, 0],
    size: [5, 3.2, 3.2],
    measures: ["CDP", "AFDP"],
    provenance: "real",
    description:
      "Multi-stage axial compressor raising the filtered air to combustion pressure. Compressor discharge pressure (CDP) reflects air mass flow and compressor health (fouling lowers it).",
  },
  {
    id: "cdp_tx",
    label: "CDP pressure transmitter",
    pos: [-6.4, 3.75, 1.0],
    size: [0.6, 0.7, 0.6],
    measures: ["CDP"],
    provenance: "real",
    description:
      "Pressure transmitter on the compressor discharge casing with its impulse line. Sensor faults (drift, plugging, freezing) show up as a CDP signal that disagrees with TIT, TEY and AFDP.",
  },
  {
    id: "combustor",
    label: "Combustor (can-annular)",
    pos: [-5.2, GT_AXIS_Y, 0],
    size: [1.8, 3.6, 3.6],
    measures: ["TIT"],
    provenance: "real",
    description:
      "Ring of combustion cans where fuel gas burns in the compressed air. Turbine inlet temperature (TIT) is the hottest point in the cycle; it drives output and NOx formation.",
  },
  {
    id: "fuel_skid",
    label: "Fuel gas skid",
    pos: [-5, 0.7, -6],
    size: [2.4, 1.4, 1.6],
    measures: ["TIT"],
    provenance: "illustrative",
    description:
      "Fuel gas conditioning and metering skid feeding the combustor. Fuel flow is not in the UCI data; the orange fuel particles are illustrative, coloured by TIT.",
  },
  {
    id: "turbine",
    label: "Gas turbine (expander)",
    pos: [-3.2, GT_AXIS_Y, 0],
    size: [2.6, 3.6, 3.6],
    measures: ["TIT", "TAT", "TEY"],
    provenance: "real",
    description:
      "Hot gas expands through the turbine stages, driving both the compressor and the generator. Turbine after temperature (TAT) and energy yield (TEY) describe how much work was extracted.",
  },
  {
    id: "exhaust_diffuser",
    label: "Exhaust diffuser",
    pos: [-0.5, GT_AXIS_Y, 0],
    size: [3, 4.4, 4.4],
    measures: ["GTEP", "TAT"],
    provenance: "real",
    description:
      "Diffuser slowing the exhaust gas before the heat-recovery steam generator. Gas turbine exhaust pressure (GTEP) is the back-pressure the turbine works against.",
  },
  {
    id: "hrsg",
    label: "Heat-recovery steam generator (HRSG)",
    pos: [4.5, 4.5, 0],
    size: [7, 8, 5],
    measures: ["TAT", "GTEP"],
    provenance: "illustrative",
    description:
      "Tube banks (superheater, evaporator, economiser) recover heat from the gas-turbine exhaust to raise steam. Not instrumented in the UCI data; shown for context.",
  },
  {
    id: "steam_drum",
    label: "HP steam drum",
    pos: [4.5, 9.6, 0],
    size: [4.4, 1.4, 1.4],
    measures: [],
    provenance: "illustrative",
    description:
      "Drum separating steam from water in the evaporator circuit; saturated steam leaves the top towards the superheater and steam turbine. Illustrative only.",
  },
  {
    id: "stack",
    label: "Exhaust stack (CO / NOx)",
    pos: [9.4, 7.5, 0],
    size: [2.4, 15, 2.4],
    measures: ["CO", "NOX"],
    provenance: "real",
    description:
      "Stack releasing cooled exhaust. CO and NOx concentrations are published hourly in the UCI data; the plume tint is scaled to the screening thresholds (not a compliance determination).",
  },
  {
    id: "steam_turbine",
    label: "Steam turbine",
    pos: [3, ST_AXIS_Y, 10],
    size: [4.4, 2.8, 2.8],
    measures: [],
    provenance: "illustrative",
    description:
      "Steam from the HRSG expands through the steam turbine for additional output without extra fuel. Not in the UCI data; flows are illustrative and scaled with TEY.",
  },
  {
    id: "condenser",
    label: "Condenser",
    pos: [3, 1, 10],
    size: [3.8, 2, 2.8],
    measures: [],
    provenance: "illustrative",
    description:
      "Shell-and-tube condenser under the steam turbine exhaust: cooling water through the tubes condenses steam back to water, which is pumped back to the HRSG. Illustrative only.",
  },
  {
    id: "cooling_tower",
    label: "Cooling tower",
    pos: [16, 5, 5],
    size: [7.4, 10, 7.4],
    measures: ["AT", "AH"],
    provenance: "illustrative",
    description:
      "Natural-draught cooling tower rejecting condenser heat to the atmosphere by evaporation. Its performance depends on ambient temperature and humidity. Illustrative only.",
  },
  {
    id: "generator",
    label: "Generator (GT)",
    pos: [-15, GT_AXIS_Y, 0],
    size: [4.6, 3.2, 3],
    measures: ["TEY"],
    thermalAsset: "GEN",
    provenance: "real",
    description:
      "Synchronous generator on the cold end of the gas-turbine shaft. Turbine energy yield (TEY, MWh as published) is the hourly electrical energy. Stator temperature shown is SIMULATED from load and ambient.",
  },
  {
    id: "breaker_52g",
    label: "Generator breaker 52G",
    pos: [-15, 1.0, 3.9],
    size: [1.4, 2, 1.2],
    measures: ["TEY"],
    thermalAsset: "GCB",
    provenance: "simulated",
    description:
      "Generator circuit breaker (device 52G) between generator and step-up transformer. Breaker state and contact temperature shown are SIMULATED. Switching is performed only by authorised personnel per permit; this software issues no commands.",
  },
  {
    id: "gsu_transformer",
    label: "Step-up transformer (GSU)",
    pos: [-15, 1.6, 7.4],
    size: [3.2, 3.6, 2.8],
    measures: ["TEY"],
    thermalAsset: "GSU",
    provenance: "simulated",
    description:
      "Generator step-up transformer raising generator voltage to grid voltage. Winding hot-spot and top-oil temperatures shown are SIMULATED from real load (IEC 60076-7 style model).",
  },
  {
    id: "hv_switchgear",
    label: "HV switchgear with breaker 52H",
    pos: [-10.5, 1.4, 13.4],
    size: [2.4, 2.8, 1.8],
    measures: ["TEY"],
    thermalAsset: "HVSG",
    provenance: "simulated",
    description:
      "High-voltage switchgear bay containing breaker 52H and disconnectors connecting the unit to the busbar. States and temperatures shown are SIMULATED; no switching is possible from this software.",
  },
  {
    id: "busbar",
    label: "HV busbar",
    pos: [-3, 5, 13.5],
    size: [14, 1.6, 1.6],
    measures: ["TEY"],
    thermalAsset: "BUS",
    provenance: "simulated",
    description:
      "Tubular high-voltage busbar on gantries collecting unit output for export. Conductor temperature shown is SIMULATED.",
  },
  {
    id: "grid_line",
    label: "Grid connection (transmission line)",
    pos: [13, 6, 16],
    size: [16, 10, 2],
    measures: ["TEY"],
    provenance: "real",
    description:
      "Overhead line exporting power to the grid. Pulse rate is scaled by the published hourly energy yield (TEY).",
  },
  {
    id: "st_generator",
    label: "Generator (ST)",
    pos: [-1.2, ST_AXIS_Y, 10],
    size: [3.6, 2.6, 2.6],
    measures: [],
    provenance: "illustrative",
    description:
      "Steam-turbine generator. Its output is not in the UCI data (TEY covers the gas turbine); shown for context only.",
  },
];

export const EQUIPMENT_BY_ID: Record<EquipmentId, EquipmentSpec> = Object.fromEntries(
  EQUIPMENT.map((e) => [e.id, e]),
) as Record<EquipmentId, EquipmentSpec>;

/** Thermal asset → equipment id (for electrical hot spots). */
export const THERMAL_ASSET_EQUIPMENT: Record<AssetId, EquipmentId> = {
  GEN: "generator",
  GCB: "breaker_52g",
  GSU: "gsu_transformer",
  HVSG: "hv_switchgear",
  BUS: "busbar",
};

export interface FlowPath {
  id: string;
  kind: FlowKind;
  /** Control points of a centripetal Catmull-Rom curve. */
  points: Vec3[];
  /** Particle count along the path. */
  count: number;
  /** Random lateral spread radius around the curve (scene units). */
  spread: number;
  /** Particle radius. */
  size: number;
  /** Base speed in path-lengths per second at driver = 1. */
  speed: number;
  /** Also render a pipe/duct tube along this path (static geometry). */
  pipe?: { radius: number; material: "steel" | "insulated" | "fuel" | "water" | "cable" };
}

const Y = GT_AXIS_Y;

export const FLOW_PATHS: FlowPath[] = [
  // Air: atmosphere → filter house → down duct → plenum → compressor → combustor
  {
    id: "air",
    kind: "air",
    points: [
      [-17, 7.6, 0],
      [-12.6, 7.6, 0],
      [-10.5, 7.2, 0],
      [-10.5, 4.6, 0],
      [-10.4, Y + 0.4, 0],
      [-9.6, Y, 0],
      [-6.2, Y, 0],
    ],
    count: 90,
    spread: 0.75,
    size: 0.09,
    speed: 0.16,
  },
  // Fuel gas: skid → combustor
  {
    id: "fuel",
    kind: "fuel",
    points: [
      [-5, 1.2, -5.2],
      [-5, 1.2, -3.4],
      [-5.1, 1.6, -2.3],
      [-5.2, Y, -1.4],
    ],
    count: 22,
    spread: 0.02,
    size: 0.1,
    speed: 0.35,
    pipe: { radius: 0.09, material: "fuel" },
  },
  // Hot gas: combustor → turbine → diffuser → HRSG → stack
  {
    id: "gas",
    kind: "gas",
    points: [
      [-4.8, Y, 0],
      [-2.2, Y, 0],
      [0.8, Y, 0],
      [3, 3.2, 0],
      [6.2, 5.6, 0],
      [8.4, 7.4, 0],
      [9.4, 9.5, 0],
      [9.4, 15.2, 0],
    ],
    count: 110,
    spread: 0.6,
    size: 0.11,
    speed: 0.12,
  },
  // Steam: drum → steam turbine (HP end)
  {
    id: "steam",
    kind: "steam",
    points: [
      [4.5, 10.3, 0.4],
      [4.5, 10.9, 3],
      [3.2, 8.6, 6.8],
      [1.3, 5.6, 9],
      [1.3, 4.4, 10],
    ],
    count: 40,
    spread: 0.04,
    size: 0.11,
    speed: 0.22,
    pipe: { radius: 0.16, material: "insulated" },
  },
  // Cooling water supply: condenser → cooling tower
  {
    id: "cw_supply",
    kind: "water",
    points: [
      [4.9, 0.6, 10.8],
      [8, 0.6, 10.8],
      [11.5, 0.6, 8.6],
      [13.4, 0.9, 6.6],
    ],
    count: 36,
    spread: 0.03,
    size: 0.11,
    speed: 0.22,
    pipe: { radius: 0.2, material: "water" },
  },
  // Cooling water return: tower basin → condenser
  {
    id: "cw_return",
    kind: "water",
    points: [
      [13.2, 0.35, 3.4],
      [10.6, 0.35, 6.6],
      [8, 0.35, 9.2],
      [4.9, 0.35, 9.2],
    ],
    count: 36,
    spread: 0.03,
    size: 0.11,
    speed: 0.22,
    pipe: { radius: 0.2, material: "water" },
  },
  // Condensate / feedwater: condenser → HRSG economiser
  {
    id: "feedwater",
    kind: "water",
    points: [
      [1.4, 0.5, 9],
      [1.4, 0.5, 5],
      [2, 0.9, 2.8],
      [2.4, 1.6, 2.5],
    ],
    count: 20,
    spread: 0.02,
    size: 0.09,
    speed: 0.25,
    pipe: { radius: 0.12, material: "water" },
  },
  // Electricity: generator → 52G → GSU → HV switchgear (52H) → busbar → grid
  {
    id: "power_gt",
    kind: "power",
    points: [
      [-15, 1.3, 1.4],
      [-15, 1.3, 3.3],
      [-15, 1.3, 4.6],
      [-15, 3.4, 6.6],
      [-15, 4.4, 8.6],
      [-12.5, 4.4, 11.8],
      [-10.5, 3.0, 13.4],
      [-9.6, 5, 13.5],
      [4, 5, 13.5],
      [10, 9.2, 16],
      [21, 9.2, 16],
    ],
    count: 48,
    spread: 0,
    size: 0.13,
    speed: 0.09,
    pipe: { radius: 0.06, material: "cable" },
  },
  // Electricity from the ST generator to the busbar (illustrative)
  {
    id: "power_st",
    kind: "power",
    points: [
      [-1.2, 4.5, 10.8],
      [-1.2, 5, 12.4],
      [-1.2, 5, 13.5],
    ],
    count: 8,
    spread: 0,
    size: 0.11,
    speed: 0.3,
    pipe: { radius: 0.05, material: "cable" },
  },
];

/** Camera defaults. */
export const CAMERA_POSITION: Vec3 = [-28, 28, 42];
export const CAMERA_TARGET: Vec3 = [-2.5, 4, 3.5];
