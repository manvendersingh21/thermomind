/** Mirror of apps/api/app/plant/schemas.py (same field names). */
import type { AgentEvent } from "../api/types";

export type { AgentEvent };

export const DELIVERY_NOTE = "Simulated in-app notification — no email/SMS/paging integration.";
export const HOW_IT_WORKS_SOURCE =
  "ThermoMind subsystem registry (apps/api/app/plant/subsystems.py): generic gas-turbine background written for this demo, not plant-specific documentation";
export const NEXT_STEPS_NOTE =
  "Maintenance / diagnostic next steps only. Every step requires supervisor approval and the site's approved procedures (permit-to-work, isolation per procedure). No control commands are issued.";
export const WHATIF_LABEL =
  "Modelled sensitivity from this plant's historical data — not physics, not a control recommendation; review with site procedures";
export const ASSOCIATION_LABEL = "statistical association in this plant's historical data, not causation, not physics";

export type WorkRequestStatus = "open" | "acknowledged" | "done" | "dismissed";
export type Confidence = "low" | "medium" | "high";
export type Direction = "increase" | "decrease" | "no_clear_change" | "mixed" | "unknown";

export interface Persona {
  persona_id: string;
  name: string;
  role: string;
  subsystems: string[];
  description: string;
  measurements_watched: string[];
  supervisor: string | null;
  external: boolean;
  demo_account: boolean;
}

/** hypothesis_key -> {assignee, supervisor, cc, field_inspection} (backend: dict[str, Any]) */
export interface RoutingEntry {
  assignee: string;
  supervisor?: string | null;
  cc?: string[];
  field_inspection?: boolean;
  [k: string]: unknown;
}

export interface PersonasResponse {
  personas: Persona[];
  default_persona: string;
  routing_table: Record<string, RoutingEntry>;
  escalation_rules: string[];
  delivery_note: string;
  auth_note: string;
}

export interface WorkRequestComment {
  ts_utc: string;
  persona: string;
  status: WorkRequestStatus;
  comment: string | null;
}

export interface WorkRequest {
  id: string;
  case_id: string;
  assigned_persona: string;
  title: string;
  status: WorkRequestStatus;
  created_at_utc: string;
  updated_at_utc: string;
  checks: string[];
  routed_by: string;
  supervisor_persona: string | null;
  cc_personas: string[];
  notified_personas: string[];
  notification_reasons: Record<string, string>;
  assignment_label: string;
  hypothesis_key: string;
  severity: string;
  scenario_id: string;
  scenario_label: string;
  synthetic: boolean;
  investigation_status: string;
  history: WorkRequestComment[];
  delivery: string;
  delivery_note: string;
}

export interface Notification {
  id: string;
  persona: string;
  kind: "work_request" | "info";
  message: string;
  read: boolean;
  created_at_utc: string;
  delivery: "in_app_simulated";
  case_id: string | null;
  work_request_id: string | null;
}

export interface InboxResponse {
  persona: Persona;
  notifications: Notification[];
  work_requests: WorkRequest[];
  unread_count: number;
  open_count: number;
  delivery_note: string;
}

export interface StatusUpdateRequest {
  status: WorkRequestStatus;
  comment?: string | null;
}

export interface Subsystem {
  key: string;
  name: string;
  measurements: string[];
  description: string;
  owner_persona: string;
  how_it_works: string;
}

export interface MeasurementInfo {
  key: string;
  name: string;
  unit: string;
  train_std: number;
  max_abs_delta: number;
  step: number;
  is_model_feature: boolean;
}

export interface WhatIfRequest {
  case_id?: string | null;
  question: string;
  measurement: string;
  delta: number;
  persona?: string | null;
}

export interface ChangeSpec {
  measurement: string;
  delta: number;
  unit: string;
  within_training_range: boolean;
}

export interface SubsystemAssessment {
  subsystem: string;
  owner_persona: string;
  owner_label: string;
  impact_summary: string;
  direction: Direction;
  magnitude_hint: string;
  confidence: Confidence;
  caveats: string[];
  tool_numbers_cited: string[];
}

