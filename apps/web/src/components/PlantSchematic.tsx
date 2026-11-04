import { MEASUREMENTS } from "../api/types";
import { fmtNum } from "../lib/format";
import type { SchematicPart } from "../lib/subsystems";

export type { SchematicPart };

interface Props {
  /** Latest values to show on sensor tags (optional). */
  values?: Record<string, number | null | undefined>;
  /** Measurement keys to highlight in yellow (e.g. synthetic-affected). */
  highlight?: string[];
  /** Subsystems to outline with a pulsing yellow "Look here" marker. */
  lookHere?: SchematicPart[];
  /** Hide the panel chrome (header + legend) and render the bare SVG. */
  bare?: boolean;
  className?: string;
}

interface TagSpec {
  key: string;
  x: number;
  y: number;
  anchor: { x: number; y: number };
}

const TAGS: TagSpec[] = [
  { key: "AFDP", x: 96, y: 52, anchor: { x: 118, y: 118 } },
  { key: "CDP", x: 318, y: 52, anchor: { x: 340, y: 118 } },
  { key: "TIT", x: 470, y: 36, anchor: { x: 470, y: 118 } },
  { key: "TAT", x: 622, y: 52, anchor: { x: 640, y: 118 } },
  { key: "GTEP", x: 760, y: 52, anchor: { x: 716, y: 92 } },
  { key: "TEY", x: 882, y: 52, anchor: { x: 890, y: 118 } },
];

const AMBIENT = ["AT", "AP", "AH"];

/** Bounding boxes (viewBox units) for the "Look here" outlines. */
const PART_BOXES: Record<SchematicPart, { x: number; y: number; w: number; h: number; label: string }> = {
  ambient: { x: 4, y: 128, w: 54, h: 56, label: "Ambient" },
  intake: { x: 52, y: 92, w: 92, h: 126, label: "Intake / filter" },
  compressor: { x: 168, y: 92, w: 186, h: 126, label: "Compressor" },
  combustor: { x: 358, y: 104, w: 144, h: 102, label: "Combustor" },
  turbine: { x: 506, y: 92, w: 186, h: 126, label: "Turbine" },
  exhaust: { x: 700, y: 6, w: 72, h: 118, label: "Exhaust" },
  generator: { x: 792, y: 104, w: 166, h: 102, label: "Generator" },
};

const C = {
  metalTop: "#e2e8f0",
  metalBottom: "#cbd5e1",
  stroke: "#94a3b8",
  blade: "#94a3b8",
  text: "#334155",
  muted: "#64748b",
  measured: "#2563eb",
  hot: "#ca8a04",
  hotFill: "#fef9c3",
  hotText: "#854d0e",
};

