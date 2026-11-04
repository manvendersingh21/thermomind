/**
 * ThermoMind API types — mirror of apps/api/app/schemas.py (THE CONTRACT).
 * Do not rename fields. Add fields only with a default on the Python side.
 */

// ---------------------------------------------------------------------------
// Constants (mirrors schemas.py)
// ---------------------------------------------------------------------------

export const MEASUREMENTS: Record<string, { name: string; unit: string }> = {
  AT: { name: "Ambient temperature", unit: "°C" },
  AP: { name: "Ambient pressure", unit: "mbar" },
  AH: { name: "Ambient humidity", unit: "%" },
  AFDP: { name: "Air filter differential pressure", unit: "mbar" },
  GTEP: { name: "Gas turbine exhaust pressure", unit: "mbar" },
  TIT: { name: "Turbine inlet temperature", unit: "°C" },
  TAT: { name: "Turbine after temperature", unit: "°C" },
  TEY: { name: "Turbine energy yield", unit: "MWh" },
  CDP: { name: "Compressor discharge pressure", unit: "mbar (as published; unit under validation)" },
  CO: { name: "Carbon monoxide", unit: "mg/m³" },
  NOX: { name: "Nitrogen oxides", unit: "mg/m³" },
};
export const MEASUREMENT_KEYS = Object.keys(MEASUREMENTS);
export const FEATURE_KEYS = ["AT", "AP", "AH", "AFDP", "GTEP", "TIT", "TAT", "CDP"];
export const TARGET_KEY = "TEY";

export const UCI_SOURCE_ID = "UCI_GAS_TURBINE_551";
export const UCI_LICENSE = "CC-BY-4.0";
export const UCI_DOI = "10.24432/C5WC95";
export const UCI_URL =
  "https://archive.ics.uci.edu/dataset/551/gas+turbine+co+and+nox+emission+data+set";
export const UCI_CITATION =
  "Kaya, H., Tüfekci, P. & Gürgen, F. (2019). Gas Turbine CO and NOx Emission Data Set. " +
  "UCI Machine Learning Repository. https://doi.org/10.24432/C5WC95";

export type ProvenanceKind =
  | "real_observation"
  | "model_derived"
  | "synthetic_overlay"
  | "measured_plus_synthetic_overlay";
export type ScenarioLabel = "real_only" | "synthetic_overlay";

// ---------------------------------------------------------------------------
// Dataset / measurements
// ---------------------------------------------------------------------------

export interface MeasurementInfo {
  key: string;
  name: string;
  unit: string;
  count: number;
  missing: number;
  min: number | null;
  max: number | null;
  mean: number | null;
  median: number | null;
}

export interface SourceFileInfo {
  filename: string;
  source_year: number | null;
  rows: number;
  sha256: string;
  bytes: number;
}

export interface DatasetSummary {
  dataset_id: string;
  source: string;
  source_license: string | null;
  source_url: string | null;
  citation: string | null;
  plant: string | null;
  row_count: number;
  years: number[];
  columns: string[];
  has_timestamps: boolean;
  time_axis_type: string;
  created_at_utc: string;
  warnings: string[];
}

export interface DatasetDetail extends DatasetSummary {
  source_files: SourceFileInfo[];
  measurements: MeasurementInfo[];
  rows_per_year: Record<string, number>;
  provenance_notes: string[];
}

export interface UploadResult {
  dataset_id: string;
  rows: number;
  columns: string[];
  source: string;
  sha256: string;
  warnings: string[];
}

export interface SeriesPoint {
  row_index: number;
  value: number | null;
  expected: number | null;
}

export interface SeriesResponse {
  dataset_id: string;
  measure: string;
  unit: string;
  source_year: number;
  start: number;
  end: number; // exclusive
  total_rows_in_year: number;
  downsample_factor: number;
  points: SeriesPoint[];
  provenance_kind: ProvenanceKind;
  scenario_id: string | null;
  synthetic: boolean;
  source: string;
  time_axis_type: string;
}

// ---------------------------------------------------------------------------
// Model / evaluation
// ---------------------------------------------------------------------------

export interface SplitInfo {
  train_years: number[];
  validation_years: number[];
  test_years: number[];
  train_rows: number;
  validation_rows: number;
  test_rows: number;
  method: string;
}