export interface CrossImpact {
  subsystems: string[];
  description: string;
  basis: string;
}

export interface HowItWorks {
  subsystem: string;
  name: string;
  explanation: string;
  source: string;
}

export interface EffectElsewhere {
  subsystem: string;
  description: string;
  direction: Direction;
  magnitude_hint: string;
  confidence: Confidence;
  tool_numbers_cited: string[];
  basis: string;
}

export type StepKind = "inspect" | "verify" | "calibrate" | "schedule" | "isolate_per_procedure" | "collect_data" | "review";

export interface NextStep {
  action: string;
  kind: StepKind;
  subsystem: string;
  rationale: string;
  requires_supervisor_approval: boolean;
}

export interface WhatIfAnswer {
  question: string;
  change: ChangeSpec;
  how_it_works: HowItWorks[];
  effects_elsewhere: EffectElsewhere[];
  recommended_next_steps: NextStep[];
  subsystem_assessments: SubsystemAssessment[];
  cross_impacts: CrossImpact[];
  what_to_check_before_acting: string[];
  disclaimer: string;
}

export interface AgentRun {
  agent: string;
  ok: boolean;
  used_tools: boolean;
  latency_ms: number;
  tokens: Record<string, number>;
  events: AgentEvent[];
  error: string | null;
  assessment: SubsystemAssessment | null;
}

export type WhatIfStatus = "running" | "completed" | "needs_review" | "failed";

export interface WhatIfSession {
  session_id: string;
  created_at_utc: string;
  completed_at_utc: string | null;
  status: WhatIfStatus;
  persona: string;
  request: WhatIfRequest;
  mode: "meta_live" | "offline";
  mode_label: string;
  meta_used: boolean;
  meta_model: string | null;
  base_window: Record<string, unknown>;
  sensitivity: Record<string, unknown>;
  answer: WhatIfAnswer | null;
  agents: AgentRun[];
  validation_errors: string[];
  wall_ms: number | null;
  label: string;
  error: string | null;
}

export interface Precedent {
  case_id: string;
  scenario_id: string;
  scenario_label: string;
  synthetic: boolean;
  rank1_hypothesis: string | null;
  decision: string;
  reviewer: string;
  comment: string | null;
  reviewed_at_utc: string;
  similarity: number;
}

export interface PrecedentsResponse {
  case_id: string | null;
  signature_ids: string[];
  precedents: Precedent[];
  reviewed_cases_considered: number;
  note: string;
}

// ---- deterministic sensitivity (GET /api/plant/sensitivity) -----------------
export interface SensitivityBase {
  source_year: number;
  start: number;
  end: number;
  rows: number;
  basis: string;
}

export interface SensitivityModelEffect {
  applicable: boolean;
  target: string;
  unit: string;
  delta_tey_mean: number | null;
  delta_tey_min: number | null;
  delta_tey_max: number | null;
  expected_tey_base_mean: number | null;
  model_version: string | null;
  note: string;
}

export interface SensitivityTrainRange {
  measurement: string;
  train_min: number;
  train_max: number;
  perturbed_min: number;
  perturbed_max: number;
  rows_outside: number;
  rows: number;
  within_training_range: boolean;
  ood_flag: boolean;
  basis: string;
}

export interface CoMovementItem {
  measurement: string;
  unit: string;
  pearson_r: number;
  slope_per_unit: number;
  implied_change_for_delta: number;
}

export interface SensitivityCoMovement {
  label: string;
  training_years: number[];
  n_rows: number;
  items: CoMovementItem[];
}

export interface Sensitivity {
  tool: string;
  measurement: string;
  delta: number;
  unit: string;
  base: SensitivityBase;
  model_effect: SensitivityModelEffect;
  train_range_check: SensitivityTrainRange;
  co_movement: SensitivityCoMovement;
  caveats: string[];
}
