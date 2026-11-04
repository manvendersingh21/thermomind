import { CartesianGrid, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { TooltipProps } from "recharts";
import type { ReactNode } from "react";
import { fmtNum, sampleLabel } from "../lib/format";

/** Validated with the dataviz palette checker against the light panel surface (#f6f8fa). */
export const SERIES_COLORS = {
  measured: "#2563eb", // blue — real measurement
  expected: "#16a34a", // green — model-derived expected (dashed)
  overlay: "#a16207", // yellow-700 — synthetic overlay (dashed expected line is the secondary encoding)
};

export interface ChartSeries {
  key: string;
  name: string;
  color: string;
  dashed?: boolean;
  /** Shown as a small tag in the legend, e.g. MODEL-DERIVED. */
  tag?: string;
}

export type ChartRow = { row_index: number } & Record<string, number | null>;

interface Props {
  title: ReactNode;
  unit: string;
  year: number;
  data: ChartRow[];
  series: ChartSeries[];
  height?: number;
  /** [start, end) window highlighted on the x axis. */
  highlight?: { start: number; end: number; label?: string } | null;
  /** Vertical cursor (used by Replay). */
  cursor?: number | null;
  footer?: ReactNode;
  badges?: ReactNode;
  emptyMessage?: string;
}

function TooltipBox({ active, payload, label, unit, year }: TooltipProps<number, string> & { unit: string; year: number }) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="rounded-lg border border-ink-600 bg-white px-3 py-2 text-sm shadow-lg">
      <div className="mb-1 font-mono text-ink-300">{sampleLabel(year, Number(label))}</div>
      {payload.map((p) => (
        <div key={String(p.dataKey)} className="flex items-center gap-2">
          <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: p.color }} />
          <span className="text-ink-300">{p.name}</span>
          <span className="ml-auto font-mono text-ink-50">
            {fmtNum(p.value as number, 2)} <span className="text-ink-400">{unit}</span>
          </span>
        </div>
      ))}
    </div>
  );
}

export function SeriesChart({
  title,
  unit,
  year,
  data,
  series,
  height = 260,
  highlight,
  cursor,
  footer,
  badges,
  emptyMessage = "No points in this window.",
}: Props) {
  const hasData = data.length > 0;
  return (
    <div className="panel">
      <div className="panel-header">
        <div className="min-w-0">
          <div className="panel-title">{title}</div>
          <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-ink-300">
            {series.map((s) => (
              <span key={s.key} className="inline-flex items-center gap-1.5">
                <svg width="22" height="8" aria-hidden="true">
                  <line
                    x1="0"
                    y1="4"
                    x2="22"
                    y2="4"
                    stroke={s.color}
                    strokeWidth="2.5"
                    strokeDasharray={s.dashed ? "5 3" : undefined}
                  />
                </svg>
                {s.name}
                {s.tag ? (
                  <span className="rounded border border-green-300 bg-green-50 px-1 py-px text-xs font-semibold text-green-800">
                    {s.tag}
                  </span>
                ) : null}
              </span>
            ))}
          </div>
        </div>
        {badges ? <div className="flex shrink-0 flex-wrap items-center gap-2">{badges}</div> : null}
      </div>
      <div className="px-2 pb-2 pt-4" style={{ height: height + 24 }}>
        {hasData ? (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 24, bottom: 8, left: 8 }}>
              <CartesianGrid stroke="#e2e6ec" strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey="row_index"
                type="number"
                domain={["dataMin", "dataMax"]}
                tickCount={8}
                stroke="#cbd5e1"
                tickLine={false}
                label={{ value: "sample index (ordered hourly samples, no timestamps)", position: "insideBottom", offset: -4, fill: "#64748b", fontSize: 12 }}
                height={40}
              />
              <YAxis
                domain={["auto", "auto"]}
                stroke="#cbd5e1"
                tickLine={false}
                width={64}
                tickFormatter={(v: number) => fmtNum(v, 1)}
                label={{ value: unit, angle: -90, position: "insideLeft", offset: 12, fill: "#64748b", fontSize: 12 }}
              />
              <Tooltip
                content={(p) => <TooltipBox {...(p as TooltipProps<number, string>)} unit={unit} year={year} />}
                cursor={{ stroke: "#94a3b8", strokeWidth: 1 }}
                isAnimationActive={false}
              />
              {highlight ? (
                <ReferenceArea
                  x1={highlight.start}
                  x2={Math.max(highlight.start, highlight.end - 1)}
                  fill="#facc15"
                  fillOpacity={0.18}
                  stroke="#ca8a04"
                  strokeOpacity={0.5}
                  label={
                    highlight.label
                      ? { value: highlight.label, position: "insideTopRight", fill: "#854d0e", fontSize: 12 }
                      : undefined
                  }
                />
              ) : null}
              {cursor !== null && cursor !== undefined ? (
                <ReferenceLine x={cursor} stroke="#0f172a" strokeOpacity={0.5} strokeWidth={1} />
              ) : null}
              {series.map((s) => (
                <Line
                  key={s.key}
                  type="monotone"
                  dataKey={s.key}
                  name={s.name}
                  stroke={s.color}
                  strokeWidth={2}
                  strokeDasharray={s.dashed ? "6 4" : undefined}
                  dot={false}
                  activeDot={{ r: 4, strokeWidth: 2, stroke: "#ffffff" }}
                  isAnimationActive={false}
                  connectNulls={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <div className="flex h-full items-center justify-center text-base text-ink-400">{emptyMessage}</div>
        )}
      </div>
      {footer ? <div className="border-t border-ink-700 px-5 py-2.5 text-sm text-ink-400">{footer}</div> : null}
    </div>
  );
}
