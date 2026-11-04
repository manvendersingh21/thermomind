import type {
  CmmsDrafts,
  ConnectorsStatus,
  HistorianCursor,
  HistorianLatest,
  HistorianStartRequest,
  Outbox,
} from "./types";

const BASE = "/api/connectors";

async function call<T>(path: string, method: "GET" | "POST" = "GET", body?: unknown, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json", Accept: "application/json" } : { Accept: "application/json" },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal,
    });
  } catch {
    throw new Error("Cannot reach the API. Is the backend running on :8000?");
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
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

export const getConnectorsStatus = (signal?: AbortSignal) => call<ConnectorsStatus>("/status", "GET", undefined, signal);
export const getHistorianLatest = (n = 20, signal?: AbortSignal) =>
  call<HistorianLatest>(`/historian/latest?n=${n}`, "GET", undefined, signal);
export const startHistorian = (req: HistorianStartRequest) =>
  call<{ cursor: HistorianCursor }>("/historian/start", "POST", req);
export const stopHistorian = () => call<{ cursor: HistorianCursor }>("/historian/stop", "POST");
export const getCmmsDrafts = (signal?: AbortSignal) => call<CmmsDrafts>("/cmms/drafts", "GET", undefined, signal);
export const createCmmsDraft = (title: string, description: string) =>
  call<{ id: string; status: string }>("/cmms/drafts", "POST", { title, description });
export const getOutbox = (signal?: AbortSignal) => call<Outbox>("/notifications/outbox", "GET", undefined, signal);
