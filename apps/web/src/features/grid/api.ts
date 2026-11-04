/** Fetch wrappers for /api/grid/* (uses the shared ApiError so ErrorBanner renders details). */
import { ApiError } from "../../api/client";
import type { ContingencyRequest, ContingencyResult, DrillRequest, GridDrill, GridReadiness, ReadinessQuery } from "./types";

async function call<T>(path: string, init: { method?: "GET" | "POST"; body?: unknown; signal?: AbortSignal; timeoutMs?: number } = {}): Promise<T> {
  const url = `/api${path}`;
  const controller = new AbortController();
  const timer = init.timeoutMs ? window.setTimeout(() => controller.abort(), init.timeoutMs) : null;
  let res: Response;
  try {
    res = await fetch(url, {
      method: init.method ?? "GET",
      headers: init.body !== undefined ? { Accept: "application/json", "Content-Type": "application/json" } : { Accept: "application/json" },
      body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
      signal: init.signal ?? controller.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw new ApiError(0, "Request aborted or timed out", url);
    throw new ApiError(0, `Network error: cannot reach API (${url}).`, url);
  } finally {
    if (timer) window.clearTimeout(timer);
  }
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    let detail = text || res.statusText || `HTTP ${res.status}`;
    try {
      const parsed = JSON.parse(text) as { detail?: unknown };
      if (parsed.detail !== undefined) detail = typeof parsed.detail === "string" ? parsed.detail : JSON.stringify(parsed.detail);
    } catch {
      /* non-JSON body */
    }
    throw new ApiError(res.status, detail.slice(0, 600), url);
  }
  return (await res.json()) as T;
}

export function getReadiness(q: ReadinessQuery, signal?: AbortSignal): Promise<GridReadiness> {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  return call<GridReadiness>(`/grid/readiness?${sp.toString()}`, { signal });
}

/** Synchronous; up to two Muse Spark calls when use_meta is true. */
export const runDrill = (body: DrillRequest) => call<GridDrill>("/grid/drill", { method: "POST", body, timeoutMs: 420_000 });

export const listDrills = (signal?: AbortSignal) => call<GridDrill[]>("/grid/drills?limit=10", { signal });

export const getContingency = (body: ContingencyRequest) =>
  call<ContingencyResult>("/grid/contingency", { method: "POST", body });
