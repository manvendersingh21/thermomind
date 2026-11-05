/** Typed fetch wrappers for /api/watchdog/*. Everything controllable here acts on a SIMULATED auxiliaries model only. */
import { ApiError } from "../../api/client";
import type { RunRequest, WatchdogState } from "./types";

export { errorMessage } from "../../api/client";

async function readDetail(res: Response): Promise<string> {
  const text = await res.text().catch(() => "");
  if (!text) return res.statusText || `HTTP ${res.status}`;
  try {
    const parsed = JSON.parse(text) as { detail?: unknown };
    if (typeof parsed.detail === "string") return parsed.detail;
    if (Array.isArray(parsed.detail)) {
      return parsed.detail
        .map((d) => {
          const e = d as { loc?: unknown[]; msg?: string };
          return `${(e.loc ?? []).slice(1).join(".")}: ${e.msg ?? ""}`;
        })
        .join("; ");
    }
    if (parsed.detail !== undefined) return JSON.stringify(parsed.detail);
  } catch {
    /* non-JSON body */
  }
  return text.slice(0, 400);
}

async function call<T>(path: string, init: RequestInit, signal?: AbortSignal): Promise<T> {
  const url = `/api${path}`;
  let res: Response;
  try {
    res = await fetch(url, { ...init, headers: { Accept: "application/json", ...(init.headers ?? {}) }, signal });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw new ApiError(0, "Request aborted", url);
    throw new ApiError(0, `Network error: cannot reach API (${url}). Is the backend running on :8000?`, url);
  }
  if (!res.ok) throw new ApiError(res.status, await readDetail(res), url);
  return (await res.json()) as T;
}

export const getWatchdogState = (signal?: AbortSignal, historyPoints = 60, nEvents = 60) =>
  call<WatchdogState>(`/watchdog/state?history_points=${historyPoints}&n_events=${nEvents}`, { method: "GET" }, signal);

export const runWatchdog = (body: RunRequest, signal?: AbortSignal) =>
  call<unknown>(
    "/watchdog/run",
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) },
    signal,
  );

export const WATCHDOG_STREAM_URL = "/api/watchdog/stream?interval_s=1";
