import { ClipboardList, Download, FileJson, Gauge, History, RefreshCw, Sparkles, Wrench } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { listInvestigations } from "../../api/client";
import { ErrorBanner, InfoBanner, PanelSkeleton, Spinner, WarnBanner } from "../../components/Feedback";
import { KpiCard } from "../../components/KpiCard";
import { PageHeader } from "../../components/Layout";
import { SourceBadge } from "../../components/SourceBadge";
import { useAsync } from "../../hooks/useAsync";
import { fmtDateTime } from "../../lib/format";
import { cmmsCsvUrl, cmmsJsonUrl, createHandover, getCmmsCsv, getCmmsJson, getOpsMetrics, listHandovers } from "./api";
import type { HandoverHours, HandoverNote, MedianStat, RateStat } from "./types";

type Tab = "handover" | "cmms" | "metrics";

const TABS: { id: Tab; label: string; icon: JSX.Element }[] = [
  { id: "handover", label: "Shift handover", icon: <ClipboardList size={16} /> },
  { id: "cmms", label: "CMMS draft export", icon: <Wrench size={16} /> },
  { id: "metrics", label: "Pilot metrics", icon: <Gauge size={16} /> },
];

function readStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    /* storage unavailable: sign-off stays in memory only */
  }
}

/** Persona chosen in the plant persona switcher (if any); read-only here. */
function currentPersona(): string | undefined {
  return readStorage("thermomind.persona") ?? undefined;
}

export default function OpsPage() {
  const [tab, setTab] = useState<Tab>("handover");
  return (
    <div>
      <PageHeader
        title="Ops workflow"
        subtitle="Shift handover drafts, CMMS work-order drafts and prototype metrics. Everything here is read-only, drafted for human review, and never sent to any plant or CMMS system."
        right={<SourceBadge variant="review" />}
      />
      <div role="tablist" aria-label="Ops sections" className="mb-5 flex flex-wrap gap-2">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={tab === t.id ? "btn-primary h-10 px-4" : "btn-secondary h-10 px-4"}
          >
            {t.icon}
            {t.label}
          </button>
        ))}
      </div>
      {tab === "handover" ? <HandoverSection /> : null}
      {tab === "cmms" ? <CmmsSection /> : null}
      {tab === "metrics" ? <MetricsSection /> : null}
    </div>
  );
}

// ----------------------------------------------------------------------------- handover

