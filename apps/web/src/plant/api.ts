/** Typed fetch wrapper for /api/plant/*. Every request sends X-Persona. */
import { ApiError } from "../api/client";
import type { Investigation } from "../api/types";
import { getPersona } from "./persona";
import type {
  InboxResponse,
  MeasurementInfo,
  Notification,
  PersonasResponse,
  PrecedentsResponse,
  Sensitivity,
  Subsystem,
  WhatIfRequest,
  WhatIfSession,
  WorkRequest,
  WorkRequestStatus,
} from "./types";

export { ApiError, errorMessage } from "../api/client";

async function readDetail(res: Response): Promise<string> {
  const text = await res.text().catch(() => "");
  if (!text) return res.statusText || `HTTP ${res.status}`;
  try {
    const parsed = JSON.parse(text) as { detail?: unknown };
    if (typeof parsed.detail === "string") return parsed.detail;
    if (parsed.detail !== undefined) return JSON.stringify(parsed.detail);
  } catch {
    /* non-JSON */
  }
  return text.slice(0, 400);
}

async function req<T>(path: string, opts: { method?: "GET" | "POST"; body?: unknown; signal?: AbortSignal } = {}): Promise<T> {
  const url = `/api${path}`;
  const headers: Record<string, string> = { Accept: "application/json", "X-Persona": getPersona() };
  let body: string | undefined;
  if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(url, { method: opts.method ?? "GET", headers, body, signal: opts.signal });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw new ApiError(0, "Request aborted", url);
    throw new ApiError(0, `Network error: cannot reach API (${url}). Is the backend running on :8000?`, url);
  }
  if (!res.ok) throw new ApiError(res.status, await readDetail(res), url);
  return (await res.json()) as T;
}

function qs(params: Record<string, string | number | undefined | null>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export const getPersonas = (signal?: AbortSignal) => req<PersonasResponse>("/plant/personas", { signal });
export const getSubsystems = (signal?: AbortSignal) => req<Subsystem[]>("/plant/subsystems", { signal });
export const getMeasurements = (signal?: AbortSignal) => req<MeasurementInfo[]>("/plant/measurements", { signal });

export const getInbox = (persona?: string, signal?: AbortSignal) =>
  req<InboxResponse>(`/plant/inbox${qs({ persona })}`, { signal });

export const markNotificationRead = (id: string) =>
  req<Notification>(`/plant/notifications/${encodeURIComponent(id)}/read`, { method: "POST" });

export const listWorkRequests = (
  q: { persona?: string; status?: WorkRequestStatus; case_id?: string } = {},
  signal?: AbortSignal,
) => req<WorkRequest[]>(`/plant/work-requests${qs(q)}`, { signal });

export const updateWorkRequestStatus = (id: string, status: Exclude<WorkRequestStatus, "open">, comment?: string) =>
  req<WorkRequest>(`/plant/work-requests/${encodeURIComponent(id)}/status`, {
    method: "POST",
    body: { status, comment: comment && comment.trim() ? comment.trim() : null },
  });

export const getSensitivity = (measurement: string, delta: number, caseId?: string, signal?: AbortSignal) =>
  req<Sensitivity>(`/plant/sensitivity${qs({ measurement, delta, case_id: caseId })}`, { signal });

export const startWhatIf = (body: WhatIfRequest) =>
  req<WhatIfSession>("/plant/whatif", { method: "POST", body });

export const getWhatIf = (sessionId: string, signal?: AbortSignal) =>
  req<WhatIfSession>(`/plant/whatif/${encodeURIComponent(sessionId)}`, { signal });

export const listWhatIf = (limit = 20, signal?: AbortSignal) =>
  req<WhatIfSession[]>(`/plant/whatif${qs({ limit })}`, { signal });

export const getPrecedents = (caseId: string, signal?: AbortSignal) =>
  req<PrecedentsResponse>(`/plant/precedents${qs({ case_id: caseId })}`, { signal });

export const listInvestigationsForPicker = (signal?: AbortSignal) => req<Investigation[]>("/investigations", { signal });
