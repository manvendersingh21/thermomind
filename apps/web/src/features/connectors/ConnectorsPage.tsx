import { Ban, Bell, ClipboardList, Database, Play, ShieldCheck, Square } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ErrorBanner, InfoBanner } from "../../components/Feedback";
import { PageHeader } from "../../components/Layout";
import { useAsync } from "../../hooks/useAsync";
import { fmtNum, sampleLabel } from "../../lib/format";
import { createCmmsDraft, getCmmsDrafts, getConnectorsStatus, getHistorianLatest, getOutbox, startHistorian, stopHistorian } from "./api";
import type { ConnectorInfo, HistorianLatest } from "./types";

const YEARS = [2011, 2012, 2013, 2014, 2015];
const TABLE_ROWS = 20;
const FETCH_ROWS = 60;
const POLL_MS = 2000;
const TABLE_COLS = ["AT", "AFDP", "GTEP", "TIT", "TAT", "TEY", "CDP", "CO", "NOX"];

function ModeBadge({ mode }: { mode: ConnectorInfo["mode"] }) {
  const simulated = mode === "simulated";
  return (
    <span
      className={`inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-semibold tracking-wide ${
        simulated ? "border-yellow-400 bg-yellow-100 text-yellow-900" : "border-red-300 bg-red-50 text-red-800"
      }`}
    >
      {simulated ? "SIMULATED" : "NOT CONNECTED"}
    </span>
  );
}

