import type { SampleRange } from "../../api/types";

export type SensorStatus = "ok" | "watch" | "check";

export interface CouplingPair {
  pair: string;
  a: string;
  b: string;
  expected: string;
  r_year: number | null;
  r_train: number | null;
  delta: number | null;
  drift: boolean;
}

export interface SensorHealth {
  key: string;
  name: string;
  unit: string;
  rows: number;
  missing: number;
  out_of_range: number;
  range_source: string;
  range_lo: number | null;
  range_hi: number | null;
  flatline_runs: number;
  flatline_rows: number;
  spikes: number;
  spike_points: number;
  spike_baseline_pct: number;
  coupling: CouplingPair[];
  coupling_drift_pairs: string[];
  penalties: Record<string, number>;
  score: number;
  status: SensorStatus;
  computation: string;
  what_to_check: string;
}

export interface ScorecardSummary {
  headline: string;
  trust: string[];
  use_with_cross_check: string[];
  verify_first: string[];
  mean_score: number;
  coupling_drift_pairs: string[];
  disclaimer: string;
}

export interface Scorecard {
  dataset_id: string;
  year: number;
  window: SampleRange;
  sensors: SensorHealth[];
  summary: ScorecardSummary;
  computed_at_utc: string;
  method_notes: string[];
  provenance_kind: string;
  disclaimer: string;
}
