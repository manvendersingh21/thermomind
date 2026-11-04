import { Gauge, RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";
import { ErrorBanner, PanelSkeleton, Spinner, WarnBanner } from "../../components/Feedback";
import { KpiCard } from "../../components/KpiCard";
import { PageHeader } from "../../components/Layout";
import { SourceBadge } from "../../components/SourceBadge";
import { useAsync } from "../../hooks/useAsync";
import { fmtDateTime, fmtInt, fmtNum, rangeLabel } from "../../lib/format";
import { getScorecard } from "./api";
import type { SensorHealth, SensorStatus } from "./types";

const YEARS = [2011, 2012, 2013, 2014, 2015];

const PILL: Record<SensorStatus, string> = {
  ok: "border-green-300 bg-green-50 text-green-800",
  watch: "border-amber-400 bg-yellow-100 text-amber-800",
  check: "border-red-300 bg-red-50 text-red-800",
};
const BAR: Record<SensorStatus, string> = { ok: "bg-green-500", watch: "bg-yellow-400", check: "bg-red-500" };

function InstrumentStatusPill({ status }: { status: SensorStatus }) {
  return (
    <span className={`inline-flex items-center rounded-md border px-2 py-0.5 text-sm font-semibold uppercase tracking-wide ${PILL[status]}`}>
      {status}
    </span>
  );
}

function ScoreBar({ score, status }: { score: number; status: SensorStatus }) {
  return (
    <div className="flex items-center gap-2" title={`Score ${score} / 100`}>
      <div className="h-2.5 w-24 overflow-hidden rounded-full bg-ink-700" role="progressbar" aria-valuenow={score} aria-valuemin={0} aria-valuemax={100}>
        <div className={`h-full rounded-full ${BAR[status]}`} style={{ width: `${Math.max(0, Math.min(100, score))}%` }} />
      </div>
      <span className="w-12 font-mono text-sm font-semibold tabular-nums text-ink-50">{fmtNum(score, 1)}</span>
    </div>
  );
}

function Count({ n, title }: { n: number; title?: string }) {
  return (
    <span title={title} className={`font-mono tabular-nums ${n > 0 ? "font-semibold text-ink-50" : "text-ink-400"}`}>
      {fmtInt(n)}
    </span>
  );
}

function Row({ s }: { s: SensorHealth }) {
  return (
    <tr className="align-top">
      <td>
        <div className="font-mono font-semibold text-blue-700">{s.key}</div>
        <div className="text-sm text-ink-300">{s.name}</div>
      </td>
      <td className="text-sm text-ink-300">{s.unit}</td>
      <td title={s.computation}>
        <ScoreBar score={s.score} status={s.status} />
      </td>
      <td>
        <InstrumentStatusPill status={s.status} />
      </td>
      <td className="text-right"><Count n={s.missing} /></td>
      <td className="text-right">
        <Count n={s.out_of_range} title={s.range_lo !== null ? `Training range ${fmtNum(s.range_lo, 3)} to ${fmtNum(s.range_hi, 3)} (${s.range_source})` : undefined} />
      </td>
      <td className="text-right">
        <Count n={s.flatline_runs} title={`${s.flatline_rows} rows inside runs of 6+ identical readings`} />
      </td>
      <td className="text-right">
        <Count n={s.spikes} title={`${s.spike_points} spike samples (training-years rate ${s.spike_baseline_pct}%)`} />
      </td>
      <td className="text-sm">
        {s.coupling_drift_pairs.length === 0 ? (
          <span className="text-ink-400">none</span>
        ) : (
          <div className="flex flex-wrap gap-1">
            {s.coupling.filter((p) => p.drift).map((p) => (
              <span key={p.pair} className="rounded border border-amber-400 bg-yellow-100 px-1.5 py-0.5 font-mono text-xs text-amber-800" title={`r = ${fmtNum(p.r_year)} vs training ${fmtNum(p.r_train)} (expected ${p.expected})`}>
                {p.pair} Δ{fmtNum(p.delta)}
              </span>
            ))}
          </div>
        )}
      </td>
      <td className="max-w-md text-sm text-ink-200">{s.what_to_check}</td>
    </tr>
  );
}

export default function InstrumentsPage() {
  const [year, setYear] = useState(2014);
  const [startTxt, setStartTxt] = useState("");
  const [endTxt, setEndTxt] = useState("");
  const [applied, setApplied] = useState<{ start?: number; end?: number }>({});
  const [formError, setFormError] = useState<string | null>(null);

  const card = useAsync((s) => getScorecard({ year, start: applied.start, end: applied.end }, s), [year, applied.start, applied.end]);

  function parse(txt: string): number | undefined | null {
    if (txt.trim() === "") return undefined;
    const n = Number(txt);
    return Number.isInteger(n) && n >= 0 ? n : null;
  }

  function apply() {
    const s = parse(startTxt);
    const e = parse(endTxt);
    if (s === null || e === null) return setFormError("Window bounds must be whole numbers >= 0 (row indices within the year).");
    if (s !== undefined && e !== undefined && e - s < 24) return setFormError("Window must contain at least 24 rows (end must be at least 24 above start).");
    setFormError(null);
    setApplied({ start: s, end: e });
  }

  function clearWindow() {
    setStartTxt("");
    setEndTxt("");
    setFormError(null);
    setApplied({});
  }

  const d = card.data;
  const sorted = useMemo(() => d?.sensors ?? [], [d]);

  return (
    <div>
      <PageHeader
        title="Instrument Health"
        subtitle="Per-sensor screening scorecard computed deterministically from the real UCI rows: missing data, out-of-training-range readings, flatlines, spikes, and drift in physically coupled sensor pairs."
        right={<SourceBadge variant="real" label="REAL UCI TURBINE DATA" />}
      />

      <WarnBanner className="mb-5" icon={<Gauge size={20} />}>
        <strong>Statistical screening on historical data — not a calibration certificate.</strong> Scores flag where an I&amp;C engineer may want to look; they do not
        prove a sensor is faulty or healthy, and ThermoMind never writes to any control system.
      </WarnBanner>

      <div className="panel mb-5">
        <div className="flex flex-wrap items-end gap-4 px-5 py-4">
          <label className="block">
            <span className="label">Source year</span>
            <select className="mt-1 block h-10 rounded-lg border border-ink-600 bg-white px-3 text-base" value={year} onChange={(e) => { setYear(Number(e.target.value)); clearWindow(); }}>
              {YEARS.map((y) => (
                <option key={y} value={y}>{y}{y <= 2013 ? " (training)" : ""}</option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="label">Window start (optional)</span>
            <input className="mt-1 block h-10 w-36 rounded-lg border border-ink-600 bg-white px-3 font-mono text-base" inputMode="numeric" placeholder="0" value={startTxt} onChange={(e) => setStartTxt(e.target.value)} />
          </label>
          <label className="block">
            <span className="label">Window end, exclusive (optional)</span>
            <input className="mt-1 block h-10 w-36 rounded-lg border border-ink-600 bg-white px-3 font-mono text-base" inputMode="numeric" placeholder="end of year" value={endTxt} onChange={(e) => setEndTxt(e.target.value)} />
          </label>
          <button type="button" className="btn-primary h-10" onClick={apply}>Apply window</button>
          <button type="button" className="btn-secondary h-10" onClick={clearWindow}>Whole year</button>
          <button type="button" className="btn-secondary h-10" onClick={card.reload} title="Recompute">
            <RefreshCw size={16} /> Recompute
          </button>
          {card.loading ? <Spinner className="text-blue-700" /> : null}
        </div>
        {formError ? <div className="border-t border-ink-700 px-5 py-2 text-sm text-red-800">{formError}</div> : null}
      </div>

      {card.error ? <ErrorBanner className="mb-5" title="Could not compute scorecard" error={card.error} onRetry={card.reload} /> : null}
      {card.loading && !d ? <PanelSkeleton lines={8} /> : null}

      {d ? (
        <>
          <div className="mb-5 grid grid-cols-4 gap-4">
            <KpiCard label="Sensors to trust" value={d.summary.trust.length} unit={`/ ${d.sensors.length}`} caption={d.summary.trust.join(", ") || "none"} tone="model" />
            <KpiCard label="Use with cross-check" value={d.summary.use_with_cross_check.length} caption={d.summary.use_with_cross_check.join(", ") || "none"} tone="amber" />
            <KpiCard label="Verify first" value={d.summary.verify_first.length} caption={d.summary.verify_first.join(", ") || "none"} />
            <KpiCard label="Mean score" value={fmtNum(d.summary.mean_score, 1)} unit="/ 100" caption={`${rangeLabel(d.window)} · ${fmtInt(d.window.end - d.window.start)} rows`} />
          </div>

          <div className="panel mb-5 px-5 py-4">
            <div className="label">Which sensors to trust for this investigation</div>
            <p className="mt-1.5 text-base text-ink-100">{d.summary.headline}</p>
            {d.summary.coupling_drift_pairs.length > 0 ? (
              <p className="mt-1.5 text-sm text-ink-300">Coupling drift in: <span className="font-mono">{d.summary.coupling_drift_pairs.join(", ")}</span></p>
            ) : null}
          </div>

          <div className="panel mb-5 overflow-x-auto">
            <div className="panel-header">
              <div className="panel-title">Sensor scorecard · {d.year}</div>
              <div className="text-sm text-ink-300">computed {fmtDateTime(d.computed_at_utc)}</div>
            </div>
            <table className="table-base">
              <thead>
                <tr>
                  <th>Sensor</th>
                  <th>Unit</th>
                  <th>Score</th>
                  <th>Status</th>
                  <th className="text-right">Missing</th>
                  <th className="text-right">OOD</th>
                  <th className="text-right">Flatline runs</th>
                  <th className="text-right">Spikes</th>
                  <th>Coupling drift</th>
                  <th>What an I&amp;C engineer would check</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((s) => (
                  <Row key={s.key} s={s} />
                ))}
              </tbody>
            </table>
          </div>

          <div className="panel px-5 py-4">
            <div className="panel-title mb-2">Method notes</div>
            <ul className="list-disc space-y-1.5 pl-5 text-sm text-ink-200">
              {d.method_notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
            <p className="mt-3 text-sm text-ink-300">Hover a score bar for the exact arithmetic; hover counts for details. Rows have no timestamps: windows are sample indices within the source year.</p>
          </div>
        </>
      ) : null}
    </div>
  );
}
