import { Loader2 } from "lucide-react";
import type { ReactNode } from "react";
import { Chip, ROLE_STYLE, RUN_STATUS_STYLE, VerdictChip } from "./badges";
import type { DelibAgentRun } from "./types";

function Bullets({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null;
  return (
    <div className="mt-2">
      <div className="text-xs font-semibold uppercase tracking-wide text-ink-300">{title}</div>
      <ul className="mt-0.5 list-disc space-y-0.5 pl-5 text-sm text-ink-100">
        {items.map((r, i) => (
          <li key={i}>{r}</li>
        ))}
      </ul>
    </div>
  );
}

function tokenText(t: Record<string, number>): string | null {
  const entries = Object.entries(t);
  if (!entries.length) return null;
  return entries.map(([k, v]) => `${k.replace(/_tokens?$/, "")} ${v}`).join(" / ") + " tokens";
}

export function AgentCard({ a }: { a: DelibAgentRun }) {
  const v = a.verdict;
  const tok = tokenText(a.tokens);
  return (
    <li className="panel px-4 py-3" aria-label={`${a.name || a.agent}: ${a.status}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-base font-semibold text-ink-50">{a.name || a.agent}</span>
        <Chip cls={ROLE_STYLE[a.role]}>{a.role}</Chip>
        <Chip cls={RUN_STATUS_STYLE[a.status]}>
          {a.status === "running" ? <Loader2 size={12} className="animate-spin" aria-hidden="true" /> : null}
          {a.status}
        </Chip>
        {v ? <VerdictChip v={v.verdict} /> : null}
        {v ? <Chip>confidence: {v.confidence}</Chip> : null}
        {v?.fallback ? (
          <Chip cls="border-amber-300 bg-amber-50 text-amber-900" title="No model reasoning: verdict computed from the deterministic pre-checks">
            deterministic stand-in
          </Chip>
        ) : null}
      </div>
      {a.error ? <div className="mt-2 text-sm text-red-800">Error: {a.error}</div> : null}
      {v ? (
        <>
          <Bullets title="Reasons" items={v.reasons} />
          <Bullets title="Harms" items={v.harms} />
          <Bullets title="Prerequisites" items={v.prerequisites} />
          {v.tool_numbers_cited.length ? (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <span className="text-xs font-semibold uppercase tracking-wide text-ink-300">Numbers cited</span>
              {v.tool_numbers_cited.map((n, i) => (
                <span key={i} className="rounded border border-ink-700 bg-white px-1.5 py-px font-mono text-xs text-ink-100">
                  {n}
                </span>
              ))}
            </div>
          ) : null}
        </>
      ) : a.status === "pending" || a.status === "running" ? (
        <div className="mt-2 text-sm text-ink-400">{a.status === "running" ? "Working..." : "Waiting to start"}</div>
      ) : null}
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-400">
        {a.latency_ms > 0 ? <span>latency {(a.latency_ms / 1000).toFixed(1)} s</span> : null}
        {tok ? <span>{tok}</span> : null}
        {a.used_tools ? <span>used tools</span> : null}
      </div>
      {a.events.length > 0 ? (
        <details className="mt-2 text-sm">
          <summary className="cursor-pointer text-ink-300 hover:text-ink-100">Events ({a.events.length})</summary>
          <ol className="mt-1 space-y-1 border-l border-ink-700 pl-3">
            {a.events.map((e) => (
              <li key={e.seq} className="text-xs text-ink-200">
                <span className="font-mono font-semibold">{e.kind}</span>
                {e.tool_name ? <span className="ml-1 font-mono text-blue-800">{e.tool_name}</span> : null}
                {e.summary ? <span className="ml-2">{e.summary}</span> : null}
              </li>
            ))}
          </ol>
        </details>
      ) : null}
    </li>
  );
}

export function AgentCards({ agents, heading }: { agents: DelibAgentRun[]; heading?: ReactNode }) {
  if (!agents.length) return null;
  return (
    <section aria-label="Agent progress">
      {heading}
      <ul className="grid gap-3 lg:grid-cols-2">
        {agents.map((a) => (
          <AgentCard key={a.agent} a={a} />
        ))}
      </ul>
    </section>
  );
}
