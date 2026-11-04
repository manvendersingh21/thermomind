/** Fetch wrapper for /api/agents/tree (shared ApiError so ErrorBanner renders details). */
import { ApiError } from "../../api/client";
import type { AgentTree } from "./types";

export async function getAgentTree(signal?: AbortSignal): Promise<AgentTree> {
  const url = "/api/agents/tree";
  let res: Response;
  try {
    res = await fetch(url, { headers: { Accept: "application/json" }, signal });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw new ApiError(0, "Request aborted", url);
    throw new ApiError(0, `Network error: cannot reach API (${url}). Is the backend running on :8000?`, url);
  }
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    let detail = text.slice(0, 400) || res.statusText;
    try {
      const parsed = JSON.parse(text) as { detail?: unknown };
      if (typeof parsed.detail === "string") detail = parsed.detail;
    } catch {
      /* non-JSON */
    }
    throw new ApiError(res.status, detail, url);
  }
  return (await res.json()) as AgentTree;
}
