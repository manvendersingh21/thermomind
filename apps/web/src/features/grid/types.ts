/** Mirrors apps/api/app/features/grid/schemas.py (grid-resilience feature). */
import type { SampleRange, Transformation } from "../../api/types";

export type GridProvenance = "real_observation" | "model_derived" | "assumption" | "synthetic_overlay" | "simulated";
export type CardStatus = "ok" | "watch" | "limited" | "info";
export type GridEvent = "frequency_dip" | "overvoltage" | "load_step";
export type ContingencyConstraint = "transformer_thermal" | "line_limit" | "unit_derate";

export interface GridNumber {
  key: string;
  label: string;
  value: number | null;
  unit: string;
  provenance: GridProvenance;
  computation: string;
  note?: string | null;
}

export interface StatusCard {
  key: string;
  title: string;
  status: CardStatus;
  headline: string;
  numbers: GridNumber[];
  computation: string;
  note?: string | null;
}

export interface SeriesPt {
  row_index: number;
  value: number | null;
}

export interface GridReadiness {
  dataset_id: string;
  year: number;
  window: SampleRange;
  rows: number;
  training_years: number[];
  assumptions: {
    nameplate_mw: number;
    h_constant_s: number;
    power_factor: number;
    h_typical_range_s: number[];
    h_reference: string;
    labels: Record<string, string>;
  };
  numbers: Record<string, GridNumber>;
  cards: StatusCard[];
  summary: { status: CardStatus; headline: string; bullets: string[] };
  charts: { tey: SeriesPt[]; tit: SeriesPt[]; nameplate_mw: number; tit_p99_train: number | null; downsample_factor: number };
  method_notes: string[];
  disclaimer: string;
  computed_at_utc: string;
  time_axis_type: string;
}

export interface ReadinessQuery {
  dataset_id: string;
  year: number;
  start?: number;
  end?: number;
  nameplate_mw: number;
  h_constant_s: number;
  power_factor: number;
}

export interface DrillRequest {
  dataset_id: string;
  year: number;
  start: number;
  end: number;
  event: GridEvent;
  use_meta: boolean;
  seed?: number;
  nameplate_mw?: number;
  h_constant_s?: number;
  power_factor?: number;
}

export interface CoMovement {
  measure: string;
  unit: string;
  pre_mean: number;
  step_mean_original: number;
  step_mean_overlay: number;
  delta_overlay_vs_original: number;
  train_slope_per_mwh: number;
  train_r: number;
  computation: string;
}

export interface DrillEvidence {
  scenario_id: string;
  synthetic: boolean;
  scenario_label: "synthetic_overlay";
  event: GridEvent;
  event_note: string;
  window: SampleRange;
  step_rows: number[];
  step_samples: SampleRange;
  tey_pre_mean: number;
  tey_step_mean_original: number;
  tey_step_mean_overlay: number;
  tey_step_delta: number;
  tey_step_delta_pct: number;
  tey_computation: string;
  co_movement: CoMovement[];
  data_quality: Record<string, unknown>;
  capability: Record<string, GridNumber>;
  transformations: Transformation[];
  provenance: Record<string, string>;
}

export interface GridBrief {
  headline: string;
  what_the_data_shows: string[];
  operator_verifications: string[];
  plant_capability: string[];
  notify: string[];
  risks: string[];
  disclaimer: string;
}

export interface DrillEvent {
  seq: number;
  kind: string;
  summary: string;
  ok: boolean;
  latency_ms?: number | null;
  tokens?: Record<string, number> | null;
}

export interface GridDrill {
  drill_id: string;
  created_at_utc: string;
  request: DrillRequest;
  banner: string;
  synthetic: boolean;
  mode: "meta_live" | "offline_preview" | "offline_fallback";
  meta_used: boolean;
  meta_model?: string | null;
  brief: GridBrief;
  brief_source: "meta" | "deterministic_offline";
  evidence: DrillEvidence;
  series: { measure: string; unit: string; original: SeriesPt[]; overlay: SeriesPt[] }[];
  validation_errors: string[];
  events: DrillEvent[];
  report_status: "draft_requires_human_review";
}

export interface ContingencyAssumptions {
  nameplate_mw: number;
  power_factor: number;
  min_stable_mw: number | null;
  transformer_mva: number;
  line_a_rating_mw: number;
  line_b_rating_mw: number;
  share_to_a: number;
  ss_a_spare_mw: number;
  ss_b_spare_mw: number;
  second_unit_available_mw: number;
  tso_redispatch_assumed_mw: number | null;
  severity_pct: number;
}

export interface ContingencyRequest {
  dataset_id: string;
  year: number;
  start: number;
  end: number;
  shortfall_mw?: number | null;
  constraint?: ContingencyConstraint | null;
  assumptions: Partial<ContingencyAssumptions>;
}

export interface ContingencyOption {
  option_id: "unit_partial_derate" | "second_unit_shift" | "tso_redispatch" | "substation_spare";
  rank: number;
  title: string;
  description: string;
  applicable: boolean;
  covered_mw: number;
  residual_shortfall_mw: number;
  external_dependency: "plant_internal" | "site" | "network_operator" | "tso_external";
  prerequisites: string[];
  who_to_notify: string[];
  computation: string;
  provenance: GridProvenance;
}

export interface TopologyNode {
  node_id: string;
  label: string;
  kind: string;
  capacity?: number | null;
  unit?: string | null;
  flow_mw?: number | null;
  note?: string | null;
}

export interface ContingencyResult {
  dataset_id: string;
  year: number;
  window: SampleRange;
  simulated: boolean;
  constraint: ContingencyConstraint | null;
  shortfall_mw: number;
  shortfall_source: "user_input" | "derived_from_constraint";
  shortfall_semantics: string;
  shortfall_computation: string;
  output_proxy_mwh: number;
  output_proxy_computation: string;
  tit_margin_c: number | null;
  assumptions: ContingencyAssumptions;
  assumption_labels: Record<string, string>;
  topology: TopologyNode[];
  options: ContingencyOption[];
  status: "no_shortfall" | "covered" | "partially_covered" | "not_covered";
  headline: string;
  disclaimer: string;
  computed_at_utc: string;
}
