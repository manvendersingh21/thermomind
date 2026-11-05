import {
  Activity,
  ArrowRight,
  CheckCircle2,
  Play,
  Radio,
  RotateCcw,
  ShieldAlert,
  Square,
  Wifi,
  WifiOff,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { ErrorBanner, InfoBanner, PanelSkeleton, WarnBanner } from "../../components/Feedback";
import { PageHeader } from "../../components/Layout";
import { SourceBadge } from "../../components/SourceBadge";
import type { SourceBadgeVariant } from "../../components/SourceBadge";
import { fmtNum } from "../../lib/format";
import { WATCHDOG_STREAM_URL, getWatchdogState, runWatchdog } from "./api";
import { AuxBoard, WINDING_STYLE, motorStateLabel, windingLevel } from "./AuxBoard";
import type {
  DelibBackend,
  Execution,
  HumanTask,
  Motor,
  Proposal,
  RunRequest,
  WatchdogEvent,
  WatchdogState,
} from "./types";

const BANNER = "Auto-execution exists only inside the simulated auxiliaries model. ThermoMind has no write path to any real plant.";
const MAX_EVENTS = 60;
const POLL_MS = 1500;

const PERSONAS = [
  "shift_supervisor",
  "plant_manager",
  "electrical_engineer",
  "mechanical_maintenance_engineer",
  "control_room_operator",
];

const hum = (s: string) => s.replace(/_/g, " ");

/** hh:mm:ss of simulated time. */
export function fmtSimTime(s: number): string {
  const t = Math.max(0, Math.floor(s));
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const sec = t % 60;
  return [h, m, sec].map((v) => String(v).padStart(2, "0")).join(":");
}

type StreamMode = "connecting" | "live stream" | "polling";

/** Live state: SSE first; on error close it and poll GET /state. */
function useWatchdogState() {
  const [state, setState] = useState<WatchdogState | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [mode, setMode] = useState<StreamMode>("connecting");
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let es: EventSource | null = null;
    let timer: number | null = null;
    const ctrl = new AbortController();

    const poll = async () => {
      try {
        const s = await getWatchdogState(ctrl.signal);
        if (cancelled) return;
        setState(s);
        setError(null);
      } catch (e) {
        if (!cancelled) setError(e);
      }
    };
    const startPolling = () => {
      if (cancelled || timer !== null) return;
      setMode("polling");
      void poll();
      timer = window.setInterval(() => void poll(), POLL_MS);
    };

    // Initial full snapshot (history_points=60) so the page is not empty while the stream connects.
    void poll();

    if (typeof EventSource === "undefined") {
      startPolling();
    } else {
      es = new EventSource(WATCHDOG_STREAM_URL);
      es.addEventListener("open", () => {
        if (!cancelled) setMode("live stream");
      });
      es.addEventListener("state", (ev) => {
        if (cancelled) return;
        try {
          setState(JSON.parse((ev as MessageEvent<string>).data) as WatchdogState);
          setError(null);
          setMode("live stream");
        } catch {
          /* ignore malformed frame */
        }
      });
      es.addEventListener("error", () => {
        es?.close();
        es = null;
        startPolling();
      });
    }
    return () => {
      cancelled = true;
      ctrl.abort();
      es?.close();
      if (timer !== null) window.clearInterval(timer);
    };
  }, [nonce]);

  const refresh = useCallback(async () => {
    try {
      setState(await getWatchdogState());
      setError(null);
    } catch (e) {
      setError(e);
    }
  }, []);
  const reconnect = useCallback(() => setNonce((n) => n + 1), []);
  return { state, error, mode, refresh, reconnect };
}

/* ---------- small pieces ---------- */

function Chip({ children, cls, title }: { children: ReactNode; cls: string; title?: string }) {
  return (
    <span title={title} className={`inline-flex items-center gap-1 whitespace-nowrap rounded-md border px-2 py-0.5 text-xs font-semibold tracking-wide ${cls}`}>
      {children}
    </span>
  );
}

const EVENT_STYLE: Record<string, { cls: string; stage: number }> = {
  detection: { cls: "border-amber-400 bg-amber-50 text-amber-900", stage: 0 },
  proposal: { cls: "border-blue-300 bg-blue-50 text-blue-800", stage: 1 },
  deliberation: { cls: "border-indigo-300 bg-indigo-50 text-indigo-800", stage: 2 },
  execution: { cls: "border-green-300 bg-green-50 text-green-800", stage: 3 },
  human_required: { cls: "border-yellow-400 bg-yellow-100 text-yellow-900", stage: 3 },
  decision: { cls: "border-green-300 bg-white text-green-800", stage: 3 },
  interlock: { cls: "border-orange-300 bg-orange-50 text-orange-900", stage: 3 },
  trip: { cls: "border-red-300 bg-red-50 text-red-900", stage: 0 },
  fault_injected: { cls: "border-yellow-400 bg-yellow-100 text-yellow-900", stage: 0 },
};
const EVENT_DEFAULT = { cls: "border-ink-600 bg-ink-800 text-ink-200", stage: 0 };
const STAGE_INDENT = ["", "ml-3", "ml-6", "ml-9"];

