import { ChevronDown, ChevronRight, GitBranch, ShieldCheck } from "lucide-react";
import { useMemo, useState } from "react";
import { ErrorBanner, PanelSkeleton } from "../../components/Feedback";
import { PageHeader } from "../../components/Layout";
import { useAsync } from "../../hooks/useAsync";
import { getAgentTree } from "./api";
import type { AgentNode, NodeKind, StatValue } from "./types";

const BANNER = "Every agent is read-only and advisory; humans review and act per site procedures.";

const KIND: Record<NodeKind, { label: string; badge: string; bar: string }> = {
  llm_agent: { label: "LLM agent", badge: "border-blue-300 bg-blue-50 text-blue-800", bar: "border-l-blue-500" },
  tool: { label: "Tool", badge: "border-ink-600 bg-ink-800 text-ink-200", bar: "border-l-slate-400" },
  engine: { label: "Engine", badge: "border-green-300 bg-green-50 text-green-800", bar: "border-l-green-500" },
  validator: { label: "Validator", badge: "border-yellow-400 bg-yellow-100 text-yellow-900", bar: "border-l-yellow-400" },
  human: { label: "Human", badge: "border-amber-400 bg-amber-100 text-amber-900", bar: "border-l-amber-500" },
  model: { label: "Model", badge: "border-purple-300 bg-purple-50 text-purple-800", bar: "border-l-purple-500" },
  group: { label: "Group", badge: "border-ink-600 bg-white text-ink-300", bar: "border-l-ink-600" },
};

function fmtStat(v: StatValue): string {
  if (v === null || v === undefined) return "n/a";
  if (typeof v === "number") {
    if (Number.isInteger(v)) return String(v);
    return v <= 1 ? `${Math.round(v * 100)}%` : v.toFixed(1);
  }
  return v;
}

function countNodes(n: AgentNode): number {
  return 1 + n.children.reduce((a, c) => a + countNodes(c), 0);
}

function Chip({ children, cls = "border-ink-700 bg-white text-ink-200" }: { children: React.ReactNode; cls?: string }) {
  return <span className={`inline-flex items-center rounded-md border px-2 py-0.5 text-xs ${cls}`}>{children}</span>;
}

function budgetText(n: AgentNode): string | null {
  const b = n.budget;
  if (!b) return null;
  const parts: string[] = [];
  if (b.max_tokens) parts.push(`${b.max_tokens} tokens/call`);
  if (b.max_tool_rounds !== null && b.max_tool_rounds !== undefined) parts.push(`${b.max_tool_rounds} tool rounds`);
  if (b.time_budget_s) parts.push(`${b.time_budget_s}s budget`);
  return parts.join(" · ");
}

