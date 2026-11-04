/** Typed fetch wrappers for /api/collab/*. Read-only decision support; POSTs only write log rows. */
import { ApiError } from "../../api/client";
import type {
  ActivityResponse,
  ApplyExistingResponse,
  AutoDecision,
  DecisionsResponse,
  DependencyGraph,
  LatestOnboarding,
  OnboardingBrief,
  PolicyResponse,
} from "./types";

const BASE = "/api/collab";

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
  const outer = init.signal;
  const onOuterAbort = () => controller.abort();
  if (outer) {
    if (outer.aborted) controller.abort();
    else outer.addEventListener("abort", onOuterAbort);
  }
  let res: Response;
  try {
    res = await fetch(url, {
      ...init,
      signal: controller.signal,
      headers: { Accept: "application/json", ...(init.headers ?? {}) },
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw new ApiError(0, "Request aborted or timed out", url);
    throw new ApiError(0, `Network error: cannot reach API (${url}). Is the backend running on :8000?`, url);
  } finally {
    if (timer) window.clearTimeout(timer);
    outer?.removeEventListener("abort", onOuterAbort);
  }
  if (!res.ok) throw new ApiError(res.status, await readDetail(res), url);
  return (await res.json()) as T;
}

function qs(params: Record<string, string | number | undefined | null>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

const post = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const getPolicy = (signal?: AbortSignal) => json<PolicyResponse>("/policy", { signal });

export const listDecisions = (opts: { caseId?: string; limit?: number } = {}, signal?: AbortSignal) =>
  json<DecisionsResponse>(`/decisions${qs({ case_id: opts.caseId, limit: opts.limit })}`, { signal });

export const reopenDecision = (decisionId: string, body: { persona?: string; comment?: string }) =>
  json<AutoDecision>(`/decisions/${encodeURIComponent(decisionId)}/reopen`, post(body));

export const applyPolicyToExisting = () => json<ApplyExistingResponse>("/policy/apply-existing", post({}));

export const getCaseActivity = (caseId: string, signal?: AbortSignal) =>
  json<ActivityResponse>(`/cases/${encodeURIComponent(caseId)}/activity`, { signal });

export const getDependencyGraph = (
  opts: { caseId?: string; measurement?: string; delta?: number } = {},
  signal?: AbortSignal,
) =>
  json<DependencyGraph>(
    `/dependency-graph${qs({ case_id: opts.caseId, measurement: opts.measurement, delta: opts.delta })}`,
    { signal },
  );

/** Synchronous on the server; live Meta drafting can take 60-120 s. */
export const generateOnboarding = (persona: string) =>
  json<OnboardingBrief>("/onboarding", { ...post({ persona }), timeoutMs: 300_000 });

export const getLatestOnboarding = (persona: string, signal?: AbortSignal) =>
  json<LatestOnboarding>(`/onboarding${qs({ persona })}`, { signal });
