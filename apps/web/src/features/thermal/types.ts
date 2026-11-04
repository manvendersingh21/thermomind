/** Mirrors apps/api/app/features/thermal/schemas.py (feature-local types). */
export type Provenance = "simulated_from_real_load";
export type AssetId = "GEN" | "GCB" | "GSU" | "HVSG" | "BUS";
export type ThermalScenario = "none" | "T01_HOT_CONNECTION";
export type DemandProfile = "flat" | "diurnal_datacenter";
export type AssetState = "normal" | "approaching" | "alarm" | "limit";
export type Severity = "info" | "watch" | "warning" | "high";
export type FlagType =
  | "approaching_alarm"
  | "above_alarm"
  | "above_limit"
  | "exceeded_alarm_in_window"
  | "rising_faster_than_peers"
  | "hot_connection_pattern";

export interface ThermalAssumptions {
  generator_rated_mwh: number;
  transformer_rated_mwh: number;
  hv_rated_mwh: number;
  indoor_ambient_offset_k: number;
  approach_margin_k: number;
  top_oil_rise_rated_k: number;
  hot_spot_gradient_rated_k: number;
  loss_ratio_r: number;
  exponent_n: number;
  exponent_m: number;
  tau_top_oil_h: number;
  tau_hot_spot_h: number;
  transformer_hot_spot_alarm_c: number;
  transformer_hot_spot_limit_c: number;
  transformer_top_oil_limit_c: number;
  normal_insulation_life_h: number;
  generator_rated_rise_k: number;
  generator_alarm_c: number;
  generator_limit_c: number;
  contact_rated_rise_k: number;
  contact_alarm_c: number;
  contact_limit_c: number;
  busbar_rated_rise_k: number;
  busbar_alarm_c: number;
  busbar_limit_c: number;
  hot_connection_growth: number;
}

export interface ThermalEvaluateRequest {
  dataset_id?: string;
  year: number;
  start: number;
  end: number;
  assumptions?: Partial<ThermalAssumptions>;
  scenario?: ThermalScenario;
  scenario_seed?: number;
  demand_multiplier?: number | null;
  demand_profile?: DemandProfile;
}

export interface AssetInfo {
  asset_id: AssetId;
  name: string;
  kind: string;
  order: number;
  group: "rotating" | "connection" | "transformer";
  temperature_label: string;
  model: string;
  standard_ref: string;
  rating_param: string;
  rise_param: string | null;
  alarm_param: string;
  limit_param: string;
}

export interface DemandProfileInfo {
  profile: DemandProfile;
  description: string;
}

export interface ThermalAssetsResponse {
  assets: AssetInfo[];
  default_assumptions: ThermalAssumptions;
  scenarios: ThermalScenario[];
  demand_profiles: DemandProfileInfo[];
  provenance: Provenance;
  banner: string;
}

export interface WindowInfo {
  source_year: number;
  start: number;
  end: number;
  n_samples: number;
  note: string;
}

export interface AssetStatus {
  asset_id: AssetId;
  name: string;
  state: AssetState;
  current_c: number;
  load_ratio_k: number;
  ambient_c: number;
  alarm_c: number;
  limit_c: number;
  margin_to_alarm_k: number;
  margin_to_limit_k: number;
  peak_c: number;
  peak_row_index: number;
  trend_k_per_sample: number | null;
  trend_window_samples: number;
  samples_above_alarm: number;
  samples_above_limit: number;
  rise_index: number | null;
  rise_index_drift: number | null;
  top_oil_c: number | null;
  top_oil_limit_c: number | null;
  synthetic: boolean;
  provenance: Provenance;
}

export interface ThermalFlag {
  asset_id: AssetId;
  flag: FlagType;
  severity: Severity;
  message: string;
  synthetic: boolean;
  provenance: Provenance;
}

export interface Advisory {
  asset_id: AssetId;
  kind: "margin" | "hot_connection" | "trend" | "demand_scenario";
  severity: Severity;
  text: string;
  read_only: boolean;
  synthetic: boolean;
  what_if: boolean;
  provenance: Provenance;
}

export interface Ageing {
  asset_id: AssetId;
  method: string;
  current_faa: number;
  equivalent_faa: number;
  loss_of_life_h: number;
  loss_of_life_pct: number;
  window_hours: number;
  normal_insulation_life_h: number;
  extrapolated_loss_of_life_pct_per_year: number;
  extrapolation_label: string;
  provenance: Provenance;
}

export interface SeriesPoint {
  row_index: number;
  ambient_c: number;
  load_mwh: number;
  load_ratio_k: number;
  GEN: number;
  GCB: number;
  GSU: number;
  GSU_TOP_OIL: number;
  HVSG: number;
  BUS: number;
  lol_cum_pct: number;
  GSU_whatif: number | null;
  lol_cum_pct_whatif: number | null;
}

export interface LimitLine {
  asset_id: AssetId;
  alarm_c: number;
  limit_c: number;
}

export interface DemandImpactRow {
  asset_id: AssetId;
  baseline_peak_c: number;
  scenario_peak_c: number;
  delta_peak_k: number;
  baseline_samples_above_alarm: number;
  scenario_samples_above_alarm: number;
  baseline_samples_above_limit: number;
  scenario_samples_above_limit: number;
}

export interface DemandScenario {
  applied: boolean;
  multiplier: number;
  profile: DemandProfile;
  description: string;
  notional_hour_note: string | null;
  samples_above_nameplate_baseline: number;
  samples_above_nameplate_scenario: number;
  impact: DemandImpactRow[];
  scenario_status: AssetStatus[];
  baseline_loss_of_life_pct: number | null;
  scenario_loss_of_life_pct: number | null;
  caveat: string;
  what_if: boolean;
}

export interface SyntheticDefect {
  scenario: "T01_HOT_CONNECTION";
  asset_id: AssetId;
  description: string;
  growth: number;
  seed: number;
  synthetic: boolean;
}

export interface ThermalEvaluateResponse {
  dataset_id: string;
  window: WindowInfo;
  provenance: Provenance;
  synthetic: boolean;
  scenario: ThermalScenario;
  synthetic_defect: SyntheticDefect | null;
  demand: DemandScenario;
  status: AssetStatus[];
  flags: ThermalFlag[];
  advisories: Advisory[];
  ageing: Ageing;
  limits: LimitLine[];
  series: SeriesPoint[];
  downsample_factor: number;
  assumptions: ThermalAssumptions;
  banner: string;
  model_note: string;
}
