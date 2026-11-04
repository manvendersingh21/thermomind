import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ReactNode } from "react";
import { fmtNum, sampleLabel } from "../../lib/format";
import type { Excursion, ProfileBin } from "./types";

export const COLORS = { co: "#2563eb", nox: "#7c3aed", threshold: "#dc2626", shade: "#dc2626" };

interface SeriesProps {
  title: string;
  unit: string;
  year: number;
  rows: { row_index: number; value: number | null }[];
  color: string;
  threshold: number;
  excursions: Excursion[];
  badges?: ReactNode;
  height?: number;
}

export function ThresholdSeriesChart({ title, unit, year, rows, color, threshold, excursions, badges, height = 240 }: SeriesProps) {
  return (
    <div className="panel">
      <div className="panel-header">
        <div>
          <div className="panel-title">{title}</div>
          <div className="mt-1 flex flex-wrap items-center gap-x-4 text-sm text-ink-300">
            <span className="inline-flex items-center gap-1.5">
              <svg width="22" height="8" aria-hidden="true">
                <line x1="0" y1="4" x2="22" y2="4" stroke={color} strokeWidth="2.5" />
              </svg>
              measured
            </span>
            <span className="inline-flex items-center gap-1.5">
              <svg width="22" height="8" aria-hidden="true">
                <line x1="0" y1="4" x2="22" y2="4" stroke={COLORS.threshold} strokeWidth="2" strokeDasharray="5 3" />
              </svg>
              screening threshold {fmtNum(threshold, 2)} {unit}
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="inline-block h-3 w-4 rounded-sm" style={{ background: COLORS.shade, opacity: 0.2 }} />
              excursion (≥3 samples)
            </span>
          </div>
        </div>
        {badges}
      </div>
      <div className="px-2 pb-2 pt-4" style={{ height: height + 24 }}>
        {rows.length === 0 ? (
          <div className="flex h-full items-center justify-center text-base text-ink-400">No points in this window.</div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={rows} margin={{ top: 8, right: 24, bottom: 8, left: 8 }}>
              <CartesianGrid stroke="#e2e6ec" strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey="row_index"
                type="number"
                domain={["dataMin", "dataMax"]}
                tickCount={8}
                stroke="#cbd5e1"
                tickLine={false}
                height={40}
                label={{ value: "sample index (ordered hourly samples, no timestamps)", position: "insideBottom", offset: -4, fill: "#64748b", fontSize: 12 }}
              />
              <YAxis
                domain={[0, "auto"]}
                stroke="#cbd5e1"
                tickLine={false}
                width={64}
                tickFormatter={(v: number) => fmtNum(v, 1)}
                label={{ value: unit, angle: -90, position: "insideLeft", offset: 12, fill: "#64748b", fontSize: 12 }}
              />
              <Tooltip
                isAnimationActive={false}
                cursor={{ stroke: "#94a3b8", strokeWidth: 1 }}
                content={(p) => {
                  if (!p.active || !p.payload || p.payload.length === 0) return null;
                  const v = p.payload[0].value as number | null;
                  return (
                    <div className="rounded-lg border border-ink-600 bg-white px-3 py-2 text-sm shadow-lg">
                      <div className="font-mono text-ink-300">{sampleLabel(year, Number(p.label))}</div>
                      <div className="font-mono text-ink-50">
                        {fmtNum(v, 2)} <span className="text-ink-400">{unit}</span>
                      </div>
                    </div>
                  );
                }}
              />
              {excursions.map((e) => (
                <ReferenceArea
                  key={e.excursion_id}
                  x1={e.start_index}
                  x2={e.end_index}
                  fill={COLORS.shade}
                  fillOpacity={0.18}
                  stroke="none"
                  ifOverflow="hidden"
                />
              ))}
              <ReferenceLine y={threshold} stroke={COLORS.threshold} strokeDasharray="6 4" strokeWidth={1.5} />
              <Line type="linear" dataKey="value" stroke={color} strokeWidth={1.5} dot={false} isAnimationActive={false} connectNulls={false} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}

interface ProfileProps {
  title: string;
  bins: ProfileBin[];
  x: "tey" | "tit";
  pollutant: "co" | "nox";
  unit: string;
  color: string;
  footer?: ReactNode;
  height?: number;
  badges?: ReactNode;
}

export function ProfileChart({ title, bins, x, pollutant, unit, color, footer, height = 260, badges }: ProfileProps) {
  const data = bins.map((b) => ({
    xv: x === "tey" ? b.tey_median : b.tit_median,
    median: pollutant === "co" ? b.co_median : b.nox_median,
    p95: pollutant === "co" ? b.co_p95 : b.nox_p95,
    band:
      (pollutant === "co" ? b.co_p25 : b.nox_p25) !== null && (pollutant === "co" ? b.co_p75 : b.nox_p75) !== null
        ? [(pollutant === "co" ? b.co_p25 : b.nox_p25) as number, (pollutant === "co" ? b.co_p75 : b.nox_p75) as number]
        : null,
    n: b.n,
    bin: b.bin,
  }));
  const xLabel = x === "tey" ? "TEY decile median (MWh, as published)" : "TIT decile median (°C)";
  return (
    <div className="panel">
      <div className="panel-header">
        <div>
          <div className="panel-title">{title}</div>
          <div className="mt-1 flex flex-wrap items-center gap-x-4 text-sm text-ink-300">
            <span className="inline-flex items-center gap-1.5">
              <svg width="22" height="8" aria-hidden="true">
                <line x1="0" y1="4" x2="22" y2="4" stroke={color} strokeWidth="2.5" />
              </svg>
              bin median
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="inline-block h-3 w-4 rounded-sm" style={{ background: color, opacity: 0.18 }} />
              P25–P75
            </span>
            <span className="inline-flex items-center gap-1.5">
              <svg width="22" height="8" aria-hidden="true">
                <line x1="0" y1="4" x2="22" y2="4" stroke={color} strokeWidth="2" strokeDasharray="2 3" />
              </svg>
              P95
            </span>
          </div>
        </div>
        {badges}
      </div>
      <div className="px-2 pb-2 pt-4" style={{ height: height + 24 }}>
        {data.length === 0 ? (
          <div className="flex h-full items-center justify-center text-base text-ink-400">No bins.</div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={data} margin={{ top: 8, right: 24, bottom: 8, left: 8 }}>
              <CartesianGrid stroke="#e2e6ec" strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey="xv"
                type="number"
                domain={["dataMin", "dataMax"]}
                stroke="#cbd5e1"
                tickLine={false}
                height={40}
                tickFormatter={(v: number) => fmtNum(v, 0)}
                label={{ value: xLabel, position: "insideBottom", offset: -4, fill: "#64748b", fontSize: 12 }}
              />
              <YAxis
                domain={[0, "auto"]}
                stroke="#cbd5e1"
                tickLine={false}
                width={64}
                tickFormatter={(v: number) => fmtNum(v, 1)}
                label={{ value: unit, angle: -90, position: "insideLeft", offset: 12, fill: "#64748b", fontSize: 12 }}
              />
              <Tooltip
                isAnimationActive={false}
                content={(p) => {
                  if (!p.active || !p.payload || p.payload.length === 0) return null;
                  const row = p.payload[0].payload as (typeof data)[number];
                  return (
                    <div className="rounded-lg border border-ink-600 bg-white px-3 py-2 text-sm shadow-lg">
                      <div className="font-mono text-ink-300">
                        decile {row.bin} · n={row.n}
                      </div>
                      <div className="font-mono text-ink-50">
                        median {fmtNum(row.median, 2)} · P95 {fmtNum(row.p95, 2)} {unit}
                      </div>
                      <div className="font-mono text-ink-400">
                        P25–P75 {row.band ? `${fmtNum(row.band[0], 2)}–${fmtNum(row.band[1], 2)}` : "—"}
                      </div>
                    </div>
                  );
                }}
              />
              <Area type="monotone" dataKey="band" stroke="none" fill={color} fillOpacity={0.18} isAnimationActive={false} />
              <Line type="monotone" dataKey="p95" stroke={color} strokeWidth={1.5} strokeDasharray="2 3" dot={false} isAnimationActive={false} />
              <Line type="monotone" dataKey="median" stroke={color} strokeWidth={2.5} dot={{ r: 3 }} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>
      {footer ? <div className="border-t border-ink-700 px-5 py-2.5 text-sm text-ink-400">{footer}</div> : null}
    </div>
  );
}
