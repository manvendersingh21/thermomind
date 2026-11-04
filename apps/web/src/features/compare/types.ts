/** Client-side view models for the case comparison page. No backend contract is added here. */
import type { Evidence, HypothesisStatus } from "../../api/types";

export type CaseSide = "A" | "B";

export interface HypothesisCell {
  rank: number;
  status: HypothesisStatus;
  supporting: number;
  contradicting: number;
}

export interface HypothesisDiffRow {
  /** Hypothesis key (or a slug of the name when the report gave no key). */
  key: string;
  name: string;
  a: HypothesisCell | null;
  b: HypothesisCell | null;
  /** Rank or status differs, or the hypothesis is missing on one side. */
  differs: boolean;
}

/** Display bands for |z_B - z_A|. Presentation only, not decision thresholds. */
export type ZBand = "none" | "small" | "moderate" | "large";

export interface SharedEvidenceRow {
  id: string;
  metric: string;
  unit: string;
  title: string;
  a: Evidence;
  b: Evidence;
  /** z_B - z_A, or null when either z is missing. */
  zDelta: number | null;
  band: ZBand;
}

export interface EvidenceDiff {
  shared: SharedEvidenceRow[];
  onlyA: Evidence[];
  onlyB: Evidence[];
}

export interface ToolCallStep {
  seq: number;
  tool: string;
  ok: boolean;
}

export interface ToolCount {
  tool: string;
  count: number;
  failed: number;
}

export interface ToolCallSummary {
  sequence: ToolCallStep[];
  counts: ToolCount[];
  total: number;
  failed: number;
}

export interface DataQualityRow {
  label: string;
  a: string[];
  b: string[];
  /** Whether the two sides hold different sets of entries. */
  differs: boolean;
}