export function PlantSchematic({ values = {}, highlight = [], lookHere = [], bare = false, className = "" }: Props) {
  const isHot = (k: string) => highlight.includes(k);
  const tagFill = (k: string) => (isHot(k) ? C.hotFill : "#ffffff");
  const tagStroke = (k: string) => (isHot(k) ? C.hot : "#cbd5e1");
  const tagText = (k: string) => (isHot(k) ? C.hotText : C.measured);

  const svg = (
    <svg viewBox="0 0 1000 280" className="h-auto w-full" role="img" aria-label="Generic combined-cycle gas turbine train schematic">
      <defs>
        <pattern id="filterHatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="6" stroke={C.measured} strokeOpacity="0.45" strokeWidth="1.5" />
        </pattern>
        <linearGradient id="metal" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={C.metalTop} />
          <stop offset="100%" stopColor={C.metalBottom} />
        </linearGradient>
        <linearGradient id="flame" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#f59e0b" stopOpacity="0.7" />
          <stop offset="100%" stopColor="#f59e0b" stopOpacity="0.1" />
        </linearGradient>
        <marker id="arrow" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto">
          <path d="M0,0 L8,4 L0,8 z" fill={C.stroke} />
        </marker>
        <style>{`@keyframes tm-pulse { 0% { stroke-opacity: 0.35; } 50% { stroke-opacity: 1; } 100% { stroke-opacity: 0.35; } } .tm-look { animation: tm-pulse 1.6s ease-in-out infinite; }`}</style>
      </defs>

      {/* "Look here" outlines (drawn first so tags stay on top) */}
      {lookHere.map((part) => {
        const b = PART_BOXES[part];
        return (
          <g key={part}>
            <rect x={b.x} y={b.y} width={b.w} height={b.h} rx="10" fill="#facc15" fillOpacity="0.18" stroke={C.hot} strokeWidth="3" className="tm-look" />
            <rect x={b.x + b.w / 2 - 38} y={b.y + b.h - 2} width="76" height="20" rx="5" fill={C.hot} />
            <text x={b.x + b.w / 2} y={b.y + b.h + 12} textAnchor="middle" fill="#ffffff" fontSize="12" fontWeight="700">
              LOOK HERE
            </text>
          </g>
        );
      })}

      {/* ambient air flow */}
      <g stroke={C.stroke} strokeWidth="1.5" fill="none" markerEnd="url(#arrow)">
        <line x1="10" y1="140" x2="56" y2="140" />
        <line x1="10" y1="158" x2="56" y2="158" />
        <line x1="10" y1="176" x2="56" y2="176" />
      </g>
      <text x="12" y="64" fill={C.text} fontSize="13" fontWeight="600">
        AMBIENT
      </text>
      {AMBIENT.map((k, i) => (
        <g key={k} transform={`translate(12 ${80 + i * 18})`}>
          <text fill={isHot(k) ? C.hotText : C.measured} fontSize="12" fontFamily="JetBrains Mono, monospace" fontWeight="700">
            {k}
          </text>
          <text x="36" fill={C.muted} fontSize="12">
            {values[k] !== undefined && values[k] !== null ? `${fmtNum(values[k], 1)} ${MEASUREMENTS[k].unit}` : MEASUREMENTS[k].name}
          </text>
        </g>
      ))}

      {/* intake / filter house */}
      <rect x="60" y="100" width="76" height="110" rx="6" fill="url(#metal)" stroke={C.stroke} strokeWidth="1.5" />
      <rect x="70" y="110" width="56" height="90" fill="url(#filterHatch)" stroke={C.measured} strokeOpacity="0.6" strokeWidth="1" />
      <text x="98" y="236" textAnchor="middle" fill={C.text} fontSize="13" fontWeight="600">
        Intake / filter
      </text>

      {/* duct to compressor */}
      <rect x="136" y="140" width="40" height="30" fill={C.metalBottom} stroke={C.stroke} strokeWidth="1.5" />

      {/* compressor (converging) */}
      <path d="M176 100 L346 128 L346 182 L176 210 Z" fill="url(#metal)" stroke={C.stroke} strokeWidth="1.5" />
      {[200, 226, 252, 278, 304, 330].map((x) => (
        <line key={x} x1={x} y1={100 + ((x - 176) / 170) * 28 + 6} x2={x} y2={210 - ((x - 176) / 170) * 28 - 6} stroke={C.blade} strokeWidth="1.5" />
      ))}
      <text x="261" y="236" textAnchor="middle" fill={C.text} fontSize="13" fontWeight="600">
        Compressor
      </text>

      {/* combustor */}
      <rect x="366" y="112" width="128" height="86" rx="18" fill="url(#metal)" stroke={C.stroke} strokeWidth="1.5" />
      <rect x="384" y="126" width="92" height="58" rx="12" fill="url(#flame)" stroke="#d97706" strokeOpacity="0.6" strokeWidth="1" />
      <text x="430" y="236" textAnchor="middle" fill={C.text} fontSize="13" fontWeight="600">
        Combustor
      </text>
      <line x1="430" y1="112" x2="430" y2="84" stroke={C.stroke} strokeWidth="1.5" />
      <text x="430" y="78" textAnchor="middle" fill={C.muted} fontSize="11">
        fuel
      </text>

      {/* turbine (diverging) */}
      <path d="M514 128 L684 100 L684 210 L514 182 Z" fill="url(#metal)" stroke={C.stroke} strokeWidth="1.5" />
      {[536, 562, 588, 614, 640, 666].map((x) => (
        <line key={x} x1={x} y1={128 - ((x - 514) / 170) * 28 + 6} x2={x} y2={182 + ((x - 514) / 170) * 28 - 6} stroke={C.blade} strokeWidth="1.5" />
      ))}
      <text x="599" y="236" textAnchor="middle" fill={C.text} fontSize="13" fontWeight="600">
        Turbine
      </text>

      {/* exhaust stack */}
      <path d="M684 118 L724 118 L724 44 L748 44 L748 118" fill="none" stroke={C.stroke} strokeWidth="1.5" />
      <rect x="724" y="30" width="24" height="14" fill={C.metalBottom} stroke={C.stroke} strokeWidth="1.5" />
      <g stroke={C.stroke} strokeWidth="1.5" fill="none" markerEnd="url(#arrow)">
        <line x1="736" y1="28" x2="736" y2="12" />
      </g>
      <text x="736" y="140" textAnchor="middle" fill={C.text} fontSize="12">
        exhaust
      </text>
      <text x="736" y="155" textAnchor="middle" fill={C.muted} fontSize="11">
        (to HRSG)
      </text>

      {/* shaft + generator */}
      <line x1="684" y1="155" x2="800" y2="155" stroke={C.stroke} strokeWidth="6" strokeLinecap="round" />
      <rect x="800" y="112" width="150" height="86" rx="28" fill="url(#metal)" stroke={C.stroke} strokeWidth="1.5" />
      <ellipse cx="800" cy="155" rx="12" ry="43" fill={C.metalBottom} stroke={C.stroke} strokeWidth="1.5" />
      <text x="875" y="160" textAnchor="middle" fill={C.text} fontSize="14" fontWeight="700">
        G
      </text>
      <text x="875" y="236" textAnchor="middle" fill={C.text} fontSize="13" fontWeight="600">
        Generator
      </text>
      <g stroke={C.stroke} strokeWidth="1.5" fill="none" markerEnd="url(#arrow)">
        <line x1="950" y1="155" x2="992" y2="155" />
      </g>
      <text x="972" y="140" textAnchor="middle" fill={C.muted} fontSize="11">
        grid
      </text>

      {/* sensor tags */}
      {TAGS.map((t) => {
        const v = values[t.key];
        const unit = MEASUREMENTS[t.key].unit.split(" ")[0];
        const w = 92;
        return (
          <g key={t.key}>
            <line x1={t.x} y1={t.y + 14} x2={t.anchor.x} y2={t.anchor.y} stroke={tagStroke(t.key)} strokeWidth="1.2" strokeDasharray="3 3" />
            <circle cx={t.anchor.x} cy={t.anchor.y} r="4" fill={isHot(t.key) ? C.hot : C.measured} />
            <rect x={t.x - w / 2} y={t.y - 14} width={w} height="28" rx="6" fill={tagFill(t.key)} stroke={tagStroke(t.key)} strokeWidth="1.5" />
            <text x={t.x} y={t.y + (v !== undefined && v !== null ? -1 : 5)} textAnchor="middle" fill={tagText(t.key)} fontSize="13" fontWeight="700" fontFamily="JetBrains Mono, monospace">
              {t.key}
            </text>
            {v !== undefined && v !== null ? (
              <text x={t.x} y={t.y + 11} textAnchor="middle" fill={C.text} fontSize="11" fontFamily="JetBrains Mono, monospace">
                {fmtNum(v, 1)} {unit}
              </text>
            ) : null}
            <title>{MEASUREMENTS[t.key].name}</title>
          </g>
        );
      })}
    </svg>
  );

  if (bare) return <div className={className}>{svg}</div>;

  return (
    <div className={`panel ${className}`}>
      <div className="panel-header">
        <div>
          <div className="panel-title">Monitored gas turbine train</div>
          <div className="mt-0.5 text-sm text-ink-300">
            Generic schematic — not the UCI facility. Tags show the 11 published hourly measurements.
          </div>
        </div>
        <div className="flex items-center gap-3 text-sm text-ink-300">
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm bg-blue-600" /> measured
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm bg-yellow-400" /> affected by scenario
          </span>
        </div>
      </div>
      <div className="px-4 pb-3 pt-2">{svg}</div>
    </div>
  );
}
