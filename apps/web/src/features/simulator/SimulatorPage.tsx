import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Cpu, ExternalLink, FlaskConical, Pause, Play, RotateCcw, Search, Square, Trash2 } from "lucide-react";
import { createInvestigation, errorMessage } from "../../api/client";
import { MEASUREMENTS } from "../../api/types";
import { LivePlantSchematic } from "../../components/LivePlantSchematic";
import { ErrorBanner, Spinner, WarnBanner } from "../../components/Feedback";
import { fmtNum } from "../../lib/format";
import {
  FAULT_KINDS,
  SIM_CHANNELS,
  STREAM_URL,
  SimulatorUnavailable,
  getCalibration,
  getSimHistory,
  getSimState,
  injectFault,
  isNum,
  registerWindow,
  removeFault,
  runSimulator,
} from "./api";
import type { ActiveFault, Calibration, FaultKind, RunRequest, StepRecord } from "./api";

const MAX_RECORDS = 300;
const SPEEDS = [1, 2, 5, 10, 30, 60];
const STRIP: { key: keyof StepRecord; color: string }[] = [
  { key: "TEY", color: "#2563eb" },
  { key: "AFDP", color: "#7c3aed" },
  { key: "TIT", color: "#dc2626" },
  { key: "CDP", color: "#0d9488" },
];

function appendRecords(prev: StepRecord[], incoming: StepRecord[]): StepRecord[] {
  if (incoming.length === 0) return prev;
  const lastT = prev.length ? prev[prev.length - 1].t_s : -Infinity;
  const fresh = incoming.filter((r) => r && isNum(r.t_s) && r.t_s > lastT);
  if (fresh.length === 0) {
    // A reset can rewind t_s; if the newest incoming is older than our tail, restart the buffer.
    const newest = incoming[incoming.length - 1];
    if (newest && isNum(newest.t_s) && newest.t_s < lastT - 1e-9 && incoming.length === 1) return [newest];
    return prev;
  }
  const next = prev.concat(fresh);
  return next.length > MAX_RECORDS ? next.slice(next.length - MAX_RECORDS) : next;
}

function StripChart({ data, k, color }: { data: StepRecord[]; k: keyof StepRecord; color: string }) {
  const unit = (MEASUREMENTS[k as string]?.unit ?? "").split(" ")[0];
  const rows = useMemo(() => data.map((r) => ({ t: r.t_s, v: isNum(r[k]) ? (r[k] as number) : null })), [data, k]);
  const last = rows.length ? rows[rows.length - 1].v : null;
  return (
    <div className="panel">
      <div className="flex items-baseline justify-between px-4 pt-3">
        <div className="text-sm font-semibold text-ink-100">
          {String(k)} <span className="font-normal text-ink-400">· {MEASUREMENTS[k as string]?.name}</span>
        </div>
        <div className="font-mono text-sm text-ink-50">
          {fmtNum(last, 2)} <span className="text-ink-400">{unit}</span>
        </div>
      </div>
      <div className="h-36 px-1 pb-2" role="img" aria-label={`${String(k)} strip chart, last ${rows.length} simulated samples`}>
        {rows.length ? (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="#e2e6ec" strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} hide />
              <YAxis domain={["auto", "auto"]} width={52} stroke="#cbd5e1" tickLine={false} tick={{ fontSize: 11 }} tickFormatter={(v: number) => fmtNum(v, 1)} />
              <Tooltip
                isAnimationActive={false}
                formatter={(v: number) => [`${fmtNum(v, 2)} ${unit}`, String(k)]}
                labelFormatter={(t: number) => `sim t = ${fmtNum(t, 0)} s`}
              />
              <Line type="monotone" dataKey="v" stroke={color} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls={false} />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-ink-400">No samples yet.</div>
        )}
      </div>
    </div>
  );
}