export interface MetricSet {
  mae: number;
  rmse: number;
  r2: number;
  n: number;
}

export interface ModelEvaluation {
  model_id: string;
  model_version: string;
  algorithm: string;
  features: string[];
  target: string;
  target_unit: string;
  seed: number;
  split: SplitInfo;
  validation: MetricSet;
  holdout: MetricSet;
  naive_baselines: Record<string, MetricSet>;
  residual_std_validation: number;
  residual_quantiles_validation: Record<string, number>;
  feature_ranges_train: Record<string, number[]>;
  trained_at_utc: string;
  notes: string[];
  device?: string | null; // e.g. "cpu" or "cuda:0 Tesla V100-PCIE-32GB"
  training_seconds?: number | null;
  role?: "production_baseline" | "challenger";
}

export interface GpuInfo {
  available: boolean;
  name?: string | null;
  memory_mb?: number | null;
  driver?: string | null;
}

export interface ModelComparison {
  production: ModelEvaluation;
  challengers: ModelEvaluation[];
  selection_rule: string; // how the production model is chosen (validation-based, never holdout)
  gpu: GpuInfo;
}

export interface TrainRequest {
  seed?: number;
}

// ---------------------------------------------------------------------------
// Scenarios
// ---------------------------------------------------------------------------

export interface Transformation {
  measurement: string;
  operation: string; // "add_ramp" | "multiply_ramp" | "add_offset" | "spike" | "none"
  params: Record<string, unknown>;
  description: string;
}

export interface ScenarioInfo {
  scenario_id: string;
  title: string;
  synthetic: boolean;
  description: string;
  rationale: string;
  affected_measurements: string[];
  default_year: number;
  default_start: number;
  default_end: number; // exclusive
  default_seed: number;
  expected_behavior: string;
}

export interface ScenarioPreviewRequest {
  dataset_id: string;
  scenario_id: string;
  year?: number;
  start_index?: number;
  end_index?: number;
  measurements?: string[];
  seed?: number | null;
}

export interface ScenarioSeries {
  measure: string;
  unit: string;
  original: SeriesPoint[];
  overlay: SeriesPoint[];
  expected: SeriesPoint[] | null;
}

