/**
 * Typed fetch wrappers for every endpoint in contracts/api.md.
 * All requests go to `/api/...` (Vite proxies to http://localhost:8000 in dev).
 */
import type {
  DatasetDetail,
  DatasetSummary,
  DemoStatus,
  Evidence,
  Health,
  Investigation,
  InvestigationCreated,
  InvestigationRequest,
  ModelComparison,
  ModelEvaluation,
  ReviewRequest,
  ScenarioInfo,
  ScenarioPreviewRequest,
  ScenarioPreviewResponse,
  SeriesResponse,
  TrainRequest,
  UploadResult,
} from "./types";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  readonly url: string;

  constructor(status: number, detail: string, url: string) {
    super(`${status}: ${detail}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.url = url;
  }
}

export function isApiError(err: unknown): err is ApiError {
  return err instanceof ApiError;
}

export function errorMessage(err: unknown): string {
  if (isApiError(err)) return err.detail;
  if (err instanceof Error) return err.message;
  return String(err);
}

const BASE = "/api";

interface RequestOptions {
  method?: "GET" | "POST";
  body?: unknown;
  formData?: FormData;
  signal?: AbortSignal;
  timeoutMs?: number;
}

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

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const url = `${BASE}${path}`;
  const headers: Record<string, string> = { Accept: "application/json" };
  let body: BodyInit | undefined;
  if (opts.formData) {
    body = opts.formData;
  } else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }

  const controller = new AbortController();
  const timer = opts.timeoutMs ? window.setTimeout(() => controller.abort(), opts.timeoutMs) : null;
  const signal = opts.signal ?? controller.signal;

  let res: Response;
  try {
    res = await fetch(url, { method: opts.method ?? "GET", headers, body, signal });
  } catch (err) {
    if (timer) window.clearTimeout(timer);
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ApiError(0, "Request aborted or timed out", url);
    }
    throw new ApiError(0, `Network error: cannot reach API (${url}). Is the backend running on :8000?`, url);
  }
  if (timer) window.clearTimeout(timer);

  if (!res.ok) {
    throw new ApiError(res.status, await readDetail(res), url);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

function qs(params: Record<string, string | number | boolean | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined) sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

// --- health / status --------------------------------------------------------

export const getHealth = (signal?: AbortSignal) => request<Health>("/health", { signal });
export const getDemoStatus = (signal?: AbortSignal) => request<DemoStatus>("/demo/status", { signal });

// --- datasets ---------------------------------------------------------------

export const listDatasets = (signal?: AbortSignal) => request<DatasetSummary[]>("/datasets", { signal });

export const seedUci = () => request<DatasetSummary>("/datasets/seed-uci", { method: "POST" });

export function uploadDataset(file: File): Promise<UploadResult> {
  const fd = new FormData();
  fd.append("file", file, file.name);
  return request<UploadResult>("/datasets/upload", { method: "POST", formData: fd });
}

export const getDataset = (datasetId: string, signal?: AbortSignal) =>
  request<DatasetDetail>(`/datasets/${encodeURIComponent(datasetId)}`, { signal });

export interface SeriesQuery {
  measure: string;
  year: number;
  start?: number;
  limit?: number;
  include_expected?: boolean;
}

export const getSeries = (datasetId: string, q: SeriesQuery, signal?: AbortSignal) =>
  request<SeriesResponse>(
    `/datasets/${encodeURIComponent(datasetId)}/series${qs({
      measure: q.measure,
      year: q.year,
      start: q.start,
      limit: q.limit,
      include_expected: q.include_expected,
    })}`,
    { signal },
  );

// --- models -----------------------------------------------------------------

export const getModelEvaluation = (signal?: AbortSignal) =>
  request<ModelEvaluation>("/models/evaluation", { signal });

/** 404 until the comparison endpoint is wired / challengers are trained. */
export const getModelComparison = (signal?: AbortSignal) =>
  request<ModelComparison>("/models/comparison", { signal });

export const trainModel = (body: TrainRequest = {}) =>
  request<ModelEvaluation>("/models/train", { method: "POST", body, timeoutMs: 600_000 });

// --- scenarios --------------------------------------------------------------

export const listScenarios = (signal?: AbortSignal) => request<ScenarioInfo[]>("/scenarios", { signal });

export const previewScenario = (body: ScenarioPreviewRequest, signal?: AbortSignal) =>
  request<ScenarioPreviewResponse>("/scenarios/preview", { method: "POST", body, signal });

// --- investigations ---------------------------------------------------------

/** Synchronous on the server: may take 30–120 s when Meta is used. */
export const createInvestigation = (body: InvestigationRequest) =>
  request<InvestigationCreated>("/investigations", { method: "POST", body, timeoutMs: 420_000 });

export const listInvestigations = (signal?: AbortSignal) =>
  request<Investigation[]>("/investigations", { signal });

export const getInvestigation = (caseId: string, signal?: AbortSignal) =>
  request<Investigation>(`/investigations/${encodeURIComponent(caseId)}`, { signal });

export const listEvidence = (caseId: string, signal?: AbortSignal) =>
  request<Evidence[]>(`/investigations/${encodeURIComponent(caseId)}/evidence`, { signal });

export const getEvidence = (caseId: string, evidenceId: string, signal?: AbortSignal) =>
  request<Evidence>(
    `/investigations/${encodeURIComponent(caseId)}/evidence/${encodeURIComponent(evidenceId)}`,
    { signal },
  );

export const submitReview = (caseId: string, body: ReviewRequest) =>
  request<Investigation>(`/investigations/${encodeURIComponent(caseId)}/review`, { method: "POST", body });

export const exportUrl = (caseId: string) => `${BASE}/investigations/${encodeURIComponent(caseId)}/export.json`;
