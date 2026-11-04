import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { TooltipProps } from "recharts";
import type { ReactNode } from "react";
import { fmtNum, sampleLabel } from "../../../lib/format";

export const PLANNER_COLORS = {
  real: "#2563eb", // blue — derived from real measurements only
  model: "#16a34a", // green — model-derived
  projection: "#475569", // slate — straight-line projection (dashed)
  threshold: "#b45309", // amber-700 — user limit / break-even threshold
  marker: "#64748b",
};

export type PlannerRow = { row_index: number } & Record<string, number | null>;

export interface PlannerSeries {
  key: string;
  name: string;
  color: string;
  dashed?: boolean;
  connectNulls?: boolean;
}

export interface PlannerRef {
  x?: number;
  y?: number;
  label: string;
  color: string;
}

interface Props {
  title: ReactNode;
  subtitle?: ReactNode;
  unit: string;
  year: number;
  data: PlannerRow[];
  series: PlannerSeries[];
  refs?: PlannerRef[];
  /** Rows after this index are projections, not data. */
  lastRealIndex?: number | null;
  height?: number;
}

function Tip({
  active,
  payload,
  label,
  unit,
  year,
  lastRealIndex,
}: TooltipProps<number, string> & { unit: string; year: number; lastRealIndex?: number | null }) {
  if (!active || !payload || payload.length === 0) return null;
  const idx = Number(label);
  const projected = lastRealIndex !== null && lastRealIndex !== undefined && idx > lastRealIndex;
  return (
    <div className="rounded-lg border border-ink-600 bg-white px-3 py-2 text-sm shadow-lg">
      <div className="mb-1 font-mono text-ink-300">
        {projected ? `${year} • projected sample #${idx} (no data)` : sampleLabel(year, idx)}
      </div>
      {payload
        .filter((p) => p.value !== null && p.value !== undefined)
        .map((p) => (
          <div key={String(p.dataKey)} className="flex items-center gap-2">
            <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: p.color }} />
            <span className="text-ink-300">{p.name}</span>
            <span className="ml-auto font-mono text-ink-50">
              {fmtNum(p.value as number, 3)} <span className="text-ink-400">{unit}</span>
            </span>
          </div>
        ))}
    </div>
  );
}

/** Single-axis line chart for planner results (one unit per chart; no dual axes). */
export function PlannerChart({ title, subtitle, unit, year, data, series, refs = [], lastRealIndex, height = 220 }: Props) {
  return (
    <div className="rounded-lg border border-ink-700 bg-white">
      <div className="border-b border-ink-700 px-4 py-2.5">
        <div className="text-sm font-semibold text-ink-50">{title}</div>
        {subtitle ? <div className="text-xs text-ink-400">{subtitle}</div> : null}
        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-300">
          {series.map((s) => (
            <span key={s.key} className="inline-flex items-center gap-1.5">
              <svg width="20" height="8" aria-hidden="true">
                <line x1="0" y1="4" x2="20" y2="4" stroke={s.color} strokeWidth="2" strokeDasharray={s.dashed ? "5 3" : undefined} />
              </svg>
              {s.name}
            </span>
          ))}
          {refs.map((r) => (
            <span key={r.label} className="inline-flex items-center gap-1.5">
              <svg width="20" height="8" aria-hidden="true">
                <line x1="0" y1="4" x2="20" y2="4" stroke={r.color} strokeWidth="1.5" strokeDasharray="2 2" />
              </svg>
              {r.label}
            </span>
          ))}
        </div>
      </div>
      <div className="px-1 pb-1 pt-2" style={{ height }}>
        {data.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-ink-400">No series to plot.</div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 4 }}>
              <CartesianGrid stroke="#e2e6ec" strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey="row_index"
                type="number"
                domain={["dataMin", "dataMax"]}
                tickCount={6}
                stroke="#cbd5e1"
                tickLine={false}
                fontSize={11}
                label={{ value: "sample index (hourly, no timestamps)", position: "insideBottom", offset: -2, fill: "#64748b", fontSize: 11 }}
                height={34}
              />
              <YAxis
                domain={["auto", "auto"]}
                stroke="#cbd5e1"
                tickLine={false}
                width={56}
                fontSize={11}
                tickFormatter={(v: number) => fmtNum(v, 1)}
                label={{ value: unit, angle: -90, position: "insideLeft", offset: 10, fill: "#64748b", fontSize: 11 }}
              />
              <Tooltip
                content={(p) => (
                  <Tip {...(p as TooltipProps<number, string>)} unit={unit} year={year} lastRealIndex={lastRealIndex} />
                )}
                cursor={{ stroke: "#94a3b8", strokeWidth: 1 }}
                isAnimationActive={false}
              />
              {refs.map((r) =>
                r.y !== undefined ? (
                  <ReferenceLine key={r.label} y={r.y} stroke={r.color} strokeDasharray="4 3" strokeWidth={1.5} ifOverflow="extendDomain" />
                ) : r.x !== undefined ? (
                  <ReferenceLine key={r.label} x={r.x} stroke={r.color} strokeDasharray="4 3" strokeWidth={1.5} ifOverflow="extendDomain" />
                ) : null,
              )}
              {series.map((s) => (
                <Line
                  key={s.key}
                  type="linear"
                  dataKey={s.key}
                  name={s.name}
                  stroke={s.color}
                  strokeWidth={2}
                  strokeDasharray={s.dashed ? "6 4" : undefined}
                  dot={false}
                  activeDot={{ r: 4, strokeWidth: 2, stroke: "#ffffff" }}
                  isAnimationActive={false}
                  connectNulls={s.connectNulls ?? false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
