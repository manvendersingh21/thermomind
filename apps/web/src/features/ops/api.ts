/** Typed fetch wrappers for /api/ops/* (handover draft, CMMS draft export, prototype metrics). */
import { ApiError } from "../../api/client";
import type { CmmsExport, HandoverNote, HandoverRequest, OpsMetrics } from "./types";

const BASE = "/api/ops";

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

async function call(path: string, init: RequestInit & { timeoutMs?: number } = {}): Promise<Response> {
  const url = `${BASE}${path}`;
  const controller = new AbortController();
  const timer = init.timeoutMs ? window.setTimeout(() => controller.abort(), init.timeoutMs) : null;
  let res: Response;
  try {
    res = await fetch(url, { ...init, signal: init.signal ?? controller.signal });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw new ApiError(0, "Request aborted or timed out", url);
    throw new ApiError(0, `Network error: cannot reach API (${url}). Is the backend running on :8000?`, url);
  } finally {
    if (timer) window.clearTimeout(timer);
  }
  if (!res.ok) throw new ApiError(res.status, await readDetail(res), url);
  return res;
}

async function json<T>(path: string, init: RequestInit & { timeoutMs?: number } = {}): Promise<T> {
  const res = await call(path, { ...init, headers: { Accept: "application/json", ...(init.headers ?? {}) } });
  return (await res.json()) as T;
}

/** Synchronous on the server: up to two Meta calls (draft + one bounded rewrite). */
export const createHandover = (body: HandoverRequest) =>
  json<HandoverNote>("/handover", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    timeoutMs: 360_000,
  });

export const listHandovers = (signal?: AbortSignal) => json<HandoverNote[]>("/handover?limit=20", { signal });

export const getHandover = (noteId: string, signal?: AbortSignal) =>
  json<HandoverNote>(`/handover/${encodeURIComponent(noteId)}`, { signal });

const personaQs = (persona?: string) => (persona ? `?persona=${encodeURIComponent(persona)}` : "");

export const cmmsJsonUrl = (caseId: string, persona?: string) =>
  `${BASE}/cmms/${encodeURIComponent(caseId)}.json${personaQs(persona)}`;

export const cmmsCsvUrl = (caseId: string, persona?: string) =>
  `${BASE}/cmms/${encodeURIComponent(caseId)}.csv${personaQs(persona)}`;

export const getCmmsJson = (caseId: string, persona?: string, signal?: AbortSignal) =>
  json<CmmsExport>(`/cmms/${encodeURIComponent(caseId)}.json${personaQs(persona)}`, { signal });

export async function getCmmsCsv(caseId: string, persona?: string, signal?: AbortSignal): Promise<string> {
  const res = await call(`/cmms/${encodeURIComponent(caseId)}.csv${personaQs(persona)}`, { signal });
  return res.text();
}

export const getOpsMetrics = (signal?: AbortSignal) => json<OpsMetrics>("/metrics", { signal });
