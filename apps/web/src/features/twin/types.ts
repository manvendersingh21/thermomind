/**
 * Shared types for the 3D digital twin. No three.js imports here so UI code can use them
 * without pulling the 3D chunk.
 */
import type { AssetId } from "../thermal/types";

export type Vec3 = [number, number, number];

export type EquipmentId =
  | "ambient_station"
  | "filter_house"
  | "afdp_tx"
  | "compressor"
  | "cdp_tx"
  | "combustor"
  | "fuel_skid"
  | "turbine"
  | "exhaust_diffuser"
  | "hrsg"
  | "steam_drum"
  | "stack"
  | "steam_turbine"
  | "condenser"
  | "cooling_tower"
  | "generator"
  | "breaker_52g"
  | "gsu_transformer"
  | "hv_switchgear"
  | "busbar"
  | "grid_line"
  | "st_generator";

/** Provenance classes shown in the legend. */
export type Provenance = "real" | "model" | "simulated" | "synthetic" | "illustrative";

export type FlowKind = "air" | "fuel" | "gas" | "steam" | "water" | "power" | "dust" | "plume" | "vapor";

/**
 * Live, per-frame state read by scene components inside useFrame (via a ref) so the React tree
 * does not re-render on every sample. Raw values are as published (units in MEASUREMENTS);
 * `n.*` are 0..1 normalisations used only for visual scaling.
 */
export interface LiveState {
  /** row_index of the current sample (null when no data). */
  row: number | null;
  /** Raw measurement values at the current sample (as published, or synthetic overlay where labelled). */
  v: Record<string, number | null>;
  /** 0..1 normalised drivers for visuals. */
  n: {
    tey: number; // electricity pulse rate + generator glow
    tit: number; // combustor emissive colour
    afdp: number; // filter dirtiness + dust
    cdp: number; // compressor gauge needle
    gtep: number; // exhaust plume size
    co: number; // stack plume tint (CO / threshold)
    nox: number; // stack plume tint (NOx / threshold)
  };
  /** Simulated electrical temperatures (°C) and 0..1 heat vs alarm, keyed by thermal asset id. */
  temps: Partial<Record<AssetId, number>>;
  heat: Partial<Record<AssetId, number>>;
  /** Global animation speed multiplier (0 = paused visuals, 1 = normal). */
  speed: number;
}

export function emptyLive(): LiveState {
  return {
    row: null,
    v: {},
    n: { tey: 0.6, tit: 0.6, afdp: 0.3, cdp: 0.5, gtep: 0.5, co: 0.2, nox: 0.4 },
    temps: {},
    heat: {},
    speed: 1,
  };
}

export type HotspotKind = "primary" | "secondary";

export interface Hotspot {
  id: string;
  equipment: EquipmentId;
  kind: HotspotKind;
  /** Billboard text, e.g. "LOOK HERE — Intake filter house · AFDP ↑ synthetic overlay". */
  label: string;
  synthetic: boolean;
  /** Short explanation for the side panel. */
  reason: string;
  source: Provenance;
}

export interface InvolvedEquipment {
  equipment: EquipmentId | null;
  name: string;
  note: string;
  provenance: Provenance;
}
