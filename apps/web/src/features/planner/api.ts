/** Typed fetch wrappers for /api/planner/*. */
import { ApiError } from "../../api/client";
import type {
  CompressorWashRequest,
  CompressorWashResult,
  FilterChangeoutRequest,
  FilterChangeoutResult,
  PlannerOptions,
} from "./types";

async function readDetail(res: Response): Promise<string> {
  const text = await res.text().catch(() => "");
  if (!text) return res.statusText || `HTTP ${res.status}`;
  try {
    const parsed = JSON.parse(text) as { detail?: unknown };
    if (typeof parsed.detail === "string") return parsed.detail;
    if (Array.isArray(parsed.detail)) {
      // FastAPI validation errors: [{loc: [...], msg: "..."}]
      return parsed.detail
        .map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).slice(1).join(".")}: ${d.msg ?? "invalid"}`)
        .join("; ");
    }
    if (parsed.detail !== undefined) return JSON.stringify(parsed.detail);
  } catch {
    /* non-JSON body */
  }
  return text.slice(0, 400);
}

async function call<T>(path: string, init: { method?: "GET" | "POST"; body?: unknown; signal?: AbortSignal } = {}): Promise<T> {
  const url = `/api${path}`;
  const headers: Record<string, string> = { Accept: "application/json" };
  if (init.body !== undefined) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(url, {
      method: init.method ?? "GET",
      headers,
      body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
      signal: init.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw new ApiError(0, "Request aborted", url);
    throw new ApiError(0, `Network error: cannot reach API (${url}). Is the backend running on :8000?`, url);
  }
  if (!res.ok) throw new ApiError(res.status, await readDetail(res), url);
  return (await res.json()) as T;
}

export const getPlannerOptions = (signal?: AbortSignal) => call<PlannerOptions>("/planner/options", { signal });

export const runCompressorWash = (body: CompressorWashRequest, signal?: AbortSignal) =>
  call<CompressorWashResult>("/planner/compressor-wash", { method: "POST", body, signal });

export const runFilterChangeout = (body: FilterChangeoutRequest, signal?: AbortSignal) =>
  call<FilterChangeoutResult>("/planner/filter-changeout", { method: "POST", body, signal });
