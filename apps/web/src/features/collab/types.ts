/** Types for /api/collab/* (policy, decisions, activity, dependency graph, onboarding). */
export type AutonomyLevel = "agent_auto" | "human_review" | "human_only";

export interface PolicyAction {
  action_id: string;
  action: string;
  level: AutonomyLevel;
  actor: string;
  why: string;
  reversible: boolean;
  link: string | null;
}

export interface DecisionCounts {
  auto_triaged_no_action: number;
  requires_human: number;
  human_override_reopened: number;
  total: number;
}

export interface PolicyResponse {
  policy_id: string;
  title: string;
  levels: Record<AutonomyLevel, string>;
  actions: PolicyAction[];
  auto_triage_conditions: string[];
  counts: DecisionCounts;
  note: string;
}

export interface PolicyCondition {
  name: string;
  passed: boolean;
  detail: string;
}

export type DecisionKind = "auto_triaged_no_action" | "requires_human" | "human_override_reopened";

export interface AutoDecision {
  decision_id: string;
  case_id: string;
  decision: DecisionKind;
  reason: string;
  policy_id: string;
  ts_utc: string;
  reversible: boolean;
  actor: string;
  routed_personas: string[];
  conditions: PolicyCondition[];
  synthetic: boolean;
  severity: string | null;
  supersedes: string | null;
}

export interface DecisionsResponse {
  decisions: AutoDecision[];
  counts: DecisionCounts;
}

export interface ApplyExistingResponse {
  applied: number;
  already_decided: number;
  decisions: AutoDecision[];
}

export type ActorKind = "agent" | "persona" | "human" | "system";

export interface ActivityItem {
  ts_utc: string;
  actor: string;
  actor_kind: ActorKind;
  kind: string;
  summary: string;
  link: string | null;
}

export interface ActivityResponse {
  case_id: string;
  items: ActivityItem[];
  sources: Record<string, boolean>;
  note: string;
}

export interface GraphNode {
  id: string;
  kind: "subsystem" | "measurement";
  label: string;
  layer: number;
  subsystem: string | null;
  unit: string | null;
  owner_persona: string | null;
  owner_label: string | null;
  description: string | null;
  how_it_works: string | null;
  what_to_check: string[];
  implicated: boolean;
  on_path: boolean;
  stat_neighbour: boolean;
}

export interface GraphEdge {
  source: string;
  target: string;
  kind: "physical" | "membership" | "statistical";
  r: number | null;
  slope: number | null;
  label: string;
  on_path: boolean;
}

export interface WhatIfAnnotation {
  measurement: string;
  delta: number;
  unit: string;
  applicable: boolean;
  delta_tey_mean: number | null;
  delta_tey_min: number | null;
  delta_tey_max: number | null;
  ood_flag: boolean | null;
  note: string;
  label: string;
}

export interface DependencyGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  implicated: { subsystem: string; measurement: string; reason: string } | null;
  domino_path: string[];
  whatif: WhatIfAnnotation | null;
  caveat: string;
  threshold: number;
  training_years: number[];
  case_id: string | null;
  synthetic: boolean | null;
}

export interface OnboardingBriefBody {
  role_summary: string;
  how_the_plant_works: { subsystem: string; explanation: string }[];
  what_you_watch: { measurement: string; why: string }[];
  who_you_work_with: { persona: string; when: string }[];
  current_open_items: string[];
  first_week_checklist: string[];
  disclaimer: string;
}

export interface OnboardingBrief {
  brief_id: string;
  persona: string;
  created_at_utc: string;
  mode: "meta_live" | "offline_fallback";
  meta_used: boolean;
  meta_model: string | null;
  meta_calls: number;
  rewrite_used: boolean;
  fallback_reason: string | null;
  validation_errors: string[];
  source_label: string;
  badge: string;
  brief: OnboardingBriefBody;
  latency_ms: number | null;
  tokens: Record<string, number>;
}

export interface LatestOnboarding {
  persona: string;
  brief: OnboardingBrief | null;
}
