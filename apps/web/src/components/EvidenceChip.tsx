import type { Evidence } from "../api/types";

interface Props {
  id: string;
  evidenceById: Map<string, Evidence>;
  onOpen: (id: string) => void;
  tone?: "support" | "contradict" | "neutral";
}

const TONE = {
  support: "border-green-300 bg-green-50 text-green-800 hover:bg-green-100",
  contradict: "border-red-300 bg-red-50 text-red-800 hover:bg-red-100",
  neutral: "border-ink-600 bg-white text-ink-200 hover:border-blue-400 hover:text-blue-800",
};

export function EvidenceChip({ id, evidenceById, onOpen, tone = "neutral" }: Props) {
  const ev = evidenceById.get(id);
  const unknown = !ev;
  return (
    <button
      type="button"
      onClick={() => onOpen(id)}
      title={ev ? `${ev.title} — ${ev.method}` : "Evidence id not found in this case"}
      className={`chip ${unknown ? "border-dashed border-red-300 text-red-700 line-through" : TONE[tone]}`}
    >
      {id}
      {ev?.is_synthetic ? <span className="ml-1 rounded bg-yellow-200 px-1 text-[11px] font-bold not-italic text-yellow-900 no-underline">SYN</span> : null}
    </button>
  );
}

export function EvidenceChips({ ids, tone, evidenceById, onOpen }: { ids: string[]; tone?: Props["tone"]; evidenceById: Map<string, Evidence>; onOpen: (id: string) => void }) {
  if (ids.length === 0) return <span className="text-sm text-ink-400">none</span>;
  return (
    <span className="inline-flex flex-wrap gap-1.5">
      {ids.map((id) => (
        <EvidenceChip key={id} id={id} tone={tone} evidenceById={evidenceById} onOpen={onOpen} />
      ))}
    </span>
  );
}
