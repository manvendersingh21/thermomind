/**
 * Fetch helpers for the physics simulator API (/api/simulator/*).
 * The simulator is a software model calibrated to public UCI data; no real plant is connected.
 */

export const SIM_CHANNELS = ["AT", "AP", "AH", "AFDP", "GTEP", "TIT", "TAT", "CDP", "TEY", "CO", "NOX"] as const;
export type SimChannel = (typeof SIM_CHANNELS)[number];

export type ProvenanceTag = "real_input" | "simulated" | "synthetic_fault" | string;

export interface SimInternal {
  mass_flow_kg_s?: number | null;
  fuel_kg_s?: number | null;
  shaft_mw?: number | null;
  freq_hz?: number | null;
  t_flame_k?: number | null;
}

export interface StepRecord {
  t_s: number;
  sim_hour?: number | null;
  source_year?: number | null;
  row_index?: number | null;
  AT?: number | null;
  AP?: number | null;
  AH?: number | null;
  AFDP?: number | null;
  GTEP?: number | null;
  TIT?: number | null;
  TAT?: number | null;
  CDP?: number | null;
  TEY?: number | null;
  CO?: number | null;
  NOX?: number | null;
  internal?: SimInternal | null;
  provenance?: Partial<Record<string, ProvenanceTag>> | null;
  energy_closure_pct?: number | null;
  active_faults?: string[] | null;
}

export type FaultKind =
  | "intake_fouling"
  | "compressor_fouling"
  | "hot_day"
  | "sensor_bias"
  | "sensor_drift"
  | "sensor_spike"
  | "sensor_stuck";

export const FAULT_KINDS: FaultKind[] = [
  "intake_fouling",
  "compressor_fouling",
  "hot_day",
  "sensor_bias",
  "sensor_drift",
  "sensor_spike",
  "sensor_stuck",
];

export interface ActiveFault {
  id: string;
  kind?: string;
  magnitude?: number | null;
  channel?: string | null;
  [k: string]: unknown;
}

export interface SimState {
  status?: string;
  speed?: number | null;
  record?: StepRecord | null;
  faults?: ActiveFault[] | null;
  buffer_size?: number | null;
}

export interface RunRequest {
  action: "start" | "pause" | "resume" | "stop" | "reset" | "speed";
  year?: number;
  start_index?: number;
  speed?: number;
}

export interface FaultRequest {
  kind: FaultKind;
  magnitude: number;
  channel?: string;
}

export interface RegisterWindowResponse {
  dataset_id: string;
  n_rows?: number;
  rows?: number;
  [k: string]: unknown;
}

export interface Calibration {
  per_channel_mae?: Record<string, number | null> | null;
  fitted_params?: Record<string, unknown> | null;
  notes?: string[] | null;
}

/** Thrown when the simulator routes are not mounted on the backend (HTTP 404). */
export class SimulatorUnavailable extends Error {
  constructor() {
    super("simulator backend not available");
    this.name = "SimulatorUnavailable";
  }
}

const BASE = "/api/simulator";

async function call<T>(path: string, method: "GET" | "POST" | "DELETE" = "GET", body?: unknown, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json", Accept: "application/json" } : { Accept: "application/json" },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal,
    });
  } catch (e) {
    if ((e as Error)?.name === "AbortError") throw e;
    throw new Error("Cannot reach the API. Is the backend running on :8000?");
  }
  if (res.status === 404 && (path === "/state" || path.startsWith("/history") || path === "/calibration")) {
    throw new SimulatorUnavailable();
  }
  if (!res.ok) {
    let detail = res.statusText || `HTTP ${res.status}`;
    try {
      const j = (await res.json()) as { detail?: unknown };
      if (typeof j.detail === "string") detail = j.detail;
      else if (j.detail !== undefined) detail = JSON.stringify(j.detail);
    } catch {
      /* non-JSON body */
    }
    if (res.status === 404 && detail.toLowerCase() === "not found") throw new SimulatorUnavailable();
    throw new Error(detail);
  }
  const text = await res.text();
  return (text ? JSON.parse(text) : {}) as T;
}

export const STREAM_URL = `${BASE}/stream`;

export const runSimulator = (req: RunRequest) => call<SimState>("/run", "POST", req);
export const getSimState = (signal?: AbortSignal) => call<SimState>("/state", "GET", undefined, signal);
export const getSimHistory = (n = 300, signal?: AbortSignal) =>
  call<{ records?: StepRecord[] | null }>(`/history?n=${n}`, "GET", undefined, signal);
export const injectFault = (req: FaultRequest) => call<{ id: string }>("/faults", "POST", req);
export const removeFault = (id: string) => call<unknown>(`/faults/${encodeURIComponent(id)}`, "DELETE");
export const registerWindow = (last_n: number) => call<RegisterWindowResponse>("/register-window", "POST", { last_n });
export const getCalibration = (signal?: AbortSignal) => call<Calibration>("/calibration", "GET", undefined, signal);

export function isNum(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}
