/** Mirrors apps/api/app/features/deliberation/schemas.py (pydantic models are the contract). */
import type { AgentEvent } from "../../api/types";

export type Verdict = "support" | "oppose" | "neutral" | "insufficient_evidence";
export type Confidence = "low" | "medium" | "high";
export type Recommendation = "proceed_with_conditions" | "do_not_proceed" | "insufficient_evidence";
export type Provenance =
  | "real_observation"
  | "model_derived"
  | "statistical_association"
  | "derived_from_history"
  | "simulated"
  | "assumption"
  | "operator_intent"
  | "not_observable";
export type FindingStatus = "ok" | "info" | "watch" | "concern" | "exceeds" | "unavailable";
export type Decision = "approve_plan" | "reject" | "defer";
export type SessionStatus = "running" | "completed" | "needs_review" | "failed";

export interface MagnitudeSpec {
  unit: string;
  default: number;
  min: number;
  max: number;
  step: number;
  label: string;
}

export interface IntentInfo {
  intent_id: string;
  label: string;
  description: string;
  magnitude: MagnitudeSpec | null;
  subsystems: string[];
  primary_measurement: string | null;
  observable: boolean;
  notes: string[];
}

export interface MeasurementDelta {
  measurement: string;
  delta: number;
  unit: string;
  role: "primary" | "implied";
  basis: string;
  provenance: Provenance;
  slope: number | null;
  pearson_r: number | null;
  slope_of: string | null;
}

export interface ModelledChange {
  intent_id: string;
  label: string;
  text: string;
  magnitude: number | null;
  unit: string | null;
  deltas: MeasurementDelta[];
  subsystems: string[];
  observable: boolean;
  qualitative_notes: string[];
  slope_label: string;
  training_years: number[];
}

export interface CustomIntent {
  text: string;
  deltas: Record<string, number>;
}

export interface ProposeRequest {
  case_id?: string | null;
  dataset_id?: string;
  year?: number | null;
  start?: number | null;
  end?: number | null;
  intent_id?: string | null;
  custom?: CustomIntent | null;
  magnitude?: number | null;
  persona?: string | null;
}

export interface ConstraintFinding {
  n: number;
  key: string;
  title: string;
  status: FindingStatus;
  detail: string;
  provenance: Provenance;
  source: string;
  numbers: Record<string, unknown>;
}

export interface AgentVerdict {
  subsystem: string;
  verdict: Verdict;
  confidence: Confidence;
  reasons: string[];
  harms: string[];
  prerequisites: string[];
  tool_numbers_cited: string[];
  owner_persona: string | null;
  fallback: boolean;
}

export type AgentRunStatus = "pending" | "running" | "done" | "failed";
export type AgentRole = "subsystem" | "constraints" | "aggregator";

export interface DelibAgentRun {
  agent: string;
  role: AgentRole;
  name: string;
  status: AgentRunStatus;
  ok: boolean;
  used_tools: boolean;
  latency_ms: number;
  tokens: Record<string, number>;
  events: AgentEvent[];
  error: string | null;
  verdict: AgentVerdict | null;
}

export interface Consensus {
  support: number;
  oppose: number;
  neutral: number;
  insufficient: number;
}

export interface Dissent {
  subsystem: string;
  why: string;
}

export interface Outcome {
  recommendation: Recommendation;
  summary: string;
  consensus: Consensus;
  dissent: Dissent[];
  conditions: string[];
  what_could_go_wrong: string[];
  rehearsal_suggestion: string;
  who_must_approve: string[];
  disclaimer: string;
  source: "model" | "deterministic_fallback";
  source_label: string;
  guard_notes: string[];
}

export interface Rehearsal {
  status: "available" | "unavailable";
  reason: string;
  steps: number;
  outcome_summary: string;
  details: Record<string, unknown>;
}

export interface HumanDecision {
  decision: Decision;
  persona: string;
  persona_label: string;
  comment: string | null;
  recorded_at_utc: string;
  routed_to: string;
  routed_to_label: string;
  notification_id: string | null;
  work_request_id: string | null;
  routing_note: string;
  executed: false;
  message: string;
}

export interface DecisionRequest {
  decision: Decision;
  persona?: string | null;
  comment?: string | null;
}

export interface DeliberationSession {
  deliberation_id: string;
  created_at_utc: string;
  completed_at_utc: string | null;
  status: SessionStatus;
  persona: string;
  request: ProposeRequest;
  case_id: string | null;
  base_window: Record<string, unknown>;
  change: ModelledChange;
  constraint_findings: ConstraintFinding[];
  agents: DelibAgentRun[];
  outcome: Outcome | null;
  rehearsal: Rehearsal | null;
  decisions: HumanDecision[];
  mode: "meta_live" | "offline";
  mode_label: string;
  meta_model: string | null;
  validation_errors: string[];
  wall_ms: number | null;
  error: string | null;
  banner: string;
  disclaimer: string;
}
