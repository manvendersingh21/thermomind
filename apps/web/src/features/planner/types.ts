/** Mirrors apps/api/app/features/planner/schemas.py (feature-local, not the shared contract). */

export type WashStatus = "consider scheduling a wash (human decision)" | "no economic case yet" | "insufficient data";
export type FilterStatus =
  | "consider scheduling a filter change-out (human decision)"
  | "no economic case yet"
  | "insufficient data";

export interface Assumption {
  key: string;
  label: string;
  value: number | string;
  unit: string;
  source: "user_input" | "default";
}

export interface CdpTrend {
  unit: string;
  start_rolling: number | null;
  end_rolling: number | null;
  slope_per_1000_samples: number | null;
  note: string;
}

export interface WashSeriesPoint {
  row_index: number;
  rolling_residual_mwh: number | null;
  cumulative_loss_mwh: number | null;
  cdp_rolling: number | null;
}

export interface FilterSeriesPoint {
  row_index: number;
  afdp_rolling_mbar: number | null;
  trend_mbar: number | null;
  cumulative_loss_mwh: number | null;
}

export interface ProjectionPoint {
  row_index: number;
  trend_mbar: number;
}

export interface AfdpProxy {
  method: string;
  coefficient_mwh_per_sample_per_mbar: number | null;
  residual_slope_mwh_per_mbar: number | null;
  model_sensitivity_mwh_per_mbar: number | null;
  training_years: number[];
  n_rows: number;
  statement: string;
  notes: string[];
}

interface ResultBase {
  dataset_id: string;
  year: number;
  model_version: string | null;
  n_samples: number;
  rolling_window_samples: number;
  current_index: number | null;
  energy_unit_note: string;
  economics: Record<string, number | null>;
  break_even_reached: boolean;
  break_even_index: number | null;
  payback_hours_if_rate_persists: number | null;
  status_reasons: string[];
  computation: string;
  assumptions: Assumption[];
  caveats: string[];
  labels: string[];
  disclaimer: string;
  requires_human_review: true;
}

export interface CompressorWashResult extends ResultBase {
  status: WashStatus;
  best_rolling_residual_mwh: number | null;
  best_index: number | null;
  current_rolling_residual_mwh: number | null;
  lost_output_rate_now_mwh_per_sample: number | null;
  cumulative_lost_output_mwh: number | null;
  typical_output_mwh_per_sample: number | null;
  cdp: CdpTrend;
  series: WashSeriesPoint[];
}

export interface FilterChangeoutResult extends ResultBase {
  status: FilterStatus;
  afdp_limit_mbar: number;
  trend_window_samples: number;
  current_afdp_rolling_mbar: number | null;
  clean_afdp_mbar: number | null;
  clean_index: number | null;
  trend_slope_mbar_per_1000_samples: number | null;
  limit_reached: boolean;
  samples_to_limit: number | null;
  projected_limit_index: number | null;
  afdp_training_range_mbar: number[] | null;
  lost_output_rate_now_mwh_per_sample: number | null;
  cumulative_lost_output_mwh: number | null;
  typical_output_mwh_per_sample: number | null;
  proxy: AfdpProxy;
  series: FilterSeriesPoint[];
  projection: ProjectionPoint[];
}

export interface WashInputs {
  rolling_window_samples: number;
  energy_price_per_mwh: number;
  wash_outage_hours: number;
  wash_direct_cost: number;
  expected_recovery_fraction: number;
}

export interface FilterInputs {
  rolling_window_samples: number;
  energy_price_per_mwh: number;
  afdp_limit_mbar: number;
  trend_window_samples: number;
  filter_change_cost: number;
  filter_outage_hours: number;
}

export interface PlannerOptions {
  dataset_id: string;
  data_available: boolean;
  years: number[];
  default_year: number | null;
  model_available: boolean;
  model_version: string | null;
  afdp_training_range_mbar: number[] | null;
  wash_defaults: WashInputs;
  filter_defaults: FilterInputs;
  labels: string[];
  disclaimer: string;
  notes: string[];
}

export type CompressorWashRequest = WashInputs & { dataset_id: string; year: number };
export type FilterChangeoutRequest = FilterInputs & { dataset_id: string; year: number };
