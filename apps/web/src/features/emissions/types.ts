/** Mirrors apps/api/app/features/emissions/schemas.py (feature-local types). */
export type Pollutant = "CO" | "NOX";

export interface Thresholds {
  co: number;
  nox: number;
  co_default_p95: number;
  nox_default_p95: number;
  co_source: "default_p95_of_year" | "user";
  nox_source: "default_p95_of_year" | "user";
  label: string;
  unit: string;
}

export interface Distribution {
  n: number;
  mean: number | null;
  min: number | null;
  p05: number | null;
  p25: number | null;
  p50: number | null;
  p75: number | null;
  p95: number | null;
  p99: number | null;
  max: number | null;
}

export interface Correlation {
  x: string;
  y: string;
  n: number;
  pearson: number | null;
  spearman: number | null;
}

export interface EmissionsKpis {
  rows_analyzed: number;
  hours_above_co: number;
  hours_above_nox: number;
  hours_above_any: number;
  pct_above_co: number | null;
  pct_above_nox: number | null;
  excursions_co: number;
  excursions_nox: number;
  excursions_total: number;
  longest_excursion_samples: number;
  corr_co_tey: Correlation;
  corr_co_at: Correlation;
  corr_nox_tey: Correlation;
  corr_nox_at: Correlation;
}

export interface ProfileBin {
  bin: number;
  lo: number;
  hi: number;
  n: number;
  tey_median: number | null;
  tit_median: number | null;
  at_median: number | null;
  co_median: number | null;
  co_p25: number | null;
  co_p75: number | null;
  co_p95: number | null;
  nox_median: number | null;
  nox_p25: number | null;
  nox_p75: number | null;
  nox_p95: number | null;
}

export interface Excursion {
  excursion_id: string;
  pollutant: Pollutant;
  start_index: number;
  end_index: number;
  n_samples: number;
  peak_value: number;
  peak_index: number;
  mean_value: number;
  threshold: number;
  peak_ratio: number;
  tey_mean: number | null;
  tit_mean: number | null;
  at_mean: number | null;
  tit_change: number | null;
  context_tags: string[];
  context: string;
  context_is_heuristic: boolean;
}

export interface EmissionsSeriesRow {
  row_index: number;
  co: number | null;
  nox: number | null;
  tey: number | null;
  tit: number | null;
  at: number | null;
}

export interface EmissionsResponse {
  dataset_id: string;
  source_year: number;
  start: number;
  end: number;
  total_rows_in_year: number;
  provenance_kind: string;
  screening_only: boolean;
  disclaimer: string;
  target_note: string;
  co_unit: string;
  nox_unit: string;
  thresholds: Thresholds;
  kpis: EmissionsKpis;
  distribution_co: Distribution;
  distribution_nox: Distribution;
  profile_tey: ProfileBin[];
  profile_tit: ProfileBin[];
  profile_basis: string;
  context_rules: string[];
  excursions: Excursion[];
  excursions_truncated: boolean;
  series: EmissionsSeriesRow[];
  downsample_factor: number;
  series_note: string;
}

export interface EmissionsQuery {
  dataset_id?: string;
  year: number;
  co_threshold?: number;
  nox_threshold?: number;
}

export interface EmissionsWindowQuery extends EmissionsQuery {
  start: number;
  end: number;
}
