import {
  AlertOctagon,
  ArrowDownToLine,
  ArrowUpFromLine,
  Bot,
  CheckCheck,
  FileCheck2,
  FolderOpen,
  RefreshCcw,
  Undo2,
  Wrench,
} from "lucide-react";
import { useState } from "react";
import type { AgentEvent, AgentEventKind, Evidence } from "../api/types";
import { fmtDateTime, fmtMs } from "../lib/format";
import { EvidenceChips } from "./EvidenceChip";

const KIND: Record<AgentEventKind, { label: string; icon: React.ReactNode; cls: string }> = {
  case_opened: { label: "Case opened", icon: <FolderOpen size={16} />, cls: "text-ink-300 border-ink-600" },
  model_request: { label: "Model request", icon: <ArrowUpFromLine size={16} />, cls: "text-blue-800 border-blue-300" },
  model_response: { label: "Model response", icon: <ArrowDownToLine size={16} />, cls: "text-blue-800 border-blue-300" },
  tool_call: { label: "Tool call", icon: <Wrench size={16} />, cls: "text-blue-800 border-blue-300" },
  tool_result: { label: "Tool result", icon: <FileCheck2 size={16} />, cls: "text-blue-800 border-blue-300" },
  validation: { label: "Validation", icon: <CheckCheck size={16} />, cls: "text-green-800 border-green-300" },
  rewrite_requested: { label: "Rewrite requested", icon: <RefreshCcw size={16} />, cls: "text-amber-800 border-amber-400" },
  report_accepted: { label: "Report accepted", icon: <Bot size={16} />, cls: "text-blue-800 border-blue-300" },
  error: { label: "Error", icon: <AlertOctagon size={16} />, cls: "text-red-800 border-red-300" },
  fallback: { label: "Fallback", icon: <Undo2 size={16} />, cls: "text-amber-800 border-amber-400" },
};

interface Props {
  events: AgentEvent[];
  evidenceById: Map<string, Evidence>;
  onOpenEvidence: (id: string) => void;
}

export function AgentTimeline({ events, evidenceById, onOpenEvidence }: Props) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const toggle = (seq: number) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(seq)) next.delete(seq);
      else next.add(seq);
      return next;
    });

  if (events.length === 0) {
    return <div className="px-5 py-6 text-base text-ink-400">No agent events were recorded for this case.</div>;
  }

  return (
    <ol className="divide-y divide-ink-700/70">
      {events.map((e) => {
        const k = KIND[e.kind];
        const hasArgs = e.args && Object.keys(e.args).length > 0;
        const isOpen = expanded.has(e.seq);
        return (
          <li key={e.seq} className={`px-5 py-3 ${e.ok ? "" : "bg-red-50/60"}`}>
            <div className="flex items-start gap-3">
              <span className={`mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md border bg-ink-900 ${k.cls}`}>{k.icon}</span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span className="font-mono text-sm text-ink-400">#{e.seq}</span>
                  <span className={`text-sm font-semibold uppercase tracking-wide ${k.cls.split(" ")[0]}`}>{k.label}</span>
                  {e.tool_name ? <code className="rounded bg-ink-900 px-1.5 py-0.5 font-mono text-sm text-blue-800">{e.tool_name}</code> : null}
                  {!e.ok ? <span className="rounded bg-red-100 px-1.5 py-0.5 text-xs font-bold text-red-800">NOT OK</span> : null}
                  <span className="ml-auto flex items-center gap-3 font-mono text-xs text-ink-400">
                    {e.tokens ? (
                      <span>
                        tokens{" "}
                        {Object.entries(e.tokens)
                          .map(([tk, tv]) => `${tk.replace(/_tokens$/, "")}=${tv}`)
                          .join(" ")}
                      </span>
                    ) : null}
                    {e.latency_ms !== null ? <span>{fmtMs(e.latency_ms)}</span> : null}
                    <span>{fmtDateTime(e.ts_utc)}</span>
                  </span>
                </div>
                <div className="mt-1 text-base text-ink-100">{e.summary}</div>
                {e.evidence_ids.length > 0 ? (
                  <div className="mt-1.5 flex items-center gap-2 text-sm text-ink-300">
                    <span>evidence</span>
                    <EvidenceChips ids={e.evidence_ids} evidenceById={evidenceById} onOpen={onOpenEvidence} />
                  </div>
                ) : null}
                {hasArgs ? (
                  <div className="mt-1.5">
                    <button type="button" onClick={() => toggle(e.seq)} className="text-sm font-medium text-blue-700 hover:underline">
                      {isOpen ? "hide args" : "show args"}
                    </button>
                    {isOpen ? (
                      <pre className="mt-1 overflow-x-auto rounded-lg border border-ink-700 bg-ink-950 px-3 py-2 font-mono text-sm text-ink-100">
                        {JSON.stringify(e.args, null, 2)}
                      </pre>
                    ) : null}
                  </div>
                ) : null}
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
