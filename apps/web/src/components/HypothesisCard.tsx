import { HelpCircle } from "lucide-react";
import type { Evidence, Hypothesis } from "../api/types";
import { humanize } from "../lib/format";
import { EvidenceChips } from "./EvidenceChip";
import { HypothesisStatusPill } from "./StatusPill";

interface Props {
  hypothesis: Hypothesis;
  evidenceById: Map<string, Evidence>;
  onOpenEvidence: (id: string) => void;
}

export function HypothesisCard({ hypothesis: h, evidenceById, onOpenEvidence }: Props) {
  return (
    <div className={`panel p-5 ${h.rank === 1 ? "border-blue-300" : ""}`}>
      <div className="flex flex-wrap items-center gap-3">
        <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-ink-700 font-mono text-base font-bold text-ink-100">
          {h.rank}
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-lg font-semibold text-ink-50">{h.name}</div>
          {h.key ? <div className="font-mono text-sm text-ink-400">{humanize(h.key)}</div> : null}
        </div>
        <HypothesisStatusPill status={h.status} />
      </div>
      {h.rationale ? <p className="mt-3 text-base leading-relaxed text-ink-100">{h.rationale}</p> : null}
      <div className="mt-4 grid grid-cols-2 gap-4 text-base">
        <div>
          <div className="label mb-1.5">Supporting evidence</div>
          <EvidenceChips ids={h.supporting_evidence_ids} tone="support" evidenceById={evidenceById} onOpen={onOpenEvidence} />
        </div>
        <div>
          <div className="label mb-1.5">Contradicting evidence</div>
          <EvidenceChips ids={h.contradicting_evidence_ids} tone="contradict" evidenceById={evidenceById} onOpen={onOpenEvidence} />
        </div>
      </div>
      {h.limitations.length > 0 ? (
        <div className="mt-4">
          <div className="label mb-1.5">Limitations</div>
          <ul className="list-disc space-y-1 pl-5 text-base text-ink-200">
            {h.limitations.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {h.what_would_change_assessment ? (
        <div className="mt-4 rounded-lg border border-ink-600 bg-ink-900/70 px-4 py-3">
          <div className="mb-1 flex items-center gap-1.5 text-sm font-semibold uppercase tracking-wide text-ink-300">
            <HelpCircle size={14} /> What would change this assessment?
          </div>
          <p className="text-base text-ink-100">{h.what_would_change_assessment}</p>
        </div>
      ) : null}
    </div>
  );
}
