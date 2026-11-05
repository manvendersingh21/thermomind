/** Types for /api/watchdog/*. Derived from a real sample response of the backend. Everything here is SIMULATED auxiliaries. */

export type MotorState = "running" | "starting" | "standby" | "stopped" | "tripped";
export type MotorRole = "duty" | "standby" | "shared" | "single";
export type VibrationZone = "A" | "B" | "C" | "D";
export type MotorId = "CWP_A" | "CWP_B" | "BFP_A" | "BFP_B" | "CTF_1" | "CTF_2" | "CTF_3" | "LOP";
export type FaultKind = "bearing_degradation" | "insulation_degradation" | "belt_slip";

export interface MotorHistoryPoint {
  t_s: number;
  winding_c: number;
  current_a: number;
  vibration_mm_s: number;
}

export interface Motor {
  asset_id: MotorId | string;
  name: string;
  group: string;
  role: MotorRole;
  state: MotorState;
  tagged_out: boolean;
  running: boolean;
  rated_kw: number;
  voltage_v: number;
  current_a: number;
  rated_current_a: number;
  current_ratio: number;
  expected_current_a: number | null;
  load_frac: number;
  i2r_loss_kw: number;
  winding_c: number;
  alarm_c: number;
  limit_c: number;
  tau_s: number;
  bearing_c: number;
  vibration_mm_s: number;
  vibration_zone: VibrationZone | null;
  insulation_mohm: number;
  speed_ratio: number;
  loss_of_life_h: number;
  trip_reason: string | null;
  responsible_persona: string;
  history: MotorHistoryPoint[];
}

export interface AuxGroup {
  group: string;
  name: string;
  duty_from: string;
  running: number;
  capacity_frac: number;
}

export interface Switchover {
  id: string;
  group: string;
  start: string;
  stop: string;
  phase: string;
  requested_at_s: number;
  finished_at_s: number | null;
  log: string[];
}

export interface InjectedFault {
  asset_id: string;
  kind: FaultKind | string;
  severity: number;
  rate_per_min: number;
  seed: number;
  injected_at_s: number;
  note: string;
}

export interface Auxiliaries {
  simulated: boolean;
  label: string;
  t_s: number;
  ambient_c: number;
  room_offset_k: number;
  cooling_demand_frac: number;
  feedwater_demand_frac: number;
  motors: Motor[];
  groups: AuxGroup[];
  unit: Record<string, unknown>;
  switchovers: Switchover[];
  injected_faults: InjectedFault[];
}

export interface Unit {
  rated_mwh: number;
  aux_limited_mwh: number;
  cooling_capacity_frac: number;
  cw_capacity_frac: number;
  fan_airflow_frac: number;
  feedwater_capacity_frac: number;
  aux_binding: string;
  thermal_limited_mwh: number;
  thermal_binding: string;
  available_mwh: number;
  dispatch_setpoint_mwh: number;
  output_mwh: number;
  demand_step_mwh: number;
  shortfall_mwh: number;
  unit_of_measure: string;
}

export interface PolicyRow {
  action_class: string;
  policy_id: string;
  description: string;
  reversible: boolean;
  risk: string;
  where: string;
  route: string;
  responsible: string[];
}

export interface Policy {
  auto_execute_simulated_switchover: boolean;
  table: PolicyRow[];
}

export interface WatchdogSource {
  kind: string;
  label: string;
  source_year?: number;
  row_index?: number;
  replay_tick?: number;
  time_axis?: string;
  TEY_mwh?: number;
  AT_c?: number;
}

export interface ProposedAction {
  intent: string;
  action_class: string;
  magnitude: number;
  params: Record<string, unknown>;
}

export interface Detection {
  id: string;
  ts_utc: string;
  t_sim_s: number;
  kind: string;
  asset: string;
  severity: string;
  evidence: { severity?: string; signature?: string; numbers: Record<string, number | string | null>; provenance: string[] };
  rationale: string;
  proposed_action: ProposedAction;
  simulated: boolean;
  source: string;
}

export type DeliberationMode = "meta_live" | "meta_live_rejected" | "offline_fallback" | "deliberation_module";

