/** Typed fetch wrapper for /api/deliberation/*. Every request sends X-Persona. */
import { ApiError } from "../../api/client";
import { getPersona } from "../../plant/persona";
import type { DecisionRequest, DeliberationSession, IntentInfo, ProposeRequest } from "./types";

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

async function req<T>(
  path: string,
  opts: { method?: "GET" | "POST"; body?: unknown; signal?: AbortSignal } = {},
): Promise<T> {
  const url = `/api/deliberation${path}`;
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
  if (!res.ok) {
    const detail = await readDetail(res);
    if (res.status === 429) throw new ApiError(429, "Deliberation capacity busy; retry shortly", url);
    throw new ApiError(res.status, detail, url);
  }
  return (await res.json()) as T;
}

export const getIntents = (signal?: AbortSignal) => req<IntentInfo[]>("/intents", { signal });

export const proposeAction = (body: ProposeRequest, signal?: AbortSignal) =>
  req<DeliberationSession>("/propose", { method: "POST", body, signal });

export const getDeliberation = (id: string, signal?: AbortSignal) =>
  req<DeliberationSession>(`/${encodeURIComponent(id)}`, { signal });

export const listDeliberations = (q: { case_id?: string; limit?: number } = {}, signal?: AbortSignal) => {
  const sp = new URLSearchParams();
  if (q.case_id) sp.set("case_id", q.case_id);
  if (q.limit) sp.set("limit", String(q.limit));
  const s = sp.toString();
  return req<DeliberationSession[]>(s ? `?${s}` : "", { signal });
};

export const recordDecision = (id: string, body: DecisionRequest, signal?: AbortSignal) =>
  req<DeliberationSession>(`/${encodeURIComponent(id)}/decision`, { method: "POST", body, signal });
