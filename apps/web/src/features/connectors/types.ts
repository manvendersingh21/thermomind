export type ConnectorMode = "simulated" | "not_connected";

export interface ConnectorInfo {
  name: string;
  kind: "historian" | "cmms" | "notifier" | "control_system";
  mode: ConnectorMode;
  description: string;
  real_adapter_needs: string[];
  detail: Record<string, unknown>;
}

export interface ConnectorsStatus {
  simulated: boolean;
  read_only: boolean;
  time_axis: string;
  connectors: ConnectorInfo[];
}

export interface HistorianCursor {
  running: boolean;
  finished: boolean;
  started: boolean;
  source_year: number | null;
  row_index: number | null;
  start_index: number | null;
  replay_tick: number;
  advance_rate: number;
  rows_in_year: number | null;
  simulated: boolean;
  time_axis: string;
}

/** One replayed UCI row: measurements plus ordering fields. No timestamp by design. */
export interface HistorianRow {
  replay_tick: number;
  source_year: number;
  row_index: number;
  [measurement: string]: number | null;
}

export interface HistorianLatest {
  simulated: boolean;
  time_axis: string;
  cursor: HistorianCursor;
  rows: HistorianRow[];
}

export interface HistorianStartRequest {
  year: number;
  advance_rate: number;
  start_index: number;
}

export interface CmmsDraft {
  id: string;
  status: string;
  simulated: boolean;
  payload: { title?: string; description?: string; case_id?: string | null; subsystem?: string | null };
  drafted_at_utc: string;
  note: string;
}

export interface CmmsDrafts {
  simulated: boolean;
  submit_supported: boolean;
  drafts: CmmsDraft[];
}

export interface OutboxItem {
  id: string;
  persona: string;
  message: string;
  delivery: string;
  source: string;
  simulated: boolean;
  created_at_utc: string;
}

export interface Outbox {
  simulated: boolean;
  delivery: string;
  notifications: OutboxItem[];
}
