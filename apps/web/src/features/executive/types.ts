/** Types for /api/executive/* (mirror of apps/api/app/features/executive/schemas.py). */
export type Provenance = "real" | "model_derived" | "simulated" | "assumption" | "prototype_metric";
export type KpiGroup = "performance" | "reliability" | "compliance" | "grid" | "people_knowledge" | "decisions" | "safety";

export interface Kpi {
  key: string;
  group: KpiGroup;
  label: string;
  value: number | string | null;
  unit: string;
  provenance: Provenance;
  source_endpoint: string;
  caveat: string;
  available: boolean;
  detail: Record<string, unknown>;
}

export interface AttentionItem {
  id: string;
  severity: "attention" | "info";
  title: string;
  detail: string;
  persona: string;
  persona_name: string;
  link: string;
  rule: string;
  kpi_keys: string[];
  case_ids: string[];
}

export interface OpenCase {
  case_id: string;
  scenario_id: string;
  synthetic: boolean;
  status: string;
  severity: string | null;
}

export interface ExecutiveOverview {
  dataset_id: string;
  year: number;
  computed_at_utc: string;
  attention: AttentionItem[];
  kpis: Kpi[];
  groups: Record<string, string>;
  open_cases: OpenCase[];
  sources_unavailable: string[];
  method_notes: string[];
  footer: string;
  read_only: true;
}

export interface DecisionNeeded {
  decision: string;
  owner_persona: string | null;
  why: string;
}

export interface BriefDraft {
  headline: string;
  situation: string;
  risks: string[];
  decisions_needed: DecisionNeeded[];
  money_and_time_caveats: string[];
  next_30_days: string[];
}

export interface ExecutiveBrief {
  brief_id: string;
  created_at_utc: string;
  year: number;
  dataset_id: string;
  mode: "meta_live" | "offline_fallback";
  meta_used: boolean;
  meta_model: string | null;
  meta_calls: number;
  source_label: string;
  status: string;
  rewrite_used: boolean;
  fallback_reason: string | null;
  validation_errors: string[];
  brief: BriefDraft;
  disclaimer: string;
  overview_numbers_checked: number;
  latency_ms: number | null;
  tokens: Record<string, number>;
  brief_hash: string;
}