function Sparkline({ values }: { values: number[] }) {
  const w = 320;
  const h = 56;
  if (values.length < 2) {
    return <div className="flex h-14 items-center text-sm text-ink-400">Start the replay to draw TEY.</div>;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) => `${((i / (values.length - 1)) * w).toFixed(1)},${(h - 4 - ((v - min) / span) * (h - 8)).toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-14 w-full" role="img" aria-label="TEY sparkline of replayed rows">
      <polyline points={pts} fill="none" stroke="#2563eb" strokeWidth={1.8} strokeLinejoin="round" />
    </svg>
  );
}

function Card({ icon, title, mode, children, tone = "default" }: { icon: React.ReactNode; title: string; mode: ConnectorInfo["mode"]; children: React.ReactNode; tone?: "default" | "red" }) {
  return (
    <div className={`panel flex flex-col ${tone === "red" ? "border-red-300 bg-red-50/40" : ""}`}>
      <div className="panel-header">
        <div className="flex items-center gap-2 text-ink-100">
          {icon}
          <span className="panel-title">{title}</span>
        </div>
        <ModeBadge mode={mode} />
      </div>
      <div className="flex-1 space-y-3 px-5 py-4">{children}</div>
    </div>
  );
}

function HistorianCard({ info }: { info?: ConnectorInfo }) {
  const [year, setYear] = useState(2014);
  const [rate, setRate] = useState(1);
  const [startIndex, setStartIndex] = useState(0);
  const [latest, setLatest] = useState<HistorianLatest | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    try {
      setLatest(await getHistorianLatest(FETCH_ROWS, signal));
      setError(null);
    } catch (e) {
      if (!signal?.aborted) setError(e);
    }
  }, []);

  const running = latest?.cursor.running ?? false;

  useEffect(() => {
    const c = new AbortController();
    void refresh(c.signal);
    return () => c.abort();
  }, [refresh]);

  useEffect(() => {
    if (!running) return;
    const c = new AbortController();
    const id = window.setInterval(() => void refresh(c.signal), POLL_MS);
    return () => {
      window.clearInterval(id);
      c.abort();
    };
  }, [running, refresh]);

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    try {
      await fn();
      await refresh();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  const rows = latest?.rows ?? [];
  const tail = useMemo(() => rows.slice(-TABLE_ROWS).reverse(), [rows]);
  const tey = useMemo(() => rows.map((r) => r.TEY).filter((v): v is number => typeof v === "number"), [rows]);
  const cursor = latest?.cursor;

  return (
    <Card icon={<Database size={18} />} title="Historian" mode="simulated">
      <p className="text-sm text-ink-300">{info?.description ?? "Replays real UCI rows as if a historian were feeding them."}</p>
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1">
          <span className="label">Year</span>
          <select className="input" value={year} disabled={running} onChange={(e) => setYear(Number(e.target.value))}>
            {YEARS.map((y) => (
              <option key={y}>{y}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="label">Start row</span>
          <input className="input w-28 font-mono" type="number" min={0} value={startIndex} disabled={running} onChange={(e) => setStartIndex(Math.max(0, Math.floor(Number(e.target.value) || 0)))} />
        </label>
        <label className="flex flex-col gap-1">
          <span className="label">Rows/s</span>
          <input className="input w-20 font-mono" type="number" min={0} max={50} value={rate} disabled={running} onChange={(e) => setRate(Math.max(0, Math.min(50, Number(e.target.value) || 0)))} />
        </label>
        {running ? (
          <button type="button" className="btn-secondary" disabled={busy} onClick={() => void act(stopHistorian)}>
            <Square size={16} /> Stop
          </button>
        ) : (
          <button type="button" className="btn-primary" disabled={busy} onClick={() => void act(() => startHistorian({ year, advance_rate: rate, start_index: startIndex }))}>
            <Play size={16} /> Start replay
          </button>
        )}
      </div>
      {error ? <ErrorBanner title="Historian request failed" error={error} /> : null}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-sm text-ink-200">
        <span>{running ? "REPLAY RUNNING" : cursor?.finished ? "REPLAY FINISHED" : cursor?.started ? "REPLAY STOPPED" : "IDLE"}</span>
        {cursor?.started && cursor.source_year !== null && cursor.row_index !== null ? (
          <>
            <span>{sampleLabel(cursor.source_year, cursor.row_index)}</span>
            <span>tick {cursor.replay_tick}</span>
          </>
        ) : null}
      </div>
      <div>
        <div className="label mb-1">TEY (MWh as published), last {tey.length} rows</div>
        <Sparkline values={tey} />
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left font-mono text-xs tabular-nums">
          <thead>
            <tr className="border-b border-ink-700 text-ink-300">
              <th className="py-1 pr-3">tick</th>
              <th className="pr-3">year/row</th>
              {TABLE_COLS.map((c) => (
                <th key={c} className="pr-3">{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tail.length === 0 ? (
              <tr>
                <td colSpan={TABLE_COLS.length + 2} className="py-3 text-ink-400">No rows replayed yet.</td>
              </tr>
            ) : (
              tail.map((r) => (
                <tr key={r.replay_tick} className="border-b border-ink-800">
                  <td className="py-1 pr-3">{r.replay_tick}</td>
                  <td className="pr-3">{r.source_year} #{r.row_index}</td>
                  {TABLE_COLS.map((c) => (
                    <td key={c} className="pr-3">{fmtNum(r[c], 2)}</td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-ink-400">
        Real UCI samples replayed in order. The data has no timestamps, so none are shown; position is year, row index and replay tick.
      </p>
    </Card>
  );
}

function CmmsCard({ info }: { info?: ConnectorInfo }) {
  const drafts = useAsync((s) => getCmmsDrafts(s), []);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  async function addDemo() {
    setBusy(true);
    try {
      await createCmmsDraft("Demo draft from Connectors page", "Created by hand on the connectors page to show the draft-only flow. Not linked to a case.");
      drafts.reload();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  }
  const list = drafts.data?.drafts ?? [];
  return (
    <Card icon={<ClipboardList size={18} />} title="CMMS" mode="simulated">
      <p className="text-sm text-ink-300">{info?.description}</p>
      {drafts.error ? <ErrorBanner error={drafts.error} onRetry={drafts.reload} /> : null}
      {err ? <ErrorBanner error={err} /> : null}
      <ul className="space-y-2">
        {list.length === 0 ? <li className="text-sm text-ink-400">No draft work orders yet.</li> : null}
        {list.slice(0, 6).map((d) => (
          <li key={d.id} className="rounded-lg border border-ink-700 px-3 py-2 text-sm">
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium text-ink-100">{d.payload.title ?? d.id}</span>
              <span className="rounded border border-yellow-400 bg-yellow-100 px-1.5 py-0.5 text-xs font-semibold text-yellow-900">{d.status}</span>
            </div>
            <div className="font-mono text-xs text-ink-400">{d.id}</div>
          </li>
        ))}
      </ul>
      <button type="button" className="btn-secondary" disabled={busy} onClick={() => void addDemo()}>
        Create a demo draft
      </button>
    </Card>
  );
}

function NotificationsCard({ info }: { info?: ConnectorInfo }) {
  const outbox = useAsync((s) => getOutbox(s), []);
  const list = outbox.data?.notifications ?? [];
  return (
    <Card icon={<Bell size={18} />} title="Notifications" mode="simulated">
      <p className="text-sm text-ink-300">{info?.description}</p>
      {outbox.error ? <ErrorBanner error={outbox.error} onRetry={outbox.reload} /> : null}
      <ul className="space-y-2">
        {list.length === 0 ? <li className="text-sm text-ink-400">Outbox is empty. Completed investigations add routed notifications here.</li> : null}
        {list.slice(0, 6).map((n) => (
          <li key={n.id} className="rounded-lg border border-ink-700 px-3 py-2 text-sm">
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono text-xs text-ink-300">to {n.persona}</span>
              <span className="text-xs font-semibold text-ink-400">{n.delivery}</span>
            </div>
            <div className="mt-0.5 line-clamp-2 text-ink-100">{n.message}</div>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function ControlCard({ info }: { info?: ConnectorInfo }) {
  return (
    <Card icon={<Ban size={18} className="text-red-700" />} title="Control system" mode="not_connected" tone="red">
      <div className="text-lg font-semibold text-red-900">No write path exists. By design.</div>
      <p className="text-sm text-ink-200">{info?.description ?? "Not connected, no write path."}</p>
      <p className="text-sm text-ink-300">
        ThermoMind produces draft recommendations for people. It has no adapter to a PLC, DCS or SCADA system, for reading or writing.
      </p>
    </Card>
  );
}

export default function ConnectorsPage() {
  const status = useAsync((s) => getConnectorsStatus(s), []);
  const byKind = (k: ConnectorInfo["kind"]) => status.data?.connectors.find((c) => c.kind === k);
  return (
    <div>
      <PageHeader
        title="Plant connectors"
        subtitle="The adapter layer a pilot would plug real systems into. Every implementation here is simulated and labelled as such; nothing reaches a real plant system."
        right={<span className="inline-flex items-center gap-1.5 rounded-md border border-yellow-400 bg-yellow-100 px-2.5 py-1 text-sm font-semibold text-yellow-900"><ShieldCheck size={14} /> READ-ONLY · SIMULATED</span>}
      />
      {status.error ? <ErrorBanner className="mb-5" title="Could not load connector status" error={status.error} onRetry={status.reload} /> : null}
      <div className="mb-5 grid grid-cols-1 gap-4 xl:grid-cols-2">
        <div className="xl:col-span-2">
          <HistorianCard info={byKind("historian")} />
        </div>
        <CmmsCard info={byKind("cmms")} />
        <NotificationsCard info={byKind("notifier")} />
        <ControlCard info={byKind("control_system")} />
        <div className="panel">
          <div className="panel-header">
            <span className="panel-title">What a pilot needs</span>
          </div>
          <div className="space-y-3 px-5 py-4 text-sm text-ink-200">
            <div>
              <div className="label mb-1">Real adapters</div>
              <ul className="list-disc space-y-1 pl-5">
                <li>Read-only historian export, or an OPC UA read client (PI Web API / AVEVA)</li>
                <li>CMMS REST endpoint (SAP PM / Maximo) that accepts drafts a human approves</li>
                <li>Email gateway approved by plant IT</li>
              </ul>
            </div>
            <div>
              <div className="label mb-1">Security review</div>
              <ul className="list-disc space-y-1 pl-5">
                <li>Network segmentation: historian replica in a DMZ, no route to control networks</li>
                <li>Read-only service accounts with least privilege; credentials in a vault</li>
                <li>Data classification and retention agreed with plant owner</li>
                <li>Audit logging of every read and every draft; human sign-off before any action</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
      <InfoBanner>Replay is not live telemetry. A real adapter would implement the read-only historian interface; the control system interface has no methods beyond a statement that nothing is connected.</InfoBanner>
    </div>
  );
}
