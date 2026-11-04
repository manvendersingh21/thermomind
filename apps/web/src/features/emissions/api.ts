/** Typed fetch wrappers for /api/emissions/*. */
import { ApiError } from "../../api/client";
import type { EmissionsQuery, EmissionsResponse, EmissionsWindowQuery } from "./types";

export { errorMessage } from "../../api/client";

async function readDetail(res: Response): Promise<string> {
  const text = await res.text().catch(() => "");
  if (!text) return res.statusText || `HTTP ${res.status}`;
  try {
    const parsed = JSON.parse(text) as { detail?: unknown };
    if (typeof parsed.detail === "string") return parsed.detail;
    if (parsed.detail !== undefined) return JSON.stringify(parsed.detail);
  } catch {
    /* non-JSON body */
  }
  return text.slice(0, 400);
}

function qs(params: Record<string, string | number | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && !(typeof v === "number" && Number.isNaN(v))) sp.set(k, String(v));
  }
  return `?${sp.toString()}`;
}

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const url = `/api${path}`;
  let res: Response;
  try {
    res = await fetch(url, { headers: { Accept: "application/json" }, signal });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw new ApiError(0, "Request aborted", url);
    throw new ApiError(0, `Network error: cannot reach API (${url}). Is the backend running on :8000?`, url);
  }
  if (!res.ok) throw new ApiError(res.status, await readDetail(res), url);
  return (await res.json()) as T;
}

export const getEmissionsOverview = (q: EmissionsQuery, signal?: AbortSignal) =>
  get<EmissionsResponse>(
    `/emissions/overview${qs({
      dataset_id: q.dataset_id ?? "ds_uci_551",
      year: q.year,
      co_threshold: q.co_threshold,
      nox_threshold: q.nox_threshold,
    })}`,
    signal,
  );

export const getEmissionsWindow = (q: EmissionsWindowQuery, signal?: AbortSignal) =>
  get<EmissionsResponse>(
    `/emissions/window${qs({
      dataset_id: q.dataset_id ?? "ds_uci_551",
      year: q.year,
      start: q.start,
      end: q.end,
      co_threshold: q.co_threshold,
      nox_threshold: q.nox_threshold,
    })}`,
    signal,
  );