function HandoverSection() {
  const [hours, setHours] = useState<HandoverHours>(8);
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<unknown>(null);
  const [selected, setSelected] = useState<HandoverNote | null>(null);
  const history = useAsync((s) => listHandovers(s), []);

  useEffect(() => {
    if (!busy) return;
    const started = Date.now();
    const id = window.setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 500);
    return () => window.clearInterval(id);
  }, [busy]);

  useEffect(() => {
    if (!selected && history.data && history.data.length > 0) setSelected(history.data[0]);
  }, [history.data, selected]);

  async function generate() {
    setBusy(true);
    setElapsed(0);
    setError(null);
    try {
      const note = await createHandover({ hours, persona: currentPersona() ?? null });
      setSelected(note);
      history.reload();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-5 xl:grid-cols-[1fr_320px]">
      <div className="flex min-w-0 flex-col gap-4">
        <div className="panel flex flex-wrap items-end gap-4 px-5 py-4">
          <label className="flex flex-col gap-1.5">
            <span className="label">Shift window</span>
            <select
              className="input"
              value={hours}
              disabled={busy}
              onChange={(e) => setHours(Number(e.target.value) as HandoverHours)}
            >
              <option value={8}>Last 8 h</option>
              <option value={12}>Last 12 h</option>
              <option value={24}>Last 24 h</option>
            </select>
          </label>
          <button type="button" className="btn-primary h-10" onClick={generate} disabled={busy}>
            {busy ? <Spinner /> : <Sparkles size={16} />}
            {busy ? `Drafting… ${elapsed}s` : "Generate handover draft"}
          </button>
          <p className="min-w-[240px] flex-1 text-sm text-ink-300">
            Cases created in the window (plus cases with open work requests) are sent as a structured list to Meta Muse
            Spark once (one bounded rewrite if the validator rejects it). If the draft cites unknown cases or contains
            control language, a deterministic fallback note is returned instead.
          </p>
        </div>
        {busy ? (
          <InfoBanner icon={<Spinner />}>
            Waiting for the server: gathering cases, calling the model and validating the draft. This typically takes
            30–120 s when Meta is configured.
          </InfoBanner>
        ) : null}
        {error ? <ErrorBanner title="Handover draft failed" error={error} onRetry={generate} /> : null}
        {selected ? <NoteView note={selected} /> : !history.loading && !busy ? (
          <div className="panel px-6 py-10 text-center text-ink-300">No handover drafts yet. Generate one above.</div>
        ) : null}
      </div>
      <aside className="panel h-fit">
        <div className="panel-header">
          <span className="panel-title flex items-center gap-2">
            <History size={16} /> Previous notes
          </span>
          <button type="button" className="btn-secondary h-8 px-2 text-sm" onClick={history.reload} aria-label="Reload">
            <RefreshCw size={14} />
          </button>
        </div>
        {history.error ? <ErrorBanner className="m-3" error={history.error} title="Could not load notes" /> : null}
        {history.loading ? <PanelSkeleton lines={3} className="border-0 shadow-none" /> : null}
        <ul className="divide-y divide-ink-700">
          {(history.data ?? []).map((n) => (
            <li key={n.note_id}>
              <button
                type="button"
                onClick={() => setSelected(n)}
                className={`w-full px-4 py-3 text-left hover:bg-ink-800 ${selected?.note_id === n.note_id ? "bg-ink-800" : ""}`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-sm text-blue-700">{n.note_id}</span>
                  <span className="text-xs text-ink-300">{n.hours} h</span>
                </div>
                <div className="mt-0.5 text-xs text-ink-300">{fmtDateTime(n.created_at_utc)}</div>
                <div className="mt-1">
                  {n.meta_used ? (
                    <SourceBadge variant="meta" size="sm" label="META DRAFT" />
                  ) : (
                    <SourceBadge variant="offline" size="sm" label="FALLBACK" />
                  )}
                </div>
              </button>
            </li>
          ))}
        </ul>
      </aside>
    </div>
  );
}

function SignOff({ noteId }: { noteId: string }) {
  const key = `thermomind.ops.signoff.${noteId}`;
  const [signed, setSigned] = useState<string | null>(() => readStorage(key));
  useEffect(() => setSigned(readStorage(key)), [key]);
  return (
    <label className="flex items-start gap-3 rounded-lg border border-yellow-300 bg-yellow-50 px-4 py-3 text-yellow-900">
      <input
        type="checkbox"
        className="mt-1 h-4 w-4"
        checked={signed !== null}
        onChange={(e) => {
          const v = e.target.checked ? new Date().toISOString() : null;
          writeStorage(key, v);
          setSigned(v);
        }}
      />
      <span className="text-sm">
        <span className="font-semibold">Shift supervisor sign-off</span>
        {signed ? ` — ticked ${fmtDateTime(signed)}` : ""}. Recorded locally in this browser only; it is not sent to the
        server and is not an approval record.
      </span>
    </label>
  );
}

function CaseLink({ id }: { id: string | null }) {
  if (!id) return <span className="font-mono text-xs text-ink-400">system</span>;
  return (
    <Link to={`/investigations/${id}`} className="font-mono text-sm text-blue-700 hover:underline">
      {id}
    </Link>
  );
}

function ItemList({ title, items }: { title: string; items: { case_id: string | null; text: string }[] }) {
  return (
    <div>
      <div className="label mb-2">
        {title} <span className="text-ink-400">({items.length})</span>
      </div>
      {items.length === 0 ? (
        <div className="text-sm text-ink-400">None.</div>
      ) : (
        <ul className="flex flex-col gap-2">
          {items.map((it, i) => (
            <li key={`${it.case_id}-${i}`} className="rounded-lg border border-ink-700 px-3 py-2">
              <CaseLink id={it.case_id} />
              <div className="mt-0.5 text-base text-ink-100">{it.text}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function NoteView({ note }: { note: HandoverNote }) {
  const real = note.cases.filter((c) => !c.synthetic).length;
  const synth = note.cases.length - real;
  return (
    <div className="panel">
      <div className="panel-header flex-wrap">
        <div className="flex flex-wrap items-center gap-2">
          <SourceBadge variant="review" label="DRAFT — REQUIRES SHIFT SUPERVISOR SIGN-OFF" />
          {note.meta_used ? (
            <SourceBadge variant="meta" label={`MODEL-DRAFTED · ${note.meta_model ?? "muse-spark-1.3"}`} />
          ) : (
            <SourceBadge variant="offline" label={note.meta_calls === 0 ? "OFFLINE DRAFT · NO META CALL" : "DETERMINISTIC FALLBACK"} />
          )}
        </div>
        <span className="font-mono text-xs text-ink-300">
          {note.note_id} · sha256 {note.note_hash.slice(0, 12)}…
        </span>
      </div>
      <div className="flex flex-col gap-5 px-5 py-4">
        <div>
          <div className="text-lg font-semibold text-ink-50">{note.draft.headline}</div>
          <div className="mt-1 text-sm text-ink-300">
            {note.source_label} · window last {note.hours} h ({fmtDateTime(note.window_start_utc)} →{" "}
            {fmtDateTime(note.window_end_utc)}) · {note.cases.length} case(s): {real} real-only, {synth} synthetic overlay ·{" "}
            {note.work_requests_available ? `${note.work_requests_included} open work request(s)` : "work requests unavailable"}
            {note.persona ? ` · prepared for ${note.persona}` : ""}
          </div>
        </div>
        {note.fallback_reason ? <WarnBanner>Fallback reason: {note.fallback_reason}</WarnBanner> : null}
        <ItemList title="Open items" items={note.draft.open_items} />
        <ItemList title="Watch list" items={note.draft.watch_list} />
        <ItemList title="Completed" items={note.draft.completed} />
        <div>
          <div className="label mb-2">Caveats</div>
          <ul className="list-disc pl-5 text-sm text-ink-200">
            {note.draft.caveats.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </div>
        {note.validation_errors.length > 0 ? (
          <details className="text-sm text-ink-300">
            <summary className="cursor-pointer">Validator findings before acceptance/fallback ({note.validation_errors.length})</summary>
            <ul className="mt-2 list-disc pl-5 font-mono text-xs">
              {note.validation_errors.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
          </details>
        ) : null}
        <div className="text-xs text-ink-400">
          Meta calls: {note.meta_calls}
          {note.rewrite_used ? " (incl. one rewrite)" : ""}
          {note.latency_ms !== null ? ` · ${(note.latency_ms / 1000).toFixed(1)} s model latency` : ""}
          {note.tokens.total_tokens ? ` · ${note.tokens.total_tokens} tokens` : ""}
        </div>
        <SignOff noteId={note.note_id} />
      </div>
    </div>
  );
}

// ----------------------------------------------------------------------------- CMMS

function CmmsSection() {
  const cases = useAsync((s) => listInvestigations(s), []);
  const [caseId, setCaseId] = useState<string>("");
  const persona = useMemo(() => currentPersona(), []);
  useEffect(() => {
    if (!caseId && cases.data && cases.data.length > 0) setCaseId(cases.data[0].case_id);
  }, [cases.data, caseId]);
  const preview = useAsync(
    async (s) => (caseId ? { json: await getCmmsJson(caseId, persona, s), csv: await getCmmsCsv(caseId, persona, s) } : null),
    [caseId],
  );
  const wo = preview.data?.json.work_order_draft;

  return (
    <div className="flex flex-col gap-4">
      <div className="panel flex flex-wrap items-end gap-4 px-5 py-4">
        <label className="flex min-w-[280px] flex-col gap-1.5">
          <span className="label">Case</span>
          <select className="input" value={caseId} onChange={(e) => setCaseId(e.target.value)} disabled={!cases.data?.length}>
            {(cases.data ?? []).map((i) => (
              <option key={i.case_id} value={i.case_id}>
                {i.case_id} · {i.scenario.title} · {i.report?.severity ?? i.status}
              </option>
            ))}
          </select>
        </label>
        <a className={`btn-secondary h-10 ${caseId ? "" : "pointer-events-none opacity-50"}`} href={caseId ? cmmsJsonUrl(caseId, persona) : undefined} download>
          <FileJson size={16} /> Download JSON
        </a>
        <a className={`btn-secondary h-10 ${caseId ? "" : "pointer-events-none opacity-50"}`} href={caseId ? cmmsCsvUrl(caseId, persona) : undefined} download>
          <Download size={16} /> Download CSV
        </a>
        <p className="min-w-[240px] flex-1 text-sm text-ink-300">
          Generic draft work-order shape for import into a CMMS by a person. ThermoMind has no CMMS integration and submits
          nothing. CSV cells starting with = + - @ are prefixed with a quote (formula-injection safe).
        </p>
      </div>
      {cases.error ? <ErrorBanner title="Could not load cases" error={cases.error} onRetry={cases.reload} /> : null}
      {!cases.loading && (cases.data ?? []).length === 0 ? (
        <div className="panel px-6 py-10 text-center text-ink-300">No investigations stored yet.</div>
      ) : null}
      {preview.error ? <ErrorBanner title="Preview failed" error={preview.error} onRetry={preview.reload} /> : null}
      {preview.loading && caseId ? <PanelSkeleton lines={5} /> : null}
      {wo && preview.data ? (
        <div className="panel">
          <div className="panel-header flex-wrap">
            <div className="flex flex-wrap items-center gap-2">
              <SourceBadge variant="review" label={wo.status.toUpperCase()} />
              {preview.data.json.provenance.synthetic ? <SourceBadge variant="synthetic" /> : <SourceBadge variant="real" />}
            </div>
            <span className="text-xs text-ink-300">{wo.system}</span>
          </div>
          <div className="grid gap-4 px-5 py-4 lg:grid-cols-2">
            <dl className="grid grid-cols-[140px_1fr] gap-x-3 gap-y-2 text-sm">
              <dt className="text-ink-300">External ref</dt>
              <dd className="font-mono">{wo.external_ref}</dd>
              <dt className="text-ink-300">Asset</dt>
              <dd>{wo.asset}</dd>
              <dt className="text-ink-300">Priority</dt>
              <dd>
                {wo.priority} · {wo.priority_label}
              </dd>
              <dt className="text-ink-300">Title</dt>
              <dd className="font-semibold">{wo.title}</dd>
              <dt className="text-ink-300">Requested by</dt>
              <dd>{wo.requested_by}</dd>
              <dt className="text-ink-300">Generated</dt>
              <dd>{fmtDateTime(wo.generated_at_utc)}</dd>
              <dt className="text-ink-300">Description</dt>
              <dd className="whitespace-pre-wrap">{wo.description}</dd>
            </dl>
            <div>
              <div className="label mb-2">Tasks (engineer review checks)</div>
              <ol className="list-decimal pl-5 text-sm text-ink-100">
                {wo.tasks.map((t) => (
                  <li key={t.seq} className="mb-1">
                    {t.text}
                  </li>
                ))}
              </ol>
              <p className="mt-3 text-xs text-ink-400">{preview.data.json.notice}</p>
            </div>
          </div>
          <details className="border-t border-ink-700 px-5 py-3">
            <summary className="cursor-pointer text-sm font-semibold text-ink-200">Raw JSON</summary>
            <pre className="mt-2 max-h-80 overflow-auto rounded-lg bg-ink-900 p-3 font-mono text-xs">
              {JSON.stringify(preview.data.json, null, 2)}
            </pre>
          </details>
          <details className="border-t border-ink-700 px-5 py-3">
            <summary className="cursor-pointer text-sm font-semibold text-ink-200">CSV preview</summary>
            <pre className="mt-2 max-h-80 overflow-auto rounded-lg bg-ink-900 p-3 font-mono text-xs">{preview.data.csv}</pre>
          </details>
        </div>
      ) : null}
    </div>
  );
}

// ----------------------------------------------------------------------------- metrics

const fmtMedian = (m: MedianStat, digits = 1) => (m.median === null ? "—" : m.median.toFixed(digits));
const fmtRate = (r: RateStat) => (r.rate === null ? "—" : `${(r.rate * 100).toFixed(0)}%`);

function CountTable({ title, counts }: { title: string; counts: Record<string, number> }) {
  const entries = Object.entries(counts);
  return (
    <div className="panel overflow-hidden">
      <div className="panel-header">
        <span className="panel-title">{title}</span>
      </div>
      <table className="table-base">
        <tbody>
          {entries.length === 0 ? (
            <tr>
              <td className="text-ink-400">No data</td>
            </tr>
          ) : (
            entries.map(([k, v]) => (
              <tr key={k}>
                <td>{k.replace(/_/g, " ")}</td>
                <td className="text-right font-mono tabular-nums">{v}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

function MetricsSection() {
  const m = useAsync((s) => getOpsMetrics(s), []);
  const d = m.data;
  return (
    <div className="flex flex-col gap-4">
      <WarnBanner>
        <span className="font-semibold">{d?.notice ?? "prototype metrics from this demo database, not pilot results"}</span>
        {" — "}computed by the API from stored investigations only; counts include demo and smoke-test runs.
      </WarnBanner>
      {m.error ? <ErrorBanner title="Could not load metrics" error={m.error} onRetry={m.reload} /> : null}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard loading={m.loading} label="Cases stored" value={d?.cases_total ?? "—"} caption={d ? `${d.live_cases} Meta live` : undefined} />
        <KpiCard
          loading={m.loading}
          label="Median live wall time"
          value={d ? fmtMedian(d.live_wall_time_s) : "—"}
          unit="s"
          caption={d ? `first model request → report accepted · n=${d.live_wall_time_s.n}` : undefined}
        />
        <KpiCard
          loading={m.loading}
          label="Median tool calls / live case"
          value={d ? fmtMedian(d.tool_calls_per_live_case, 0) : "—"}
          caption={d ? `n=${d.tool_calls_per_live_case.n}` : undefined}
        />
        <KpiCard
          loading={m.loading}
          tone="model"
          label="Validator first-pass acceptance"
          value={d ? fmtRate(d.validator_first_pass_acceptance) : "—"}
          caption={d ? `${d.validator_first_pass_acceptance.numerator}/${d.validator_first_pass_acceptance.n} live cases` : undefined}
        />
        <KpiCard
          loading={m.loading}
          tone="amber"
          label="Rewrite rate"
          value={d ? fmtRate(d.rewrite_rate) : "—"}
          caption={d ? `${d.rewrite_rate.numerator}/${d.rewrite_rate.n} live cases` : undefined}
        />
        <KpiCard
          loading={m.loading}
          label="Evidence citations / report"
          value={d ? fmtMedian(d.evidence_citations_per_report, 0) : "—"}
          caption={d ? `median, n=${d.evidence_citations_per_report.n} reports` : undefined}
        />
        <KpiCard
          loading={m.loading}
          tone="model"
          label="Cited ids resolving"
          value={d ? fmtRate(d.cited_ids_resolving) : "—"}
          caption={d ? `${d.cited_ids_resolving.numerator}/${d.cited_ids_resolving.n} citations` : undefined}
        />
        <KpiCard
          loading={m.loading}
          label="Median time to review"
          value={d ? fmtMedian(d.time_to_review_s, 0) : "—"}
          unit="s"
          caption={d ? `created → review · n=${d.time_to_review_s.n}` : undefined}
        />
      </div>
      {d ? (
        <>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <CountTable title="By mode" counts={d.by_mode} />
            <CountTable title="By status" counts={d.by_status} />
            <CountTable title="By scenario label" counts={d.by_scenario_label} />
            <CountTable title="Human review decisions" counts={d.review_counts} />
          </div>
          <details className="panel px-5 py-3">
            <summary className="cursor-pointer text-sm font-semibold text-ink-200">Metric definitions</summary>
            <dl className="mt-2 grid gap-x-4 gap-y-1 text-sm md:grid-cols-[260px_1fr]">
              {Object.entries(d.definitions).map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="font-mono text-ink-300">{k}</dt>
                  <dd className="text-ink-100">{v}</dd>
                </div>
              ))}
            </dl>
            <div className="mt-2 text-xs text-ink-400">Generated {fmtDateTime(d.generated_at_utc)}</div>
          </details>
        </>
      ) : null}
    </div>
  );
}