function deliberationBadge(mode: string, label: string): ReactNode {
  let variant: SourceBadgeVariant = "review";
  let text = "REVIEW";
  if (mode === "meta_live") {
    variant = "meta";
    text = "META LIVE";
  } else if (mode === "offline_fallback") {
    variant = "offline";
    text = "OFFLINE";
  } else if (mode === "meta_live_rejected") {
    variant = "review";
    text = "META REJECTED — REVIEW";
  } else if (mode === "deliberation_module") {
    variant = "model";
    text = "DELIBERATION MODULE";
  }
  return <SourceBadge variant={variant} size="sm" label={text} title={label} />;
}

type Outcome = { label: string; cls: string; icon: ReactNode };
function proposalOutcome(p: Proposal, execs: Execution[], tasks: HumanTask[]): Outcome {
  const ex = execs.find((e) => e.proposal_id === p.id);
  if (ex) {
    if (ex.status === "completed" || ex.status === "in_progress")
      return { label: ex.status === "in_progress" ? "executing in simulated auxiliaries" : "executed in simulated auxiliaries", cls: "border-green-300 bg-green-50 text-green-800", icon: <CheckCircle2 size={13} /> };
    if (ex.status === "blocked_by_interlock")
      return { label: "blocked by interlock", cls: "border-orange-300 bg-orange-50 text-orange-900", icon: <ShieldAlert size={13} /> };
    return { label: `execution ${hum(ex.status)}`, cls: "border-red-300 bg-red-50 text-red-900", icon: <XCircle size={13} /> };
  }
  const t = tasks.find((x) => x.proposal_id === p.id);
  if (t) {
    if (t.status === "awaiting_human")
      return { label: "awaiting human", cls: "border-yellow-400 bg-yellow-100 text-yellow-900", icon: <ShieldAlert size={13} /> };
    return { label: `human ${t.status} — recorded, nothing executed on any plant`, cls: "border-ink-600 bg-white text-ink-200", icon: <CheckCircle2 size={13} /> };
  }
  if (p.routing?.route === "human_required")
    return { label: "awaiting human", cls: "border-yellow-400 bg-yellow-100 text-yellow-900", icon: <ShieldAlert size={13} /> };
  return { label: "pending routing", cls: "border-ink-600 bg-ink-800 text-ink-200", icon: <Activity size={13} /> };
}

/* ---------- panels ---------- */

function MotorDetail({ m }: { m: Motor }) {
  const w = 360;
  const h = 110;
  const pts = m.history;
  const lo = 0;
  const hi = Math.max(m.limit_c + 10, ...pts.map((p) => p.winding_c));
  const tMin = pts.length ? pts[0].t_s : 0;
  const tMax = pts.length ? pts[pts.length - 1].t_s : 1;
  const px = (t: number) => 6 + ((t - tMin) / Math.max(1, tMax - tMin)) * (w - 12);
  const py = (c: number) => h - 6 - ((c - lo) / (hi - lo)) * (h - 12);
  const line = pts.map((p) => `${px(p.t_s).toFixed(1)},${py(p.winding_c).toFixed(1)}`).join(" ");
  const ws = WINDING_STYLE[windingLevel(m)];
  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-title">{m.name} ({m.asset_id})</div>
        <SourceBadge variant="synthetic" size="sm" label="SIMULATED" />
      </div>
      <div className="grid gap-4 p-5 md:grid-cols-[minmax(0,380px)_1fr]">
        <div>
          <div className="mb-1 text-sm text-ink-300">Winding temperature, recent history (simulated time {fmtSimTime(tMin)} to {fmtSimTime(tMax)})</div>
          <svg viewBox={`0 0 ${w} ${h}`} width="100%" role="img" aria-label={`Winding temperature history of ${m.name}; now ${fmtNum(m.winding_c, 1)} °C, alarm ${m.alarm_c} °C, limit ${m.limit_c} °C`} className="block h-auto w-full rounded-md border border-ink-700 bg-white">
            <line x1={0} x2={w} y1={py(m.alarm_c)} y2={py(m.alarm_c)} stroke="#ca8a04" strokeDasharray="5 3" />
            <line x1={0} x2={w} y1={py(m.limit_c)} y2={py(m.limit_c)} stroke="#b91c1c" strokeDasharray="5 3" />
            <text x={w - 4} y={py(m.alarm_c) - 2} textAnchor="end" fontSize={9} fill="#854d0e">alarm {m.alarm_c} °C</text>
            <text x={w - 4} y={py(m.limit_c) - 2} textAnchor="end" fontSize={9} fill="#7f1d1d">limit {m.limit_c} °C</text>
            {pts.length > 1 ? <polyline points={line} fill="none" stroke="#2563eb" strokeWidth={2} /> : <text x={10} y={20} fontSize={11} fill="#64748b">no history yet</text>}
          </svg>
        </div>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-base sm:grid-cols-3">
          <Stat k="Winding" v={`${fmtNum(m.winding_c, 1)} °C`} sub={ws.label} />
          <Stat k="Current" v={`${fmtNum(m.current_a, 1)} A`} sub={m.expected_current_a !== null ? `expected ${fmtNum(m.expected_current_a, 1)} A` : `rated ${fmtNum(m.rated_current_a, 1)} A`} />
          <Stat k="Bearing" v={`${fmtNum(m.bearing_c, 1)} °C`} />
          <Stat k="Vibration" v={`${fmtNum(m.vibration_mm_s, 2)} mm/s`} sub={m.vibration_zone ? `ISO zone ${m.vibration_zone}` : "zone —"} />
          <Stat k="Insulation" v={`${fmtNum(m.insulation_mohm, 0)} MΩ`} />
          <Stat k="I²R loss" v={`${fmtNum(m.i2r_loss_kw, 2)} kW`} />
          <Stat k="State" v={motorStateLabel(m.state)} sub={`${m.role}${m.tagged_out ? " · TAGGED OUT" : ""}`} />
          <Stat k="Trip reason" v={m.trip_reason ?? "none"} />
          <Stat k="Responsible" v={hum(m.responsible_persona)} />
        </dl>
      </div>
    </div>
  );
}

