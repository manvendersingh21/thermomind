/** Time scrubber + play/pause over the selected window, window editor and historian replay toggle. */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Pause, Play, Radio, SkipBack } from "lucide-react";
import { MEASUREMENTS } from "../../api/types";
import { fmtNum, sampleLabel } from "../../lib/format";
import type { TwinController } from "./controller";
import { MAX_WINDOW } from "./data";

const READOUT = ["TEY", "TIT", "TAT", "AFDP", "CDP", "GTEP", "AT", "CO", "NOX"];
const YEARS = [2011, 2012, 2013, 2014, 2015];

export function LiveReadout({ ctl }: { ctl: TwinController }) {
  const synth = ctl.data.series?.syntheticMeasures ?? [];
  return (
    <div className="flex flex-wrap gap-1.5" data-testid="twin-readout">
      {READOUT.map((k) => {
        const s = synth.includes(k);
        return (
          <span
            key={k}
            title={`${MEASUREMENTS[k].name}${s ? " — SYNTHETIC overlay" : " — real observation"}`}
            className={`inline-flex items-baseline gap-1 rounded-md border px-1.5 py-0.5 font-mono text-xs ${
              s ? "border-yellow-400 bg-yellow-100 text-yellow-900" : "border-ink-600 bg-white text-ink-100"
            }`}
          >
            <b className={s ? "" : "text-blue-700"}>{k}</b>
            {fmtNum(ctl.current.v[k], 2)}
            <span className="text-[10px] text-ink-400">{MEASUREMENTS[k].unit.split(" ")[0]}</span>
          </span>
        );
      })}
    </div>
  );
}

