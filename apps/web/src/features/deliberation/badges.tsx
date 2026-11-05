import type { ReactNode } from "react";
import type { AgentRole, AgentRunStatus, FindingStatus, Provenance, Verdict } from "./types";

export function Chip({ children, cls = "border-ink-600 bg-white text-ink-200", title }: { children: ReactNode; cls?: string; title?: string }) {
  return (
    <span title={title} className={`inline-flex items-center gap-1 whitespace-nowrap rounded-md border px-2 py-0.5 text-xs font-semibold ${cls}`}>
      {children}
    </span>
  );
}

export const humanize = (s: string) => s.replace(/_/g, " ");

const PROV: Record<Provenance, string> = {
  real_observation: "border-green-300 bg-green-50 text-green-800",
  model_derived: "border-blue-300 bg-blue-50 text-blue-800",
  statistical_association: "border-purple-300 bg-purple-50 text-purple-800",
  derived_from_history: "border-cyan-300 bg-cyan-50 text-cyan-800",
  simulated: "border-yellow-400 bg-yellow-50 text-yellow-900",
  assumption: "border-indigo-300 bg-indigo-50 text-indigo-800",
  operator_intent: "border-pink-300 bg-pink-50 text-pink-800",
  not_observable: "border-dashed border-ink-500 bg-ink-800 text-ink-300",
};

export function ProvenanceBadge({ p }: { p: Provenance }) {
  return <Chip cls={PROV[p] ?? "border-ink-600 bg-white text-ink-200"} title={`Provenance: ${humanize(p)}`}>{humanize(p)}</Chip>;
}

const FINDING: Record<FindingStatus, string> = {
  ok: "border-green-300 bg-green-50 text-green-800",
  info: "border-ink-600 bg-ink-800 text-ink-200",
  watch: "border-amber-300 bg-amber-50 text-amber-900",
  concern: "border-orange-400 bg-orange-50 text-orange-900",
  exceeds: "border-red-300 bg-red-50 text-red-900",
  unavailable: "border-dashed border-ink-500 bg-ink-800 text-ink-400",
};

export function FindingChip({ s }: { s: FindingStatus }) {
  return <Chip cls={FINDING[s] ?? FINDING.info}>{s}</Chip>;
}

export const VERDICT_STYLE: Record<Verdict, { label: string; cls: string; bar: string }> = {
  support: { label: "support", cls: "border-green-300 bg-green-50 text-green-800", bar: "bg-green-600" },
  oppose: { label: "oppose", cls: "border-red-300 bg-red-50 text-red-800", bar: "bg-red-600" },
  neutral: { label: "neutral", cls: "border-ink-600 bg-ink-800 text-ink-200", bar: "bg-slate-400" },
  insufficient_evidence: { label: "insufficient evidence", cls: "border-amber-300 bg-amber-50 text-amber-900", bar: "bg-amber-500" },
};

export function VerdictChip({ v }: { v: Verdict }) {
  const s = VERDICT_STYLE[v] ?? VERDICT_STYLE.neutral;
  return <Chip cls={s.cls}>{s.label}</Chip>;
}

export const ROLE_STYLE: Record<AgentRole, string> = {
  subsystem: "border-blue-200 bg-blue-50 text-blue-800",
  constraints: "border-purple-200 bg-purple-50 text-purple-800",
  aggregator: "border-teal-200 bg-teal-50 text-teal-800",
};

export const RUN_STATUS_STYLE: Record<AgentRunStatus, string> = {
  pending: "border-ink-600 bg-ink-800 text-ink-300",
  running: "border-blue-300 bg-blue-50 text-blue-800",
  done: "border-green-300 bg-green-50 text-green-800",
  failed: "border-red-300 bg-red-50 text-red-800",
};