export default function SimulatorPage() {
  const [unavailable, setUnavailable] = useState(false);
  const [status, setStatus] = useState<string>("unknown");
  const [speed, setSpeed] = useState<number>(1);
  const [faults, setFaults] = useState<ActiveFault[]>([]);
  const [records, setRecords] = useState<StepRecord[]>([]);
  const [transport, setTransport] = useState<"sse" | "polling" | "idle">("idle");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const [year, setYear] = useState(2015);
  const [startIndex, setStartIndex] = useState(0);

  const [faultKind, setFaultKind] = useState<FaultKind>("intake_fouling");
  const [magnitude, setMagnitude] = useState(1);
  const [channel, setChannel] = useState<string>("TIT");

  const [calib, setCalib] = useState<Calibration | null>(null);
  const [calibErr, setCalibErr] = useState<string | null>(null);

  const [useMeta, setUseMeta] = useState(false);
  const [invBusy, setInvBusy] = useState(false);
  const [invErr, setInvErr] = useState<unknown>(null);
  const [caseId, setCaseId] = useState<string | null>(null);

  const latest = records.length ? records[records.length - 1] : null;
  const running = status === "running";

  const handleErr = useCallback((e: unknown) => {
    if (e instanceof SimulatorUnavailable) setUnavailable(true);
    else if ((e as Error)?.name !== "AbortError") setError(e);
  }, []);

  const refreshState = useCallback(async (signal?: AbortSignal) => {
    const s = await getSimState(signal);
    if (typeof s.status === "string") setStatus(s.status);
    if (isNum(s.speed)) setSpeed(s.speed);
    setFaults(Array.isArray(s.faults) ? s.faults.filter((f) => f && typeof f.id === "string") : []);
    if (s.record && isNum(s.record.t_s)) setRecords((prev) => appendRecords(prev, [s.record as StepRecord]));
    return s;
  }, []);

  // Initial load: state + history + calibration.
  useEffect(() => {
    const ac = new AbortController();
    (async () => {
      try {
        await refreshState(ac.signal);
        const h = await getSimHistory(MAX_RECORDS, ac.signal);
        const recs = Array.isArray(h.records) ? h.records.filter((r) => r && isNum(r.t_s)) : [];
        if (recs.length) setRecords(recs.slice(-MAX_RECORDS));
      } catch (e) {
        handleErr(e);
      }
      try {
        setCalib(await getCalibration(ac.signal));
      } catch (e) {
        if ((e as Error)?.name !== "AbortError") setCalibErr(errorMessage(e));
      }
    })();
    return () => ac.abort();
  }, [refreshState, handleErr]);

  // Live data: SSE with 1 s polling fallback.
  useEffect(() => {
    if (unavailable) return;
    let es: EventSource | null = null;
    let poll: number | null = null;
    let closed = false;
    const startPolling = () => {
      if (poll !== null || closed) return;
      setTransport("polling");
      poll = window.setInterval(() => {
        refreshState().catch(handleErr);
      }, 1000);
    };
    if (typeof EventSource !== "undefined") {
      try {
        es = new EventSource(STREAM_URL);
        es.onopen = () => setTransport("sse");
        es.onmessage = (ev) => {
          try {
            const rec = JSON.parse(ev.data) as StepRecord;
            if (rec && isNum(rec.t_s)) setRecords((prev) => appendRecords(prev, [rec]));
          } catch {
            /* ignore malformed event */
          }
        };
        es.onerror = () => {
          es?.close();
          es = null;
          startPolling();
        };
      } catch {
        startPolling();
      }
    } else {
      startPolling();
    }
    // Status + fault list are not in the stream; refresh them slowly regardless.
    const statusTimer = window.setInterval(() => {
      if (es) refreshState().catch(handleErr);
    }, 2000);
    return () => {
      closed = true;
      es?.close();
      if (poll !== null) window.clearInterval(poll);
      window.clearInterval(statusTimer);
    };
  }, [unavailable, refreshState, handleErr]);

  const act = async (req: RunRequest) => {
    setBusy(true);
    setError(null);
    try {
      const s = await runSimulator(req);
      if (s && typeof s.status === "string") setStatus(s.status);
      if (req.action === "reset" || req.action === "start") setRecords([]);
      await refreshState();
    } catch (e) {
      handleErr(e);
    } finally {
      setBusy(false);
    }
  };

  const addFault = async () => {
    setBusy(true);
    setError(null);
    try {
      await injectFault({
        kind: faultKind,
        magnitude: Number.isFinite(magnitude) ? magnitude : 1,
        ...(faultKind.startsWith("sensor_") ? { channel } : {}),
      });
      await refreshState();
    } catch (e) {
      handleErr(e);
    } finally {
      setBusy(false);
    }
  };

  const dropFault = async (id: string) => {
    setBusy(true);
    try {
      await removeFault(id);
      await refreshState();
    } catch (e) {
      handleErr(e);
    } finally {
      setBusy(false);
    }
  };

  const investigate = async () => {
    setInvBusy(true);
    setInvErr(null);
    setCaseId(null);
    try {
      const reg = await registerWindow(120);
      const nReg = isNum(reg.n_rows) ? reg.n_rows : isNum(reg.rows) ? reg.rows : Math.min(120, records.length);
      const n = Math.max(1, nReg);
      const srcYear = isNum(latest?.source_year) ? (latest?.source_year as number) : year;
      const created = await createInvestigation({
        dataset_id: reg.dataset_id,
        scenario_id: "S01_NORMAL",
        year: srcYear,
        start_index: Math.max(0, n - 120),
        end_index: n,
        use_meta: useMeta,
      });
      setCaseId(created.case_id);
    } catch (e) {
      setInvErr(e instanceof SimulatorUnavailable ? new Error("simulator backend not available") : e);
    } finally {
      setInvBusy(false);
    }
  };

  const mae = calib?.per_channel_mae && typeof calib.per_channel_mae === "object" ? Object.entries(calib.per_channel_mae) : [];
  const fitted = calib?.fitted_params && typeof calib.fitted_params === "object" ? Object.entries(calib.fitted_params) : [];

  return (
    <div className="space-y-5">
      <div role="note" className="sticky top-0 z-10 flex items-start gap-3 rounded-xl border-2 border-yellow-400 bg-yellow-50 px-4 py-3 text-yellow-900 shadow-sm">
        <FlaskConical size={20} className="mt-0.5 shrink-0" />
        <div className="text-base font-semibold">
          PHYSICS SIMULATION — a software model calibrated to public data; no real plant is connected; simulator controls act on the model only
        </div>
      </div>

      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-ink-50">Plant simulator</h1>
          <p className="mt-1 text-base text-ink-300">
            Ambient inputs replay real UCI rows; everything downstream is computed by the model. Inject synthetic faults to see how the
            monitoring pipeline reacts.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="rounded-md border border-ink-600 bg-white px-2.5 py-1 font-mono text-ink-200">
            status: <b>{status}</b>
          </span>
          <span className="rounded-md border border-ink-600 bg-white px-2.5 py-1 font-mono text-ink-200">feed: {transport}</span>
          {latest ? (
            <span className="rounded-md border border-ink-600 bg-white px-2.5 py-1 font-mono text-ink-200">
              t = {fmtNum(latest.t_s, 0)} s · src {latest.source_year ?? "—"}#{latest.row_index ?? "—"}
            </span>
          ) : null}
        </div>
      </div>

      {unavailable ? (
        <WarnBanner>
          <b>simulator backend not available</b> — the API did not expose <code className="font-mono">/api/simulator/*</code> (HTTP 404).
        </WarnBanner>
      ) : null}
      {error ? <ErrorBanner error={error} title="Simulator request failed" onRetry={() => setError(null)} /> : null}

      <div className="grid gap-5 xl:grid-cols-[340px_minmax(0,1fr)]">
        {/* control panel */}
        <div className="space-y-5">
          <div className="panel p-4">
            <div className="panel-title mb-3">Run control</div>
            <div className="grid grid-cols-2 gap-3">
              <label className="block">
                <span className="label">Source year</span>
                <select className="input mt-1 w-full" value={year} onChange={(e) => setYear(Number(e.target.value))}>
                  {[2011, 2012, 2013, 2014, 2015].map((y) => (
                    <option key={y} value={y}>{y}</option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="label">Start index</span>
                <input className="input mt-1 w-full" type="number" min={0} value={startIndex} onChange={(e) => setStartIndex(Math.max(0, Number(e.target.value) || 0))} />
              </label>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <button type="button" className="btn-primary h-9 px-3 text-sm" disabled={busy || unavailable} onClick={() => act({ action: "start", year, start_index: startIndex })}>
                <Play size={14} /> Start
              </button>
              {running ? (
                <button type="button" className="btn-secondary h-9 px-3 text-sm" disabled={busy || unavailable} onClick={() => act({ action: "pause" })}>
                  <Pause size={14} /> Pause
                </button>
              ) : (
                <button type="button" className="btn-secondary h-9 px-3 text-sm" disabled={busy || unavailable} onClick={() => act({ action: "resume" })}>
                  <Play size={14} /> Resume
                </button>
              )}
              <button type="button" className="btn-secondary h-9 px-3 text-sm" disabled={busy || unavailable} onClick={() => act({ action: "stop" })}>
                <Square size={14} /> Stop
              </button>
              <button type="button" className="btn-secondary h-9 px-3 text-sm" disabled={busy || unavailable} onClick={() => act({ action: "reset" })}>
                <RotateCcw size={14} /> Reset
              </button>
            </div>
            <label className="mt-3 block">
              <span className="label">Speed (simulated hours per wall second)</span>
              <select
                className="input mt-1 w-full"
                value={speed}
                disabled={busy || unavailable}
                onChange={(e) => {
                  const v = Number(e.target.value);
                  setSpeed(v);
                  void act({ action: "speed", speed: v });
                }}
              >
                {(SPEEDS.includes(speed) ? SPEEDS : [...SPEEDS, speed].sort((a, b) => a - b)).map((s) => (
                  <option key={s} value={s}>{s}×</option>
                ))}
              </select>
            </label>
          </div>

          <div className="panel p-4">
            <div className="panel-title mb-1">Inject synthetic fault</div>
            <p className="mb-3 text-sm text-ink-300">Acts on the model only. Affected channels turn yellow (SYNTHETIC FAULT).</p>
            <label className="block">
              <span className="label">Kind</span>
              <select className="input mt-1 w-full" value={faultKind} onChange={(e) => setFaultKind(e.target.value as FaultKind)}>
                {FAULT_KINDS.map((k) => (
                  <option key={k} value={k}>{k.replace(/_/g, " ")}</option>
                ))}
              </select>
            </label>
            <div className="mt-3 grid grid-cols-2 gap-3">
              <label className="block">
                <span className="label">Magnitude</span>
                <input className="input mt-1 w-full" type="number" step="0.1" value={magnitude} onChange={(e) => setMagnitude(Number(e.target.value))} />
              </label>
              <label className="block">
                <span className="label">Channel</span>
                <select className="input mt-1 w-full" value={channel} disabled={!faultKind.startsWith("sensor_")} onChange={(e) => setChannel(e.target.value)}>
                  {SIM_CHANNELS.map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </label>
            </div>
            <button type="button" className="btn-primary mt-3 h-9 px-3 text-sm" disabled={busy || unavailable} onClick={addFault}>
              <FlaskConical size={14} /> Inject
            </button>

            <div className="mt-4 label">Active faults</div>
            {faults.length === 0 ? (
              <div className="mt-1 text-sm text-ink-400">None.</div>
            ) : (
              <ul className="mt-1 space-y-1.5">
                {faults.map((f) => (
                  <li key={f.id} className="flex items-center gap-2 rounded-md border border-yellow-300 bg-yellow-50 px-2.5 py-1.5 text-sm text-yellow-900">
                    <span className="min-w-0 flex-1 truncate">
                      <b>{String(f.kind ?? "fault").replace(/_/g, " ")}</b>
                      {isNum(f.magnitude) ? ` · ${fmtNum(f.magnitude, 2)}` : ""}
                      {f.channel ? ` · ${f.channel}` : ""}
                      <span className="ml-1 font-mono text-xs text-yellow-700">{f.id}</span>
                    </span>
                    <button type="button" className="rounded p-1 hover:bg-yellow-100" aria-label={`Remove fault ${f.id}`} disabled={busy} onClick={() => dropFault(f.id)}>
                      <Trash2 size={14} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        {/* schematic + charts */}
        <div className="min-w-0 space-y-5">
          <div className="panel">
            <div className="panel-header">
              <div>
                <div className="panel-title">Live simulated gas turbine train</div>
                <div className="mt-0.5 text-sm text-ink-300">
                  Generic schematic driven by the simulator — not the UCI facility and not a live plant. Particle speed follows modelled mass
                  flow and shaft power; combustor glow follows TIT; filter tint follows AFDP.
                </div>
              </div>
              <span className="inline-flex items-center gap-1.5 rounded-md border border-blue-300 bg-blue-50 px-2.5 py-1 text-sm font-semibold text-blue-800">
                <Cpu size={14} /> SIMULATED
              </span>
            </div>
            <div className="px-4 pb-3 pt-2">
              <LivePlantSchematic record={latest} running={running} />
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            {STRIP.map((s) => (
              <StripChart key={String(s.key)} data={records} k={s.key} color={s.color} />
            ))}
          </div>
          <div className="text-sm text-ink-400">Strip charts show the last {MAX_RECORDS} simulated steps (x = simulated time, seconds).</div>

          <div className="grid gap-5 lg:grid-cols-2">
            <div className="panel p-4">
              <div className="panel-title mb-1">Investigate the last 120 samples</div>
              <p className="mb-3 text-sm text-ink-300">
                Registers the simulator's most recent 120 steps as a dataset, then opens an investigation (scenario S01_NORMAL — no
                overlay added on top of the simulator's own faults).
              </p>
              <label className="mb-3 flex items-center gap-2 text-sm text-ink-200">
                <input type="checkbox" checked={useMeta} onChange={(e) => setUseMeta(e.target.checked)} />
                Use Meta Muse Spark (otherwise offline deterministic preview)
              </label>
              <button type="button" className="btn-primary h-9 px-3 text-sm" disabled={invBusy || unavailable || records.length === 0} onClick={investigate}>
                {invBusy ? <Spinner /> : <Search size={14} />} Investigate last 120 samples
              </button>
              {caseId ? (
                <div className="mt-3 text-sm">
                  Case created:{" "}
                  <Link className="inline-flex items-center gap-1 font-mono font-semibold text-blue-700 underline" to={`/investigations/${encodeURIComponent(caseId)}`}>
                    {caseId} <ExternalLink size={12} />
                  </Link>
                </div>
              ) : null}
              {invErr ? <ErrorBanner className="mt-3" error={invErr} title="Investigation failed" /> : null}
            </div>

            <div className="panel p-4">
              <div className="panel-title mb-1">Model calibration</div>
              <p className="mb-3 text-sm text-ink-300">
                Mean absolute error per channel — calibrated to UCI steady states; not a measurement of a real plant.
              </p>
              {calibErr ? (
                <div className="text-sm text-ink-400">{calibErr === "simulator backend not available" ? calibErr : `Calibration unavailable: ${calibErr}`}</div>
              ) : !calib ? (
                <div className="text-sm text-ink-400">Loading…</div>
              ) : (
                <>
                  {mae.length ? (
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-left text-ink-400">
                          <th className="py-1 font-medium">Channel</th>
                          <th className="py-1 text-right font-medium">MAE</th>
                          <th className="py-1 pl-2 font-medium">Unit</th>
                        </tr>
                      </thead>
                      <tbody>
                        {mae.map(([k, v]) => (
                          <tr key={k} className="border-t border-ink-700">
                            <td className="py-1 font-mono font-semibold text-ink-100">{k}</td>
                            <td className="py-1 text-right font-mono tabular-nums text-ink-50">{fmtNum(isNum(v) ? v : null, 3)}</td>
                            <td className="py-1 pl-2 text-ink-400">{(MEASUREMENTS[k]?.unit ?? "").split(" ")[0]}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <div className="text-sm text-ink-400">No per-channel MAE reported.</div>
                  )}
                  {fitted.length ? (
                    <details className="mt-3 text-sm">
                      <summary className="cursor-pointer text-ink-300">Fitted parameters ({fitted.length})</summary>
                      <ul className="mt-1 space-y-0.5 font-mono text-xs text-ink-200">
                        {fitted.map(([k, v]) => (
                          <li key={k}>
                            {k}: {isNum(v) ? fmtNum(v, 4) : JSON.stringify(v)}
                          </li>
                        ))}
                      </ul>
                    </details>
                  ) : null}
                  {Array.isArray(calib.notes) && calib.notes.length ? (
                    <ul className="mt-3 list-disc space-y-0.5 pl-5 text-sm text-ink-300">
                      {calib.notes.map((n, i) => (
                        <li key={i}>{String(n)}</li>
                      ))}
                    </ul>
                  ) : null}
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export { LivePlantSchematic };