function NodeCard({ n }: { n: AgentNode }) {
  const k = KIND[n.kind] ?? KIND.group;
  const budget = budgetText(n);
  const measurements = Array.isArray(n.meta?.measurements) ? (n.meta.measurements as string[]) : null;
  const owner = typeof n.meta?.owner_persona === "string" ? (n.meta.owner_persona as string) : null;
  const statEntries = Object.entries(n.stats);
  return (
    <div className={`panel border-l-4 px-4 py-3 ${k.bar}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className={`rounded-md border px-2 py-0.5 text-xs font-bold tracking-wide ${k.badge}`}>{k.label}</span>
        <span className="text-base font-semibold text-ink-50">{n.name}</span>
        {n.model ? <Chip cls="border-blue-200 bg-white font-mono text-blue-800">{n.model}</Chip> : null}
      </div>
      <div className="mt-1 text-sm text-ink-300">{n.description}</div>
      {(measurements || owner || budget) && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {measurements ? <Chip>measures {measurements.join(", ")}</Chip> : null}
          {owner ? <Chip>owner: {owner.replace(/_/g, " ")}</Chip> : null}
          {budget ? <Chip cls="border-blue-200 bg-blue-50 text-blue-800">{budget}</Chip> : null}
        </div>
      )}
      <div className="mt-2 flex flex-wrap gap-1.5">
        {n.permissions.map((p) => (
          <Chip key={p} cls="border-green-200 bg-green-50 text-green-800">
            {p}
          </Chip>
        ))}
      </div>
      {statEntries.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1.5" aria-label="live stats">
          {statEntries.map(([label, v]) => (
            <Chip key={label} cls="border-ink-700 bg-ink-850 font-mono text-ink-100">
              {label}: <b className="ml-1">{fmtStat(v)}</b>
            </Chip>
          ))}
        </div>
      ) : null}
      {n.may_call.length > 0 && n.children.length === 0 ? (
        <div className="mt-2 text-xs text-ink-400">may call: {n.may_call.map((c) => c.replace(/^tool\./, "")).join(", ")}</div>
      ) : null}
    </div>
  );
}

function TreeNode({ n, depth, last }: { n: AgentNode; depth: number; last: boolean }) {
  const [open, setOpen] = useState(depth < 2 && n.kind !== "human");
  const hasKids = n.children.length > 0;
  return (
    <li className="relative pl-7">
      {/* connector lines */}
      <span className={`absolute left-2.5 top-0 w-px bg-ink-600 ${last ? "h-6" : "h-full"}`} aria-hidden="true" />
      <span className="absolute left-2.5 top-6 h-px w-4 bg-ink-600" aria-hidden="true" />
      <div className="pb-3">
        <div className="flex items-start gap-2">
          {hasKids ? (
            <button
              type="button"
              onClick={() => setOpen((o) => !o)}
              aria-expanded={open}
              aria-label={`${open ? "Collapse" : "Expand"} ${n.name}`}
              className="mt-3 shrink-0 rounded border border-ink-600 bg-white p-0.5 text-ink-300 hover:bg-ink-800"
            >
              {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </button>
          ) : (
            <span className="w-[22px] shrink-0" />
          )}
          <div className="min-w-0 flex-1">
            <NodeCard n={n} />
            {hasKids && !open ? <div className="mt-1 text-xs text-ink-400">{countNodes(n) - 1} nodes collapsed</div> : null}
          </div>
        </div>
        {hasKids && open ? (
          <ul className="mt-3 ml-3">
            {n.children.map((c, i) => (
              <TreeNode key={c.id} n={c} depth={depth + 1} last={i === n.children.length - 1} />
            ))}
          </ul>
        ) : null}
      </div>
    </li>
  );
}

function Legend() {
  return (
    <div className="flex flex-wrap gap-2">
      {(Object.keys(KIND) as NodeKind[])
        .filter((k) => k !== "group")
        .map((k) => (
          <span key={k} className={`rounded-md border px-2 py-0.5 text-xs font-bold tracking-wide ${KIND[k].badge}`}>
            {KIND[k].label}
          </span>
        ))}
    </div>
  );
}

function BuildProcessCard() {
  return (
    <div className="panel border-t-2 border-t-blue-600 px-5 py-4">
      <div className="flex items-center gap-2">
        <GitBranch size={18} className="text-blue-700" />
        <div className="label">Build process</div>
      </div>
      <p className="mt-2 text-sm text-ink-200">
        The software itself was built the same way: a principal agent wrote the contracts first, then delegated each module (data, ML, Meta agent,
        backend, frontend, docs, QA, review, features) to specialist agents, which spawned their own sub-agents where a task split cleanly. Model and effort
        were chosen per task, and every commit was made by the principal after review. Details: <span className="font-mono">docs/HACKATHON_WORK.md</span>,{" "}
        <span className="font-mono">AGENTS.md</span>.
      </p>
    </div>
  );
}

export default function AgentTreePage() {
  const tree = useAsync((s) => getAgentTree(s), []);
  const t = tree.data?.totals;
  const root = tree.data?.root;
  const kindChips = useMemo(
    () => (t ? (Object.keys(KIND) as NodeKind[]).filter((k) => (t.by_kind[k] ?? 0) > 0).map((k) => `${t.by_kind[k]} ${KIND[k].label.toLowerCase()}`) : []),
    [t],
  );
  return (
    <div>
      <PageHeader
        title="Agent organisation"
        subtitle="How ThermoMind's agents are organised, what each may call, and what it is allowed to do. Live counts come from the stored cases."
      />
      <div className="mb-4 flex items-start gap-3 rounded-xl border border-green-300 bg-green-50 px-4 py-3 text-green-900">
        <ShieldCheck size={20} className="mt-0.5 shrink-0 text-green-700" />
        <div className="text-base font-medium">{BANNER}</div>
      </div>
      {tree.error ? <ErrorBanner error={tree.error} title="Could not load the agent tree" onRetry={tree.reload} /> : null}
      {tree.loading && !tree.data ? <PanelSkeleton lines={8} /> : null}
      {root && t ? (
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_20rem]">
          <div>
            <div className="mb-3 flex flex-wrap items-center gap-2 text-sm text-ink-300">
              <span className="font-semibold text-ink-100">{t.nodes} nodes</span>
              <span>·</span>
              <span>{kindChips.join(" · ")}</span>
              <span>·</span>
              <span>{t.deterministic_nodes} run no LLM</span>
            </div>
            <ul>
              <li className="relative">
                <NodeCard n={root} />
                <ul className="mt-3 ml-3">
                  {root.children.map((c, i) => (
                    <TreeNode key={c.id} n={c} depth={1} last={i === root.children.length - 1} />
                  ))}
                </ul>
              </li>
            </ul>
          </div>
          <aside className="space-y-4">
            <div className="panel px-5 py-4">
              <div className="label">Legend</div>
              <div className="mt-2">
                <Legend />
              </div>
              <div className="mt-3 text-xs text-ink-400">
                n+1: a new plant-area agent is one entry in the registry; it appears here and in the what-if run without other changes.
              </div>
              <div className="mt-2 text-xs text-ink-400">Generated {tree.data?.generated_at_utc}</div>
            </div>
            <BuildProcessCard />
          </aside>
        </div>
      ) : null}
    </div>
  );
}
