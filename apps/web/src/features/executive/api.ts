/** Typed fetch wrappers for /api/executive/*. */
import { ApiError } from "../../api/client";
import type { ExecutiveBrief, ExecutiveOverview } from "./types";

const BASE = "/api/executive";

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

async function json<T>(path: string, init: RequestInit & { timeoutMs?: number } = {}): Promise<T> {
  const url = `${BASE}${path}`;
  const controller = new AbortController();
  const timer = init.timeoutMs ? window.setTimeout(() => controller.abort(), init.timeoutMs) : null;
  let res: Response;
  try {
    res = await fetch(url, {
      ...init,
      headers: { Accept: "application/json", ...(init.headers ?? {}) },
      signal: init.signal ?? controller.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw new ApiError(0, "Request aborted or timed out", url);
    throw new ApiError(0, `Network error: cannot reach API (${url}). Is the backend running?`, url);
  } finally {
    if (timer) window.clearTimeout(timer);
  }
  if (!res.ok) throw new ApiError(res.status, await readDetail(res), url);
  return (await res.json()) as T;
}

export const getExecutiveOverview = (year: number, signal?: AbortSignal) =>
  json<ExecutiveOverview>(`/overview?year=${encodeURIComponent(String(year))}`, { signal });

/** One Muse Spark call (+ at most one rewrite); reasoning model, so allow several minutes. */
export const createExecutiveBrief = (year: number) =>
  json<ExecutiveBrief>("/brief", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ year }),
    timeoutMs: 300_000,
  });

export const listExecutiveBriefs = (limit = 5, signal?: AbortSignal) =>
  json<ExecutiveBrief[]>(`/briefs?limit=${limit}`, { signal });