export interface ScenarioPreviewResponse {
  dataset_id: string;
  scenario_id: string;
  synthetic: boolean;
  scenario_label: ScenarioLabel;
  year: number;
  start_index: number;
  end_index: number;
  seed: number;
  transformations: Transformation[];
  series: ScenarioSeries[];
  provenance: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Evidence
// ---------------------------------------------------------------------------

export interface SampleRange {
  source_year: number;
  start: number;
  end: number; // exclusive
}

export type DataQualityLevel = "pass" | "warn" | "fail";

export interface Evidence {
  evidence_id: string;
  case_id: string;
  kind: ProvenanceKind;
  metric: string;
  unit: string;
  title: string;
  sample_range: SampleRange;
  reference_range: SampleRange | null;
  observed_stat: number | null;
  comparison_stat: number | null;
  delta: number | null;
  delta_pct: number | null;
  z_score: number | null;
  method: string;
  computation: string;
  data_quality: DataQualityLevel;
  is_synthetic: boolean;
  model_version: string | null;
  flags: string[];
  values: Record<string, unknown>;
}

export interface DataQualityReport {
  case_id: string;
  missing_values: Record<string, number>;
  out_of_training_range: Record<string, number>;
  sensor_consistency_flags: string[];
  scenario_label: ScenarioLabel;
  synthetic_measurements: string[];
  source: string;
  notes: string[];
}

export interface BaselineComparison {
  case_id: string;
  model_version: string;
  window: SampleRange;
  reference: SampleRange;
  observed_tey_mean: number;
  expected_tey_mean: number;
  residual_mean: number;
  residual_std_window: number;
  residual_std_validation: number;
  residual_z: number;
  reference_residual_mean: number;
  unit: string;
  holdout_mae: number;
  holdout_r2: number;
  caveats: string[];
}

export interface HypothesisEvaluation {
  case_id: string;
  hypothesis_key: string;
  supporting_evidence_ids: string[];
  contradicting_evidence_ids: string[];
  deterministic_notes: string[];
  deterministic_support_score: number;
}

// ---------------------------------------------------------------------------
// Investigation / agent
// ---------------------------------------------------------------------------

export const HYPOTHESIS_KEYS = ["intake_restriction", "operating_condition", "sensor_issue", "unknown"];

export interface InvestigationRequest {
  dataset_id: string;
  scenario_id?: string;
  year?: number;
  start_index?: number;
  end_index?: number;
  seed?: number | null;
  use_meta?: boolean;
}

export interface Observation {
  statement: string;
  evidence_ids: string[];
}

export type HypothesisStatus = "possible" | "inconclusive" | "not_supported";

export interface Hypothesis {
  name: string;
  key: string | null;
  rank: number;
  supporting_evidence_ids: string[];
  contradicting_evidence_ids: string[];
  limitations: string[];
  status: HypothesisStatus;
  rationale: string | null;
  what_would_change_assessment: string | null;
}

export type Severity = "informational" | "review" | "urgent_review";

export interface DiagnosticReport {
  case_id: string;
  title: string;
  summary: string;
  severity: Severity;
  data_source: string;
  scenario_label: ScenarioLabel;
  observations: Observation[];
  hypotheses: Hypothesis[];
  additional_data_needed: string[];
  engineer_review_checks: string[];
  limitations: string[];
  disclaimer: string;
  report_status: "draft_requires_human_review";
}

export type AgentEventKind =
  | "case_opened"
  | "model_request"
  | "model_response"
  | "tool_call"
  | "tool_result"
  | "validation"
  | "rewrite_requested"
  | "report_accepted"
  | "error"
  | "fallback";

export interface AgentEvent {
  seq: number;
  ts_utc: string;
  kind: AgentEventKind;
  tool_name: string | null;
  args: Record<string, unknown> | null;
  summary: string;
  evidence_ids: string[];
  latency_ms: number | null;
  ok: boolean;
  tokens: Record<string, number> | null;
}

export type InvestigationStatus = "queued" | "running" | "completed" | "needs_review" | "failed";
export type ReviewDecision = "accepted" | "rejected" | "more_data_requested";
export type InvestigationMode = "meta_live" | "offline_preview";

export interface ReviewRecord {
  decision: ReviewDecision;
  reviewer: string;
  comment: string | null;
  ts_utc: string;
}

export interface ReviewRequest {
  decision: ReviewDecision;
  reviewer?: string;
  comment?: string | null;
}

/** Fully-populated request as echoed back by the server inside Investigation. */
export interface InvestigationRequestResolved {
  dataset_id: string;
  scenario_id: string;
  year: number;
  start_index: number;
  end_index: number;
  seed: number | null;
  use_meta: boolean;
}

export interface Investigation {
  case_id: string;
  status: InvestigationStatus;
  created_at_utc: string;
  completed_at_utc: string | null;
  request: InvestigationRequestResolved;
  scenario: ScenarioInfo;
  scenario_label: ScenarioLabel;
  window: SampleRange;
  reference: SampleRange;
  model_version: string | null;
  meta_model: string | null;
  meta_used: boolean;
  mode: InvestigationMode;
  report: DiagnosticReport | null;
  deterministic_summary: Record<string, unknown>;
  evidence: Evidence[];
  data_quality: DataQualityReport | null;
  baseline: BaselineComparison | null;
  events: AgentEvent[];
  validation_errors: string[];
  report_hash: string | null;
  review: ReviewRecord | null;
  error: string | null;
}

export interface InvestigationCreated {
  case_id: string;
  status: InvestigationStatus;
}

// ---------------------------------------------------------------------------
// Health / demo status
// ---------------------------------------------------------------------------

export interface Health {
  status: "ok" | "degraded";
  version: string;
  build: string;
  data_ready: boolean;
  model_ready: boolean;
  meta_configured: boolean;
  meta_model: string;
  meta_base_url: string;
}

export interface DemoStatus {
  data: Record<string, unknown>;
  model: Record<string, unknown>;
  meta: Record<string, unknown>;
  backend: Record<string, unknown>;
  scenarios: Record<string, unknown>;
  build: Record<string, unknown>;
  ready_for_demo: boolean;
  blockers: string[];
}