export interface Deliberation {
  mode: DeliberationMode | string;
  mode_label: string;
  validated: boolean;
  answer: {
    recommendation: string;
    summary: string;
    harms_elsewhere: { subsystem: string; effect: string }[];
    conditions: string[];
    who_must_approve: string[];
  };
  errors: string[];
  latency_ms?: number;
}

export interface Routing {
  route: "auto_execute_simulated" | "human_required" | string;
  policy_id: string;
  reason: string;
}

export interface Proposal {
  id: string;
  ts_utc: string;
  t_sim_s: number;
  detection_id: string;
  origin: string;
  intent: string;
  action_class: string;
  magnitude: number;
  params: Record<string, unknown>;
  responsible: string[];
  reversible: boolean;
  status: string;
  deliberation: Deliberation | null;
  routing: Routing | null;
  window?: { source_year: number; start: number; end: number };
}

export type ExecutionStatus = "in_progress" | "completed" | "aborted" | "blocked_by_interlock";

export interface Execution {
  id: string;
  ts_utc: string;
  t_sim_s: number;
  proposal_id: string;
  detection_id: string;
  what: string;
  where: string;
  policy_id: string;
  approved_by: string;
  reversible: boolean;
  status: ExecutionStatus | string;
  notified: string[];
  interlocks: string[];
  simulated: boolean;
  switchover_id?: string;
  sequence_log?: string[];
  completed_t_sim_s?: number;
}

export interface HumanDecision {
  decision: string;
  persona: string;
  comment?: string | null;
  ts_utc: string;
  outcome: string;
}

export interface HumanTask {
  id: string;
  ts_utc: string;
  t_sim_s: number;
  proposal_id: string;
  detection_id: string;
  action_class: string;
  intent: string;
  magnitude: number;
  policy_id: string;
  reason: string;
  recommendation: string;
  summary: string;
  conditions: string[];
  who_must_approve: string[];
  responsible: string[];
  status: "awaiting_human" | "approved" | "rejected" | string;
  decision: HumanDecision | null;
  notified: string[];
}

export interface WatchdogNotification {
  id: string;
  ts_utc: string;
  persona: string;
  message: string;
  delivery: string;
  channel: string;
  execution_id?: string;
  proposal_id?: string;
}

export type EventType =
  | "detection"
  | "proposal"
  | "deliberation"
  | "execution"
  | "human_required"
  | "decision"
  | "notification"
  | "interlock"
  | "trip"
  | "fault_injected"
  | "demand_step"
  | "policy"
  | "control";

export interface WatchdogEvent {
  seq: number;
  ts_utc: string;
  t_sim_s: number;
  type: EventType | string;
  message: string;
  detection_id?: string;
  proposal_id?: string;
  execution_id?: string;
  task_id?: string;
  asset?: string;
}

export interface WatchdogState {
  simulated: boolean;
  honesty_statement: string;
  running: boolean;
  speed: number;
  sim_time_s: number;
  source: WatchdogSource;
  auxiliaries: Auxiliaries;
  unit: Unit;
  policy: Policy;
  deliberation_backend: string;
  deliberation_paths?: Record<string, string>;
  detections: Detection[];
  proposals: Proposal[];
  executions: Execution[];
  human_tasks: HumanTask[];
  notifications: WatchdogNotification[];
  events: WatchdogEvent[];
  counts: Record<string, number>;
}

export type RunRequest =
  | { action: "start"; speed: number }
  | { action: "stop" }
  | { action: "reset" }
  | { action: "inject_fault"; asset: string; fault: FaultKind; rate_per_min?: number; seed?: number }
  | { action: "clear_fault"; asset: string }
  | { action: "demand_step"; mwh: number }
  | { action: "set_policy"; auto_execute?: boolean; deliberation_backend?: DelibBackend }
  | { action: "tag_out"; asset: string; tagged: boolean }
  | { action: "decide"; task_id: string; decision: "approve" | "reject"; persona: string; comment?: string };

export type DelibBackend = "auto" | "builtin" | "shared";