function WindowEditor({ ctl }: { ctl: TwinController }) {
  const [year, setYear] = useState(ctl.win.year);
  const [start, setStart] = useState(ctl.win.start);
  const [len, setLen] = useState(ctl.win.end - ctl.win.start);
  useEffect(() => {
    setYear(ctl.win.year);
    setStart(ctl.win.start);
    setLen(ctl.win.end - ctl.win.start);
  }, [ctl.win.year, ctl.win.start, ctl.win.end]);
  return (
    <form
      className="flex flex-wrap items-end gap-2 text-xs"
      onSubmit={(e) => {
        e.preventDefault();
        ctl.setWindow({ year, start, end: start + len });
      }}
    >
      <label className="flex flex-col gap-0.5">
        <span className="label">Year</span>
        <select className="rounded-md border border-ink-600 bg-white px-1.5 py-1" value={year} onChange={(e) => setYear(Number(e.target.value))}>
          {YEARS.map((y) => (
            <option key={y} value={y}>
              {y}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-0.5">
        <span className="label">Start row</span>
        <input type="number" min={0} className="w-20 rounded-md border border-ink-600 bg-white px-1.5 py-1" value={start} onChange={(e) => setStart(Number(e.target.value))} />
      </label>
      <label className="flex flex-col gap-0.5">
        <span className="label">Length</span>
        <input type="number" min={2} max={MAX_WINDOW} className="w-20 rounded-md border border-ink-600 bg-white px-1.5 py-1" value={len} onChange={(e) => setLen(Number(e.target.value))} />
      </label>
      <button type="submit" className="btn btn-secondary px-2 py-1 text-xs">
        Apply
      </button>
      {ctl.windowOverridden ? (
        <button type="button" className="btn btn-secondary px-2 py-1 text-xs" onClick={ctl.resetWindow}>
          {ctl.inv ? "Case window" : "Default"}
        </button>
      ) : null}
    </form>
  );
}

export function Scrubber({ ctl, compact = false }: { ctl: TwinController; compact?: boolean }) {
  const { n, index, win } = ctl;
  const rows = ctl.data.series?.rows ?? [];
  const excursions = ctl.data.emissions?.excursions ?? [];
  const span = Math.max(1, win.end - win.start);
  const historian = ctl.mode === "historian";
  const cursor = ctl.historian.data?.cursor;

  return (
    <div className="space-y-2" data-testid="twin-scrubber">
      <div className="flex flex-wrap items-center gap-2">
        {!historian ? (
          <>
            <button className="btn btn-primary px-2.5 py-1 text-xs" onClick={() => ctl.setPlaying(!ctl.playing)} disabled={n < 2} aria-label={ctl.playing ? "Pause" : "Play"}>
              {ctl.playing ? <Pause size={14} /> : <Play size={14} />} {ctl.playing ? "Pause" : "Play"}
            </button>
            <button className="btn btn-secondary px-2 py-1 text-xs" onClick={() => ctl.setIndex(0)} aria-label="Back to start">
              <SkipBack size={14} />
            </button>
          </>
        ) : null}
        <span className="font-mono text-xs text-ink-200" data-testid="twin-sample">
          {ctl.current.row !== null && (historian ? ctl.current.year : win.year) !== null
            ? sampleLabel((historian ? ctl.current.year : win.year) as number, ctl.current.row)
            : "no sample"}
          {!historian && n > 0 ? <span className="text-ink-400"> · {index + 1}/{n}</span> : null}
          {!historian && (ctl.data.series?.downsample ?? 1) > 1 ? <span className="text-ink-400"> · every {ctl.data.series?.downsample}th row</span> : null}
        </span>
        {!historian && !compact ? (
          <select className="rounded-md border border-ink-600 bg-white px-1.5 py-0.5 text-xs" value={ctl.rate} onChange={(e) => ctl.setRate(Number(e.target.value))} aria-label="Playback rate">
            {[1, 2, 4, 8, 16].map((r) => (
              <option key={r} value={r}>
                {r} samples/s
              </option>
            ))}
          </select>
        ) : null}
        {!compact ? (
          <button
            className={`btn ml-auto px-2 py-1 text-xs ${historian ? "btn-amber" : "btn-secondary"}`}
            onClick={() => ctl.setMode(historian ? "window" : "historian")}
            title="Poll the SIMULATED historian replay connector instead of the selected window"
          >
            <Radio size={13} /> {historian ? "Historian replay ON (simulated)" : "Historian replay"}
          </button>
        ) : null}
      </div>

      {!historian ? (
        <div className="relative pt-1">
          <div className="pointer-events-none absolute inset-x-0 top-1 h-2">
            {excursions.map((ex) => {
              const l = ((ex.start_index - win.start) / span) * 100;
              const w = (Math.max(1, ex.end_index - ex.start_index) / span) * 100;
              return <span key={ex.excursion_id} className="absolute h-2 rounded-sm bg-amber-400/70" style={{ left: `${l}%`, width: `${w}%` }} title={`${ex.pollutant} excursion`} />;
            })}
          </div>
          <input
            type="range"
            min={0}
            max={Math.max(0, n - 1)}
            value={Math.min(index, Math.max(0, n - 1))}
            onChange={(e) => {
              ctl.setPlaying(false);
              ctl.setIndex(Number(e.target.value));
            }}
            className="relative w-full accent-blue-600"
            aria-label="Sample within window"
            disabled={n < 2}
          />
          <div className="flex justify-between font-mono text-[10px] text-ink-400">
            <span>#{rows[0] ?? win.start}</span>
            {excursions.length > 0 ? <span className="text-amber-700">■ emissions excursion (screening)</span> : null}
            <span>#{rows[rows.length - 1] ?? win.end - 1}</span>
          </div>
        </div>
      ) : (
        <div className="rounded-md border border-ink-600 bg-white px-3 py-2 text-xs text-ink-200">
          {ctl.historian.error ? (
            <span className="text-red-700">Historian: {ctl.historian.error}</span>
          ) : cursor && cursor.started && ctl.current.row !== null ? (
            <span>
              Polling the <b>simulated</b> historian replay every 2 s (UCI rows in order, no timestamps) — tick {cursor.replay_tick}, {cursor.running ? "running" : cursor.finished ? "finished" : "stopped"}.
            </span>
          ) : (
            <span>
              Historian replay is not running. Start it on <Link className="text-blue-700 underline" to="/connectors">Connectors</Link> (simulated connector), then come back.
            </span>
          )}
        </div>
      )}

      {!compact && !historian ? <WindowEditor ctl={ctl} /> : null}
    </div>
  );
}
