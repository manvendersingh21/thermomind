import type { HypothesisStatus, InvestigationStatus, Severity } from "../api/types";

const INV: Record<InvestigationStatus, string> = {
  queued: "border-ink-600 bg-ink-800 text-ink-200",
  running: "border-blue-300 bg-blue-50 text-blue-800",
  completed: "border-green-300 bg-green-50 text-green-800",
  needs_review: "border-amber-400 bg-yellow-100 text-amber-800",
  failed: "border-red-300 bg-red-50 text-red-800",
};

const HYP: Record<HypothesisStatus, string> = {
  possible: "border-amber-400 bg-yellow-100 text-amber-800",
  inconclusive: "border-ink-600 bg-ink-800 text-ink-200",
  not_supported: "border-green-300 bg-green-50 text-green-800",
};

const SEV: Record<Severity, string> = {
  informational: "border-green-300 bg-green-50 text-green-800",
  review: "border-amber-400 bg-yellow-100 text-amber-800",
  urgent_review: "border-red-300 bg-red-50 text-red-800",
};

function pill(cls: string, text: string) {
  return (
    <span className={`inline-flex items-center rounded-md border px-2 py-0.5 text-sm font-semibold uppercase tracking-wide ${cls}`}>
      {text.replace(/_/g, " ")}
    </span>
  );
}

export const InvestigationStatusPill = ({ status }: { status: InvestigationStatus }) => pill(INV[status], status);
export const HypothesisStatusPill = ({ status }: { status: HypothesisStatus }) => pill(HYP[status], status);
export const SeverityPill = ({ severity }: { severity: Severity }) => pill(SEV[severity], severity);