function Stat({ k, v, sub }: { k: string; v: string; sub?: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-sm text-ink-400">{k}</dt>
      <dd className="break-words font-mono text-base font-semibold text-ink-50">{v}</dd>
      {sub ? <div className="text-xs text-ink-400">{sub}</div> : null}
    </div>
  );
}

function UnitPanel({ s }: { s: WatchdogState }) {
  const u = s.unit;
  const max = Math.max(u.dispatch_setpoint_mwh, u.available_mwh, u.output_mwh, 1) * 1.05;
  const bar = (label: string, v: number, color: string) => (
    <div>
      <div className="flex justify-between text-sm">
        <span className="text-ink-300">{label}</span>
        <span className="font-mono font-semibold text-ink-50">{fmtNum(v, 1)} MWh</span>
      </div>
      <div className="mt-1 h-3 rounded bg-ink-800" role="presentation">
        <div className="h-3 rounded" style={{ width: `${Math.min(100, (v / max) * 100)}%`, background: color }} />
      </div>
    </div>
  );
  const short = u.shortfall_mwh > 0.05;
  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-title">Unit — dispatch vs capability</div>
        <SourceBadge variant="synthetic" size="sm" label="SIMULATED" />
      </div>
      <div className="space-y-3 p-5">
        <div className="text-sm text-ink-300">Unit of measure: {u.unit_of_measure}</div>
        {bar("Dispatch setpoint", u.dispatch_setpoint_mwh, "#64748b")}
        {bar("Available (min of aux- and thermal-limited)", u.available_mwh, "#2563eb")}
        {bar("Output", u.output_mwh, "#16a34a")}
        <div className={`rounded-lg border px-3 py-2 ${short ? "border-red-300 bg-red-50 text-red-900" : "border-green-300 bg-green-50 text-green-900"}`}>
          <span className="font-semibold">{short ? "SHORTFALL" : "NO SHORTFALL"}</span>{" "}
          <span className="font-mono">{fmtNum(u.shortfall_mwh, 2)} MWh per hourly sample</span>
        </div>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2">
          <Stat k="Cooling capacity" v={`${fmtNum(u.cooling_capacity_frac * 100, 0)} %`} sub={`CW ${fmtNum(u.cw_capacity_frac * 100, 0)} % · fans ${fmtNum(u.fan_airflow_frac * 100, 0)} %`} />
          <Stat k="Aux-limited" v={`${fmtNum(u.aux_limited_mwh, 1)} MWh`} sub={`binding: ${u.aux_binding}`} />
          <Stat k="Thermal-limited" v={`${fmtNum(u.thermal_limited_mwh, 1)} MWh`} sub={`binding: ${u.thermal_binding}`} />
          <Stat k="Demand step" v={`${fmtNum(u.demand_step_mwh, 0)} MWh`} />
        </dl>
        <div className="space-y-1 border-t border-ink-700 pt-3 text-sm text-ink-300">
          <div>
            <SourceBadge variant="real" size="sm" label="REAL UCI ROWS" /> <span className="ml-1">{s.source.label}</span>
          </div>
          {s.source.row_index !== undefined ? (
            <div className="font-mono text-ink-400">
              {s.source.source_year} • sample #{s.source.row_index}
              {s.source.TEY_mwh !== undefined ? ` · TEY ${fmtNum(s.source.TEY_mwh, 1)} MWh` : ""}
              {s.source.AT_c !== undefined ? ` · AT ${fmtNum(s.source.AT_c, 1)} °C` : ""}
            </div>
          ) : null}
          <div>
            Simulated time <span className="font-mono font-semibold text-ink-50">{fmtSimTime(s.sim_time_s)}</span> (simulated time, not wall clock) · speed {fmtNum(s.speed, 0)}×
          </div>
        </div>
      </div>
    </div>
  );
}

