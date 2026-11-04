/** Mirrors apps/api/app/features/ops/schemas.py */

export type HandoverHours = 8 | 12 | 24;

export interface HandoverRequest {
  hours: HandoverHours;
  persona?: string | null;
}

export interface HandoverItem {
  case_id: string;
  text: string;
}

export interface WatchItem {
  case_id: string | null;
  text: string;
}

export interface HandoverDraft {
  headline: string;
  open_items: HandoverItem[];
  watch_list: WatchItem[];
  completed: HandoverItem[];
  caveats: string[];
}

export interface HandoverCaseRef {
  case_id: string;
  created_at_utc: string;
  status: string;
  mode: string;
  scenario_id: string;
  scenario_title: string;
  scenario_label: string;
  synthetic: boolean;
  window: string;
  severity: string | null;
  rank1_hypothesis: string | null;
  rank1_status: string | null;
  report_title: string | null;
  review_decision: string | null;
  reviewer: string | null;
}

export interface HandoverNote {
  note_id: string;
  created_at_utc: string;
  hours: number;
  persona: string | null;
  window_start_utc: string;
  window_end_utc: string;
  status: string;
  mode: "meta_live" | "offline_fallback";
  meta_used: boolean;
  meta_model: string | null;
  meta_calls: number;
  source_label: string;
  rewrite_used: boolean;
  fallback_reason: string | null;
  validation_errors: string[];
  draft: HandoverDraft;
  cases: HandoverCaseRef[];
  work_requests_included: number;
  work_requests_available: boolean;
  health_flags: Record<string, unknown>;
  latency_ms: number | null;
  tokens: Record<string, number>;
  note_hash: string;
  human_review: string;
}

export interface CmmsTask {
  seq: number;
  text: string;
  type: string;
}

export interface CmmsWorkOrderDraft {
  external_ref: string;
  asset: string;
  priority: string;
  priority_label: string;
  title: string;
  description: string;
  tasks: CmmsTask[];
  requested_by: string;
  status: string;
  generated_at_utc: string;
  system: string;
}

export interface CmmsExport {
  work_order_draft: CmmsWorkOrderDraft;
  provenance: {
    case_id: string;
    scenario_id: string;
    scenario_label: string;
    synthetic: boolean;
    window: string;
    data_source: string;
    investigation_status: string;
    mode: string;
    meta_used: boolean;
    report_hash: string | null;
    human_review: Record<string, unknown> | null;
  };
  notice: string;
}

export interface MedianStat {
  median: number | null;
  n: number;
  unit: string;
}

export interface RateStat {
  rate: number | null;
  numerator: number;
  n: number;
}

export interface OpsMetrics {
  notice: string;
  generated_at_utc: string;
  cases_total: number;
  by_mode: Record<string, number>;
  by_status: Record<string, number>;
  by_scenario_label: Record<string, number>;
  live_cases: number;
  live_wall_time_s: MedianStat;
  tool_calls_per_live_case: MedianStat;
  validator_first_pass_acceptance: RateStat;
  rewrite_rate: RateStat;
  review_counts: Record<string, number>;
  evidence_citations_per_report: MedianStat;
  cited_ids_resolving: RateStat;
  time_to_review_s: MedianStat;
  definitions: Record<string, string>;
}
