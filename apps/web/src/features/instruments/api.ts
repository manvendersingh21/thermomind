import { ApiError } from "../../api/client";
import type { Scorecard } from "./types";

export interface ScorecardQuery {
  dataset_id?: string;
  year: number;
  start?: number;
  end?: number;
}

export async function getScorecard(q: ScorecardQuery, signal?: AbortSignal): Promise<Scorecard> {
  const sp = new URLSearchParams();
  sp.set("dataset_id", q.dataset_id ?? "ds_uci_551");
  sp.set("year", String(q.year));
  if (q.start !== undefined) sp.set("start", String(q.start));
  if (q.end !== undefined) sp.set("end", String(q.end));
  const url = `/api/instruments/scorecard?${sp.toString()}`;
  let res: Response;
  try {
    res = await fetch(url, { headers: { Accept: "application/json" }, signal });
  } catch {
    throw new ApiError(0, `Network error: cannot reach API (${url}). Is the backend running on :8000?`, url);
  }
  if (!res.ok) {
    let detail = res.statusText || `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
      else if (body.detail !== undefined) detail = JSON.stringify(body.detail);
    } catch {
      /* non-JSON body */
    }
    throw new ApiError(res.status, detail, url);
  }
  return (await res.json()) as Scorecard;
}