function Controls({ s, busy, act }: { s: WatchdogState; busy: boolean; act: (r: RunRequest | RunRequest[]) => void }) {
  const [speed, setSpeed] = useState(60);
  const [step, setStep] = useState("60");
  const stepVal = Number(step);
  const stepOk = step.trim() !== "" && Number.isFinite(stepVal) && stepVal >= -200 && stepVal <= 200;
  const cwpB = s.auxiliaries.motors.find((m) => m.asset_id === "CWP_B");
  const backendMode: DelibBackend = s.deliberation_backend === "builtin" || s.deliberation_backend === "shared" ? s.deliberation_backend : "auto";
  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-title">Controls (simulator only)</div>
        <Chip cls={s.running ? "border-green-300 bg-green-50 text-green-800" : "border-ink-600 bg-ink-800 text-ink-200"}>
          {s.running ? "SIM RUNNING" : "SIM STOPPED"}
        </Chip>
      </div>
      <div className="space-y-4 p-5">
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1.5">
            <span className="label">Speed (sim s per real s)</span>
            <select className="input w-28" value={speed} disabled={busy} onChange={(e) => setSpeed(Number(e.target.value))}>
              {[10, 60, 300, 600].map((v) => (
                <option key={v} value={v}>{v}×</option>
              ))}
            </select>
          </label>
          <button type="button" className="btn-primary h-10 px-4" disabled={busy} onClick={() => act({ action: "start", speed })}>
            <Play size={16} /> {s.running ? "Set speed" : "Start"}
          </button>
          <button type="button" className="btn-secondary h-10 px-4" disabled={busy || !s.running} onClick={() => act({ action: "stop" })}>
            <Square size={16} /> Stop
          </button>
          <button type="button" className="btn-secondary h-10 px-4" disabled={busy} onClick={() => act({ action: "reset" })}>
            <RotateCcw size={16} /> Reset
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-3 border-t border-ink-700 pt-4">
          <button type="button" className="btn-amber h-10 px-4" disabled={busy} onClick={() => act({ action: "inject_fault", asset: "CWP_A", fault: "bearing_degradation", rate_per_min: 0.05 })}>
            Inject pump A bearing degradation
          </button>
          <button type="button" className="btn-amber h-10 px-4" disabled={busy} onClick={() => act({ action: "inject_fault", asset: "CTF_2", fault: "belt_slip" })}>
            Inject fan 2 belt slip
          </button>
          <button type="button" className="btn-secondary h-10 px-4" disabled={busy || s.auxiliaries.injected_faults.length === 0} onClick={() => act(s.auxiliaries.injected_faults.map((f) => ({ action: "clear_fault" as const, asset: f.asset_id })))}>
            Clear injected faults
          </button>
          <span className="text-sm text-ink-400">Faults are SYNTHETIC and injected into the simulator only.</span>
        </div>

        <div className="flex flex-wrap items-end gap-3 border-t border-ink-700 pt-4">
          <label className="flex flex-col gap-1.5">
            <span className="label">Demand step (MWh per hourly sample)</span>
            <input className={`input w-28 font-mono ${stepOk ? "" : "border-red-400"}`} type="number" min={-200} max={200} step={5} value={step} disabled={busy} onChange={(e) => setStep(e.target.value)} />
          </label>
          <button type="button" className="btn-amber h-10 px-4" disabled={busy || !stepOk} onClick={() => act({ action: "demand_step", mwh: stepVal })}>
            Demand step {stepOk && stepVal > 0 ? "+" : ""}{stepOk ? stepVal : "X"}
          </button>
          <button type="button" className="btn-secondary h-10 px-4" disabled={busy} onClick={() => act({ action: "demand_step", mwh: 0 })}>
            Clear step
          </button>
          <button
            type="button"
            className="btn-secondary h-10 px-4"
            disabled={busy || !cwpB}
            aria-pressed={cwpB?.tagged_out ?? false}
            onClick={() => act({ action: "tag_out", asset: "CWP_B", tagged: !(cwpB?.tagged_out ?? false) })}
          >
            {cwpB?.tagged_out ? "Return pump B to service (remove tag-out)" : "Tag out pump B"}
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-x-6 gap-y-3 border-t border-ink-700 pt-4">
          <label className="inline-flex items-center gap-2 text-base text-ink-100">
            <input
              type="checkbox"
              checked={s.policy.auto_execute_simulated_switchover}
              disabled={busy}
              onChange={(e) => act({ action: "set_policy", auto_execute: e.target.checked })}
            />
            auto-execute low-risk switchovers in simulator
          </label>
          <label className="inline-flex items-center gap-2 text-base text-ink-100">
            <span className="text-ink-300">Deliberation backend</span>
            <select
              className="input w-64"
              value={backendMode}
              disabled={busy}
              aria-label="Deliberation backend"
              onChange={(e) => act({ action: "set_policy", deliberation_backend: e.target.value as DelibBackend })}
            >
              <option value="auto">auto (by action class)</option>
              <option value="builtin">builtin (one Muse Spark call)</option>
              <option value="shared">shared deliberation feature</option>
            </select>
          </label>
          <span className="text-sm text-ink-400">
            Active: {s.deliberation_backend}
            {s.deliberation_paths
              ? ` · switchover → ${s.deliberation_paths.simulated_auxiliary_switchover ?? "?"}, unit commitment → ${s.deliberation_paths.unit_commitment ?? "?"}`
              : ""}
          </span>
        </div>
      </div>
    </div>
  );
}

