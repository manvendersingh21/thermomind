import { Pause, Play, Radio, RotateCcw, SkipForward } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { getSeries, listDatasets } from "../api/client";
import { MEASUREMENTS, MEASUREMENT_KEYS } from "../api/types";
import type { SeriesResponse } from "../api/types";
import { ChartSkeleton, EmptyDataset, ErrorBanner, WarnBanner } from "../components/Feedback";
import { PageHeader } from "../components/Layout";
import { SERIES_COLORS, SeriesChart } from "../components/SeriesChart";
import type { ChartRow } from "../components/SeriesChart";
import { SourceBadge } from "../components/SourceBadge";
import { useAsync } from "../hooks/useAsync";
import { fmtNum, sampleLabel } from "../lib/format";

const SPEEDS = [1, 2, 5, 10, 25];
const DEFAULT_MEASURES = ["TEY", "AFDP", "CDP"];
const MAX_SELECTED = 4;

export function ReplayPage() {
  const datasets = useAsync((s) => listDatasets(s), []);
  const dataset = useMemo(() => {
    const list = datasets.data ?? [];
    return list.find((d) => d.dataset_id === "ds_uci_551") ?? list[0] ?? null;
  }, [datasets.data]);
  const datasetId = dataset?.dataset_id ?? null;

  const [year, setYear] = useState(2014);
  const [start, setStart] = useState(960);
  const [length, setLength] = useState(480);
  const [measures, setMeasures] = useState<string[]>(DEFAULT_MEASURES);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(5);
  const [cursor, setCursor] = useState(0); // number of samples revealed
  const safeLength = Math.max(10, Math.min(2000, length));

  const series = useAsync(
    async (signal) => {
      if (!datasetId) return null;
      const res = await Promise.all(
        measures.map((m) => getSeries(datasetId, { measure: m, year, start, limit: safeLength, include_expected: m === "TEY" }, signal)),
      );
      const out: Record<string, SeriesResponse> = {};
      res.forEach((r, i) => (out[measures[i]] = r));
      return out;
    },
    [datasetId, year, start, safeLength, measures.join(",")],
  );

  // reset the cursor when a new window is loaded
  useEffect(() => {
    setCursor(0);
    setPlaying(false);
  }, [series.data]);

  const totalPoints = useMemo(() => {
    if (!series.data) return 0;
    return Math.max(0, ...Object.values(series.data).map((s) => s.points.length));
  }, [series.data]);

  const rafRef = useRef<number | null>(null);
  useEffect(() => {
    if (!playing) return;
    let last = performance.now();
    let acc = 0;
    const step = (now: number) => {
      const dt = now - last;
      last = now;
      acc += (dt / 1000) * speed * 4; // 4 samples/s at 1x
      const inc = Math.floor(acc);
      if (inc > 0) {
        acc -= inc;
        setCursor((c) => {
          const next = Math.min(totalPoints, c + inc);
          if (next >= totalPoints) setPlaying(false);
          return next;
        });
      }
      rafRef.current = requestAnimationFrame(step);
    };
    rafRef.current = requestAnimationFrame(step);
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  }, [playing, speed, totalPoints]);

  function toggleMeasure(m: string) {
    setMeasures((prev) => {
      if (prev.includes(m)) return prev.length > 1 ? prev.filter((x) => x !== m) : prev;
      if (prev.length >= MAX_SELECTED) return prev;
      return [...prev, m];
    });
  }

  const revealed = useMemo(() => {
    const out: Record<string, ChartRow[]> = {};
    if (!series.data) return out;
    for (const [m, s] of Object.entries(series.data)) {
      out[m] = s.points.slice(0, cursor).map((p) => {
        const row: ChartRow = { row_index: p.row_index, value: p.value };
        if (m === "TEY") row.expected = p.expected;
        return row;
      });
    }
    return out;
  }, [series.data, cursor]);

  const currentIndex = useMemo(() => {
    if (!series.data || cursor === 0) return null;
    const first = Object.values(series.data)[0];
    return first?.points[Math.min(cursor, first.points.length) - 1]?.row_index ?? null;
  }, [series.data, cursor]);

  const datasetEmpty = !datasets.loading && !datasets.error && (datasets.data?.length ?? 0) === 0;
  const lastValues = useMemo(() => {
    const out: Record<string, number | null> = {};
    for (const [m, rows] of Object.entries(revealed)) out[m] = rows.length ? rows[rows.length - 1].value : null;
    return out;
  }, [revealed]);

  return (
    <div>
      <PageHeader
        title="Replay"
        subtitle={
          <span>
            <strong className="text-amber-800">Replay of historical ordered samples — not live plant telemetry.</strong> The player
            advances a cursor through real UCI rows fetched from the series endpoint; nothing is simulated or generated.
          </span>
        }
        right={<SourceBadge variant="real" label="REAL UCI TURBINE DATA · REPLAY" />}
      />

      {datasets.error ? <ErrorBanner className="mb-5" title="Could not load datasets" error={datasets.error} onRetry={datasets.reload} /> : null}
      {datasetEmpty ? <EmptyDataset className="mb-5" /> : null}

      <div className="panel mb-5">
        <div className="grid grid-cols-12 gap-4 px-5 py-4">
          <label className="col-span-2 flex flex-col gap-1.5">
            <span className="label">Year</span>
            <select className="input" value={year} onChange={(e) => setYear(Number(e.target.value))}>
              {(dataset?.years ?? [2011, 2012, 2013, 2014, 2015]).map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </select>
          </label>
          <label className="col-span-2 flex flex-col gap-1.5">
            <span className="label">Start index</span>
            <input className="input font-mono" type="number" min={0} value={start} onChange={(e) => setStart(Math.max(0, Math.floor(Number(e.target.value) || 0)))} />
          </label>
          <label className="col-span-2 flex flex-col gap-1.5">
            <span className="label">Length</span>
            <input className="input font-mono" type="number" min={10} max={2000} value={length} onChange={(e) => setLength(Math.floor(Number(e.target.value) || 480))} />
          </label>
          <div className="col-span-6 flex flex-col gap-1.5">
            <span className="label">Measurements (up to {MAX_SELECTED})</span>
            <div className="flex flex-wrap gap-1.5">
              {MEASUREMENT_KEYS.map((m) => {
                const on = measures.includes(m);
                return (
                  <button
                    key={m}
                    type="button"
                    onClick={() => toggleMeasure(m)}
                    title={MEASUREMENTS[m].name}
                    className={`rounded-md border px-2.5 py-1 font-mono text-sm font-semibold transition ${
                      on ? "border-blue-500 bg-blue-50 text-blue-800" : "border-ink-600 bg-ink-900 text-ink-300 hover:border-ink-500"
                    }`}
                  >
                    {m}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3 border-t border-ink-700 px-5 py-4">
          <button type="button" className="btn-primary" onClick={() => setPlaying((p) => !p)} disabled={!series.data || totalPoints === 0 || (cursor >= totalPoints && !playing)}>
            {playing ? <Pause size={18} /> : <Play size={18} />}
            {playing ? "Pause" : cursor > 0 && cursor < totalPoints ? "Resume" : "Play"}
          </button>
          <button type="button" className="btn-secondary" onClick={() => setCursor((c) => Math.min(totalPoints, c + 10))} disabled={!series.data}>
            <SkipForward size={16} /> +10
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => {
              setPlaying(false);
              setCursor(0);
            }}
            disabled={!series.data}
          >
            <RotateCcw size={16} /> Reset
          </button>
          <div className="ml-2 flex items-center gap-1.5">
            <span className="text-sm font-medium text-ink-300">Speed</span>
            {SPEEDS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setSpeed(s)}
                className={`rounded-md border px-2.5 py-1 font-mono text-sm ${speed === s ? "border-blue-500 bg-blue-50 text-blue-800" : "border-ink-600 text-ink-300"}`}
              >
                {s}×
              </button>
            ))}
          </div>
          <div className="ml-auto flex items-center gap-3">
            <input
              type="range"
              min={0}
              max={Math.max(0, totalPoints)}
              value={cursor}
              onChange={(e) => setCursor(Number(e.target.value))}
              className="w-56 accent-blue-600"
              disabled={!series.data}
            />
            <span className="font-mono text-sm text-ink-200">
              {currentIndex !== null ? sampleLabel(year, currentIndex) : `${year} • —`} · {cursor}/{totalPoints}
            </span>
            <span className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-semibold ${playing ? "border-blue-400 text-blue-700" : "border-ink-600 text-ink-400"}`}>
              <Radio size={12} /> REPLAY {playing ? "RUNNING" : "PAUSED"}
            </span>
          </div>
        </div>
      </div>

      {series.error ? <ErrorBanner className="mb-5" title="Could not load series" error={series.error} onRetry={series.reload} /> : null}
      {series.data && totalPoints === 0 ? <WarnBanner className="mb-5">The requested window is outside the available rows for {year}.</WarnBanner> : null}

      <div className="grid grid-cols-2 gap-4">
        {series.loading && !series.data
          ? measures.map((m) => <ChartSkeleton key={m} height={220} />)
          : measures.map((m) => {
              const s = series.data?.[m];
              const rows = revealed[m] ?? [];
              const hasExpected = m === "TEY" && rows.some((r) => r.expected !== null && r.expected !== undefined);
              return (
                <SeriesChart
                  key={m}
                  height={220}
                  title={
                    <span>
                      {m} — {MEASUREMENTS[m].name}{" "}
                      <span className="ml-2 font-mono text-base text-blue-700">
                        {lastValues[m] !== null && lastValues[m] !== undefined ? `${fmtNum(lastValues[m], 2)} ${s?.unit ?? MEASUREMENTS[m].unit.split(" ")[0]}` : ""}
                      </span>
                    </span>
                  }
                  unit={s?.unit ?? MEASUREMENTS[m].unit}
                  year={year}
                  data={rows}
                  cursor={currentIndex}
                  series={
                    hasExpected
                      ? [
                          { key: "value", name: `Measured ${m}`, color: SERIES_COLORS.measured },
                          { key: "expected", name: "Model expected", color: SERIES_COLORS.expected, dashed: true, tag: "MODEL-DERIVED" },
                        ]
                      : [{ key: "value", name: `Measured ${m}`, color: SERIES_COLORS.measured }]
                  }
                  badges={<SourceBadge variant="real" size="sm" />}
                  emptyMessage={totalPoints === 0 ? "No rows in this window." : "Press Play to stream samples into the chart."}
                  footer={s ? `${s.points.length} points fetched · downsample ×${s.downsample_factor} · ${s.time_axis_type.replace(/_/g, " ")}` : null}
                />
              );
            })}
      </div>
    </div>
  );
}