function EventFeed({ events }: { events: WatchdogEvent[] }) {
  const list = useMemo(() => [...events].sort((a, b) => b.seq - a.seq).slice(0, MAX_EVENTS), [events]);
  return (
    <div className="panel">
      <div className="panel-header">
        <div className="min-w-0">
          <div className="panel-title">Live event feed (newest first, max {MAX_EVENTS})</div>
          <div className="mt-1 flex flex-wrap items-center gap-1 text-xs text-ink-300">
            <span>Pipeline:</span>
            <Chip cls={EVENT_STYLE.detection.cls}>detection</Chip><ArrowRight size={12} />
            <Chip cls={EVENT_STYLE.proposal.cls}>proposal</Chip><ArrowRight size={12} />
            <Chip cls={EVENT_STYLE.deliberation.cls}>deliberation</Chip><ArrowRight size={12} />
            <Chip cls={EVENT_STYLE.execution.cls}>execution</Chip> / <Chip cls={EVENT_STYLE.human_required.cls}>human required</Chip>
          </div>
        </div>
      </div>
      <ol className="max-h-[480px] divide-y divide-ink-700 overflow-y-auto" aria-label="Watchdog events">
        {list.length === 0 ? <li className="px-5 py-6 text-base text-ink-400">No events yet. Start the simulator and inject a fault or a demand step.</li> : null}
        {list.map((e) => {
          const st = EVENT_STYLE[e.type] ?? EVENT_DEFAULT;
          return (
            <li key={e.seq} className="px-5 py-2">
              <div className={`flex items-start gap-2 ${STAGE_INDENT[st.stage]}`}>
                <Chip cls={st.cls}>{hum(e.type)}</Chip>
                <span className="shrink-0 font-mono text-xs text-ink-400" title="simulated time">{fmtSimTime(e.t_sim_s)}</span>
                <span className="min-w-0 break-words text-sm text-ink-100">{e.message}</span>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function PipelineStrip({ p, det, ex, outcome }: { p: Proposal; det?: string; ex?: Execution; outcome: Outcome }) {
  const step = (label: string, cls: string) => <Chip cls={cls}>{label}</Chip>;
  return (
    <div className="flex flex-wrap items-center gap-1 text-xs">
      {step(`detection${det ? ` ${det}` : ""}`, EVENT_STYLE.detection.cls)}<ArrowRight size={12} />
      {step("proposal", EVENT_STYLE.proposal.cls)}<ArrowRight size={12} />
      {step(p.deliberation ? `deliberation: ${hum(p.deliberation.answer.recommendation)}` : "deliberation pending", EVENT_STYLE.deliberation.cls)}<ArrowRight size={12} />
      <Chip cls={outcome.cls}>{outcome.icon} {ex ? `execution ${hum(ex.status)}` : outcome.label}</Chip>
    </div>
  );
}

function ProposalsList({ s }: { s: WatchdogState }) {
  const list = useMemo(() => [...s.proposals].sort((a, b) => b.t_sim_s - a.t_sim_s), [s.proposals]);
  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-title">Proposals</div>
        <span className="text-sm text-ink-400">{list.length} total</span>
      </div>
      <div className="space-y-4 p-5">
        {list.length === 0 ? <div className="text-base text-ink-400">No proposals yet.</div> : null}
        {list.map((p) => {
          const outcome = proposalOutcome(p, s.executions, s.human_tasks);
          const ex = s.executions.find((e) => e.proposal_id === p.id);
          const det = s.detections.find((d) => d.id === p.detection_id);
          const d = p.deliberation;
          return (
            <article key={p.id} className="rounded-xl border border-ink-700 bg-white p-4">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-xs text-ink-400">{p.id} · {fmtSimTime(p.t_sim_s)}</span>
                <Chip cls="border-ink-600 bg-ink-800 text-ink-200">{p.action_class}</Chip>
                {d ? deliberationBadge(d.mode, d.mode_label) : null}
                <Chip cls={outcome.cls}>{outcome.icon} {outcome.label}</Chip>
              </div>
              <div className="mt-2 text-base font-semibold text-ink-50">{p.intent}</div>
              {det ? <div className="mt-1 text-sm text-ink-300">Why: {det.rationale}</div> : null}
              <div className="mt-2"><PipelineStrip p={p} det={det?.asset} ex={ex} outcome={outcome} /></div>
              {d ? (
                <div className="mt-3 space-y-2 text-sm text-ink-100">
                  <div className="text-xs text-ink-400">{d.mode_label}{d.validated ? "" : " · NOT VALIDATED"}</div>
                  <div><span className="font-semibold">Recommendation:</span> {hum(d.answer.recommendation)} — {d.answer.summary}</div>
                  {d.answer.harms_elsewhere.length ? (
                    <div>
                      <span className="font-semibold">Harms elsewhere:</span>
                      <ul className="ml-5 list-disc">
                        {d.answer.harms_elsewhere.map((h, i) => <li key={i}><span className="font-medium">{h.subsystem}:</span> {h.effect}</li>)}
                      </ul>
                    </div>
                  ) : null}
                  {d.answer.conditions.length ? (
                    <div>
                      <span className="font-semibold">Conditions:</span>
                      <ul className="ml-5 list-disc">{d.answer.conditions.map((c, i) => <li key={i}>{c}</li>)}</ul>
                    </div>
                  ) : null}
                  {d.errors.length ? <div className="text-amber-900">Deliberation notes: {d.errors.join("; ")}</div> : null}
                </div>
              ) : <div className="mt-3 text-sm text-ink-400">Deliberation pending.</div>}
              {p.routing ? (
                <div className="mt-3 rounded-lg bg-ink-800 px-3 py-2 text-sm text-ink-200">
                  <span className="font-semibold">Routing:</span> {hum(p.routing.route)} · <span className="font-mono">{p.routing.policy_id}</span> — {p.routing.reason}
                </div>
              ) : null}
            </article>
          );
        })}
      </div>
    </div>
  );
}

function TaskCard({ t, busy, act }: { t: HumanTask; busy: boolean; act: (r: RunRequest | RunRequest[]) => void }) {
  const [persona, setPersona] = useState(PERSONAS.find((p) => t.who_must_approve.includes(p)) ?? "shift_supervisor");
  const [comment, setComment] = useState("");
  const decide = (decision: "approve" | "reject") =>
    act({ action: "decide", task_id: t.id, decision, persona, ...(comment.trim() ? { comment: comment.trim() } : {}) });
  return (
    <div className="rounded-xl border border-yellow-400 bg-yellow-50/60 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Chip cls="border-yellow-400 bg-yellow-100 text-yellow-900"><ShieldAlert size={13} /> HUMAN DECISION REQUIRED</Chip>
        <Chip cls="border-ink-600 bg-white text-ink-200">{t.action_class}</Chip>
        <span className="font-mono text-xs text-ink-400">{t.policy_id} · {t.id} · {fmtSimTime(t.t_sim_s)}</span>
      </div>
      <div className="mt-2 text-base font-semibold text-ink-50">{t.intent}</div>
      <div className="mt-1 text-sm text-ink-200"><span className="font-semibold">Recommendation:</span> {hum(t.recommendation)} — {t.summary}</div>
      <div className="mt-1 text-sm text-ink-300">{t.reason}</div>
      {t.conditions.length ? (
        <ul className="ml-5 mt-2 list-disc text-sm text-ink-100">{t.conditions.map((c, i) => <li key={i}>{c}</li>)}</ul>
      ) : null}
      <div className="mt-2 text-sm text-ink-200"><span className="font-semibold">Must approve:</span> {t.who_must_approve.map(hum).join(", ") || "—"}</div>
      <div className="text-sm text-ink-200"><span className="font-semibold">Notified:</span> {t.notified.map(hum).join(", ") || "—"}</div>
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1.5">
          <span className="label">Decide as</span>
          <select className="input w-64" value={persona} disabled={busy} onChange={(e) => setPersona(e.target.value)}>
            {PERSONAS.map((p) => <option key={p} value={p}>{hum(p)}</option>)}
          </select>
        </label>
        <label className="flex min-w-[12rem] flex-1 flex-col gap-1.5">
          <span className="label">Comment (optional)</span>
          <input className="input" value={comment} disabled={busy} onChange={(e) => setComment(e.target.value)} />
        </label>
        <button type="button" className="btn-primary h-10 px-4" disabled={busy} onClick={() => decide("approve")}>
          <CheckCircle2 size={16} /> Approve
        </button>
        <button type="button" className="btn-danger h-10 px-4" disabled={busy} onClick={() => decide("reject")}>
          <XCircle size={16} /> Reject
        </button>
      </div>
      <div className="mt-2 text-sm font-semibold text-ink-200">Your decision is recorded. Nothing is executed on any plant.</div>
    </div>
  );
}

function HumanPanel({ tasks, busy, act }: { tasks: HumanTask[]; busy: boolean; act: (r: RunRequest | RunRequest[]) => void }) {
  const open = tasks.filter((t) => t.status === "awaiting_human");
  const done = tasks.filter((t) => t.status !== "awaiting_human");
  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-title">Human decisions</div>
        <SourceBadge variant="review" size="sm" label="HUMAN REVIEW REQUIRED" />
      </div>
      <div className="space-y-4 p-5">
        {open.length === 0 ? <div className="text-base text-ink-400">Nothing awaiting a human decision.</div> : null}
        {open.map((t) => <TaskCard key={t.id} t={t} busy={busy} act={act} />)}
        {done.length ? (
          <div>
            <div className="mb-2 text-sm font-semibold text-ink-200">Decided</div>
            <ul className="space-y-2">
              {done.map((t) => (
                <li key={t.id} className="rounded-lg border border-ink-700 bg-white px-3 py-2 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <Chip cls={t.status === "approved" ? "border-green-300 bg-green-50 text-green-800" : "border-red-300 bg-red-50 text-red-900"}>{t.status.toUpperCase()}</Chip>
                    <span className="font-medium text-ink-50">{t.intent}</span>
                  </div>
                  {t.decision ? (
                    <div className="mt-1 text-ink-300">
                      {hum(t.decision.persona)}{t.decision.comment ? ` — "${t.decision.comment}"` : ""} · outcome: {t.decision.outcome}
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function Th({ children }: { children: ReactNode }) {
  return <th scope="col" className="whitespace-nowrap px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-ink-400">{children}</th>;
}

function ExecutionsTable({ list }: { list: Execution[] }) {
  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-title">Executions (inside SIMULATED auxiliaries only)</div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-ink-800"><tr><Th>What</Th><Th>Where</Th><Th>Policy</Th><Th>Approved by</Th><Th>Reversible</Th><Th>Status</Th><Th>Notified</Th></tr></thead>
          <tbody className="divide-y divide-ink-700">
            {list.length === 0 ? <tr><td colSpan={7} className="px-3 py-4 text-ink-400">No executions yet.</td></tr> : null}
            {list.map((e) => (
              <tr key={e.id} className="align-top">
                <td className="px-3 py-2">
                  {e.what}
                  {e.sequence_log?.length ? (
                    <details className="mt-1 text-xs text-ink-400">
                      <summary className="cursor-pointer">sequence log</summary>
                      <ul className="ml-4 list-disc font-mono">{e.sequence_log.map((l, i) => <li key={i}>{l}</li>)}</ul>
                    </details>
                  ) : null}
                </td>
                <td className="px-3 py-2">{e.where}</td>
                <td className="px-3 py-2 font-mono">{e.policy_id}</td>
                <td className="px-3 py-2">{e.approved_by}</td>
                <td className="px-3 py-2">{e.reversible ? "yes" : "no"}</td>
                <td className="px-3 py-2"><Chip cls={e.status === "completed" ? "border-green-300 bg-green-50 text-green-800" : e.status === "blocked_by_interlock" ? "border-orange-300 bg-orange-50 text-orange-900" : "border-ink-600 bg-ink-800 text-ink-200"}>{hum(e.status)}</Chip></td>
                <td className="px-3 py-2">{e.notified.map(hum).join(", ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PolicyTable({ s }: { s: WatchdogState }) {
  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-title">Policy table</div>
        <Chip cls={s.policy.auto_execute_simulated_switchover ? "border-green-300 bg-green-50 text-green-800" : "border-ink-600 bg-ink-800 text-ink-200"}>
          auto-execute in simulator: {s.policy.auto_execute_simulated_switchover ? "ON" : "OFF"}
        </Chip>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-ink-800"><tr><Th>Action class</Th><Th>Policy</Th><Th>Route</Th><Th>Reversible</Th><Th>Risk</Th></tr></thead>
          <tbody className="divide-y divide-ink-700">
            {s.policy.table.map((r) => (
              <tr key={r.policy_id} className="align-top">
                <td className="px-3 py-2"><div className="font-medium">{r.action_class}</div><div className="text-xs text-ink-400">{r.description}</div></td>
                <td className="px-3 py-2 font-mono">{r.policy_id}</td>
                <td className="px-3 py-2">{r.route}<div className="text-xs text-ink-400">{r.where}</div></td>
                <td className="px-3 py-2">{r.reversible ? "yes" : "no"}</td>
                <td className="px-3 py-2">{r.risk}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ---------- page ---------- */

export default function WatchdogPage() {
  const { state, error, mode, refresh, reconnect } = useWatchdogState();
  const [busy, setBusy] = useState(false);
  const [actError, setActError] = useState<unknown>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const inFlight = useRef(false);

  const act = useCallback(
    async (req: RunRequest | RunRequest[]) => {
      if (inFlight.current) return;
      inFlight.current = true;
      setBusy(true);
      setActError(null);
      try {
        for (const r of Array.isArray(req) ? req : [req]) await runWatchdog(r);
        await refresh();
      } catch (e) {
        setActError(e);
      } finally {
        inFlight.current = false;
        setBusy(false);
      }
    },
    [refresh],
  );

  const sel = state?.auxiliaries.motors.find((m) => m.asset_id === selected) ?? null;

  return (
    <div>
      {/* persistent, non-dismissible honesty banner */}
      <div
        role="note"
        className="mb-5 flex flex-wrap items-center gap-3 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-amber-900"
      >
        <ShieldAlert size={20} className="shrink-0 text-amber-700" />
        <span className="min-w-0 flex-1 text-base font-semibold">{BANNER}</span>
        <SourceBadge variant="synthetic" label="SIMULATED" />
      </div>

      <PageHeader
        title="Watchdog — auxiliaries & autonomy"
        subtitle="The agent watches the plant auxiliaries. When it detects an overheating auxiliary motor or a power shortfall, it proposes an action and deliberates on it; then it either executes a reversible switchover inside the SIMULATED auxiliaries model or routes the decision to a human."
        right={
          <span
            className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-sm font-semibold ${mode === "live stream" ? "border-green-300 bg-green-50 text-green-800" : "border-ink-600 bg-ink-800 text-ink-200"}`}
            title="How state updates reach this page"
          >
            {mode === "live stream" ? <Radio size={14} /> : mode === "polling" ? <WifiOff size={14} /> : <Wifi size={14} />}
            {mode}
          </span>
        }
      />

      {error ? <ErrorBanner className="mb-4" error={error} title="Cannot load watchdog state" onRetry={reconnect} /> : null}
      {actError ? <ErrorBanner className="mb-4" error={actError} title="Action failed" /> : null}

      {!state ? (
        <div className="space-y-4"><PanelSkeleton lines={6} /><PanelSkeleton lines={4} /></div>
      ) : (
        <div className="space-y-5">
          {mode === "polling" ? (
            <InfoBanner>Live stream unavailable; polling the state every {POLL_MS / 1000} s instead.</InfoBanner>
          ) : null}
          {state.unit.shortfall_mwh > 0.05 ? (
            <WarnBanner>
              <span className="font-semibold">Power shortfall:</span> dispatch exceeds available output by {fmtNum(state.unit.shortfall_mwh, 1)} MWh per hourly sample (simulated).
            </WarnBanner>
          ) : null}

          <div className="panel">
            <div className="panel-header">
              <div className="panel-title">Auxiliaries board</div>
              <span className="text-sm text-ink-400">Click a motor for detail</span>
            </div>
            <div className="p-3">
              <AuxBoard motors={state.auxiliaries.motors} selected={selected} onSelect={(id) => setSelected((cur) => (cur === id ? null : id))} />
            </div>
          </div>

          {sel ? <MotorDetail m={sel} /> : null}

          <div className="grid gap-5 lg:grid-cols-2">
            <UnitPanel s={state} />
            <Controls s={state} busy={busy} act={act} />
          </div>

          <HumanPanel tasks={state.human_tasks} busy={busy} act={act} />

          <div className="grid gap-5 xl:grid-cols-2">
            <EventFeed events={state.events} />
            <ProposalsList s={state} />
          </div>

          <ExecutionsTable list={[...state.executions].sort((a, b) => b.t_sim_s - a.t_sim_s)} />
          <PolicyTable s={state} />
        </div>
      )}
    </div>
  );
}
