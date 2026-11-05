import { useEffect, useMemo, useRef, useState } from "react";
import { MEASUREMENTS } from "../api/types";
import { fmtNum } from "../lib/format";
import type { StepRecord } from "../features/simulator/api";

/**
 * Animated schematic for the PHYSICS SIMULATOR. Geometry reuses PlantSchematic
 * (intake/filter → compressor → combustor → turbine → exhaust → generator → grid).
 * Every value shown here comes from a software model; no real plant is connected.
 */

interface Props {
  record: StepRecord | null;
  /** When false, particles freeze in place. */
  running: boolean;
  className?: string;
}

type Pt = [number, number];

interface Stream {
  id: string;
  pts: Pt[];
  count: number;
  r: number;
  kind: "air" | "fuel" | "gas" | "elec";
}

const STREAMS: Stream[] = [
  { id: "air1", kind: "air", r: 3, count: 6, pts: [[10, 140], [60, 140], [136, 148], [176, 150], [346, 150], [392, 150]] },
  { id: "air2", kind: "air", r: 3, count: 6, pts: [[10, 158], [60, 158], [136, 155], [176, 155], [346, 155], [392, 155]] },
  { id: "air3", kind: "air", r: 3, count: 6, pts: [[10, 176], [60, 176], [136, 162], [176, 160], [346, 160], [392, 160]] },
  { id: "fuel", kind: "fuel", r: 3.2, count: 3, pts: [[430, 66], [430, 132]] },
  { id: "gas", kind: "gas", r: 3.6, count: 14, pts: [[470, 155], [684, 155], [736, 120], [736, 44], [736, 2]] },
  { id: "elec", kind: "elec", r: 4.2, count: 3, pts: [[950, 155], [1012, 155]] },
];

const BASE_PX_S = 110;

interface TagSpec {
  key: string;
  x: number;
  y: number;
  anchor?: { x: number; y: number };
}

const TAGS: TagSpec[] = [
  { key: "AT", x: -68, y: 150 },
  { key: "AP", x: -68, y: 184 },
  { key: "AH", x: -68, y: 218 },
  { key: "AFDP", x: 96, y: 52, anchor: { x: 118, y: 118 } },
  { key: "CDP", x: 318, y: 52, anchor: { x: 340, y: 118 } },
  { key: "TIT", x: 486, y: 36, anchor: { x: 470, y: 118 } },
  { key: "TAT", x: 622, y: 64, anchor: { x: 640, y: 118 } },
  { key: "GTEP", x: 808, y: 64, anchor: { x: 724, y: 92 } },
  { key: "TEY", x: 900, y: 92, anchor: { x: 890, y: 118 } },
  { key: "CO", x: 628, y: 18, anchor: { x: 728, y: 30 } },
  { key: "NOX", x: 846, y: 18, anchor: { x: 748, y: 30 } },
];

const C = {
  metalTop: "#e2e8f0",
  metalBottom: "#cbd5e1",
  stroke: "#94a3b8",
  blade: "#94a3b8",
  text: "#334155",
  muted: "#64748b",
};

const PROV_STYLE: Record<string, { fill: string; stroke: string; text: string; label: string }> = {
  real_input: { fill: "#f0fdf4", stroke: "#16a34a", text: "#166534", label: "REAL INPUT" },
  simulated: { fill: "#eff6ff", stroke: "#2563eb", text: "#1d4ed8", label: "SIMULATED" },
  synthetic_fault: { fill: "#fef9c3", stroke: "#ca8a04", text: "#854d0e", label: "SYNTHETIC FAULT" },
  unknown: { fill: "#f8fafc", stroke: "#cbd5e1", text: "#475569", label: "—" },
};

function clamp(v: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, v));
}

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function hexToRgb(h: string): [number, number, number] {
  const n = parseInt(h.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function lerpColor(a: string, b: string, t: number): string {
  const [r1, g1, b1] = hexToRgb(a);
  const [r2, g2, b2] = hexToRgb(b);
  const k = clamp(t, 0, 1);
  const r = Math.round(r1 + (r2 - r1) * k);
  const g = Math.round(g1 + (g2 - g1) * k);
  const bl = Math.round(b1 + (b2 - b1) * k);
  return `rgb(${r},${g},${bl})`;
}

function polyLength(pts: Pt[]): number[] {
  const cum = [0];
  for (let i = 1; i < pts.length; i++) {
    cum.push(cum[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
  }
  return cum;
}

function pointAt(pts: Pt[], cum: number[], d: number): Pt {
  const total = cum[cum.length - 1];
  const dd = ((d % total) + total) % total;
  for (let i = 1; i < pts.length; i++) {
    if (dd <= cum[i]) {
      const seg = cum[i] - cum[i - 1] || 1;
      const t = (dd - cum[i - 1]) / seg;
      return [pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * t, pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * t];
    }
  }
  return pts[pts.length - 1];
}

function prefersReducedMotion(): boolean {
  try {
    return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

/** Relative speed factors (1.0 ≈ nominal) derived from the model's internal state. */
function speedFactors(rec: StepRecord | null) {
  const mf = num(rec?.internal?.mass_flow_kg_s);
  const fuel = num(rec?.internal?.fuel_kg_s);
  const mw = num(rec?.internal?.shaft_mw) ?? num(rec?.TEY);
  const air = mf !== null ? clamp(mf / 450, 0.2, 2.5) : 1;
  const fuelF = fuel !== null ? clamp(fuel / 9, 0.2, 2.5) : 1;
  const gas = mf !== null ? clamp(((mf + (fuel ?? 0)) / 460) * 1.5, 0.3, 3.5) : 1.5;
  const elec = mw !== null ? clamp(mw / 130, 0.15, 2.5) : 1;
  return { air, fuel: fuelF, gas, elec };
}

export function LivePlantSchematic({ record, running, className = "" }: Props) {
  const geo = useMemo(() => STREAMS.map((s) => ({ ...s, cum: polyLength(s.pts) })), []);
  const phases = useRef<Record<string, number>>({});
  const factors = useRef(speedFactors(record));
  factors.current = speedFactors(record);
  const [, setTick] = useState(0);
  const reduced = useMemo(prefersReducedMotion, []);

  useEffect(() => {
    if (!running || reduced) return;
    let raf = 0;
    let last = performance.now();
    let lastPaint = 0;
    const loop = (now: number) => {
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      const f = factors.current;
      for (const s of STREAMS) {
        phases.current[s.id] = (phases.current[s.id] ?? 0) + BASE_PX_S * f[s.kind] * dt;
      }
      if (now - lastPaint > 33) {
        lastPaint = now;
        setTick((t) => (t + 1) % 1_000_000);
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [running, reduced]);

  const tit = num(record?.TIT);
  const titT = tit !== null ? clamp((tit - 1000) / 100, 0, 1) : 0.4;
  const glowColor = lerpColor("#fbbf24", "#dc2626", titT);
  const glowOpacity = record ? 0.35 + 0.55 * titT : 0.15;

  const afdp = num(record?.AFDP);
  const afdpT = afdp !== null ? clamp((afdp - 2) / 5.5, 0, 1) : 0;
  const filterTint = lerpColor("#e0f2fe", "#57534e", afdpT);

  const freq = num(record?.internal?.freq_hz);
  const nominal = freq !== null && freq > 55 ? 60 : 50;
  const span = 0.5;
  const needleDeg = freq !== null ? -120 + 240 * clamp((freq - (nominal - span)) / (2 * span), 0, 1) : -120;

  const closure = num(record?.energy_closure_pct);
  const closureOk = closure !== null && (Math.abs(closure - 100) <= 3 || Math.abs(closure) <= 3);
  const closureWarn = closure !== null && !closureOk && (Math.abs(closure - 100) <= 8 || Math.abs(closure) <= 8);
  const closureStyle = closure === null
    ? { fill: "#f8fafc", stroke: "#cbd5e1", text: "#475569" }
    : closureOk
      ? { fill: "#f0fdf4", stroke: "#16a34a", text: "#166534" }
      : closureWarn
        ? { fill: "#fffbeb", stroke: "#d97706", text: "#92400e" }
        : { fill: "#fef2f2", stroke: "#dc2626", text: "#991b1b" };

  const prov = (k: string) => {
    const p = record?.provenance?.[k];
    return PROV_STYLE[typeof p === "string" && p in PROV_STYLE ? p : "unknown"];
  };

  const particleColor = (kind: Stream["kind"], frac: number) => {
    switch (kind) {
      case "air":
        return "#7dd3fc";
      case "fuel":
        return "#f97316";
      case "gas":
        return lerpColor("#dc2626", "#9ca3af", frac);
      case "elec":
        return "#facc15";
    }
  };

  const ariaLabel = record
    ? `Simulated gas turbine train. TIT ${fmtNum(num(record.TIT), 1)} °C, TEY ${fmtNum(num(record.TEY), 1)} MWh, AFDP ${fmtNum(num(record.AFDP), 2)} mbar, frequency ${fmtNum(freq, 3)} Hz.`
    : "Simulated gas turbine train, no data yet.";

  return (
    <div className={className}>
      <svg viewBox="-130 -8 1270 290" className="h-auto w-full" role="img" aria-label={ariaLabel}>
        <defs>
          <pattern id="lpsFilterHatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="6" stroke="#2563eb" strokeOpacity="0.35" strokeWidth="1.5" />
          </pattern>
          <linearGradient id="lpsMetal" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={C.metalTop} />
            <stop offset="100%" stopColor={C.metalBottom} />
          </linearGradient>
          <filter id="lpsGlow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="6" />
          </filter>
          <filter id="lpsSoft" x="-100%" y="-100%" width="300%" height="300%">
            <feGaussianBlur stdDeviation="1.6" />
          </filter>
          <marker id="lpsArrow" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto">
            <path d="M0,0 L8,4 L0,8 z" fill={C.stroke} />
          </marker>
          <style>{`@keyframes lps-pulse { 0% { stroke-opacity: 0.35; } 50% { stroke-opacity: 1; } 100% { stroke-opacity: 0.35; } } .lps-fault { animation: lps-pulse 1.4s ease-in-out infinite; } @media (prefers-reduced-motion: reduce) { .lps-fault { animation: none; } }`}</style>
        </defs>

        {/* ambient column */}
        <text x="-124" y="122" fill={C.text} fontSize="13" fontWeight="600">
          AMBIENT
        </text>
        <g stroke={C.stroke} strokeWidth="1.5" fill="none" markerEnd="url(#lpsArrow)">
          <line x1="10" y1="140" x2="56" y2="140" />
          <line x1="10" y1="158" x2="56" y2="158" />
          <line x1="10" y1="176" x2="56" y2="176" />
        </g>

        {/* intake / filter house — tint darkens with AFDP */}
        <rect x="60" y="100" width="76" height="110" rx="6" fill="url(#lpsMetal)" stroke={C.stroke} strokeWidth="1.5" />
        <rect x="70" y="110" width="56" height="90" fill={filterTint} fillOpacity={0.25 + 0.6 * afdpT} stroke="#2563eb" strokeOpacity="0.5" strokeWidth="1">
          <title>Filter tint follows AFDP ({fmtNum(afdp, 2)} mbar)</title>
        </rect>
        <rect x="70" y="110" width="56" height="90" fill="url(#lpsFilterHatch)" />
        <text x="98" y="236" textAnchor="middle" fill={C.text} fontSize="13" fontWeight="600">
          Intake / filter
        </text>

        <rect x="136" y="140" width="40" height="30" fill={C.metalBottom} stroke={C.stroke} strokeWidth="1.5" />

        {/* compressor */}
        <path d="M176 100 L346 128 L346 182 L176 210 Z" fill="url(#lpsMetal)" stroke={C.stroke} strokeWidth="1.5" />
        {[200, 226, 252, 278, 304, 330].map((x) => (
          <line key={x} x1={x} y1={100 + ((x - 176) / 170) * 28 + 6} x2={x} y2={210 - ((x - 176) / 170) * 28 - 6} stroke={C.blade} strokeWidth="1.5" />
        ))}
        <text x="261" y="236" textAnchor="middle" fill={C.text} fontSize="13" fontWeight="600">
          Compressor
        </text>

        {/* combustor with TIT-driven glow */}
        <rect x="366" y="112" width="128" height="86" rx="18" fill="url(#lpsMetal)" stroke={C.stroke} strokeWidth="1.5" />
        <ellipse cx="430" cy="155" rx="50" ry="30" fill={glowColor} opacity={glowOpacity} filter="url(#lpsGlow)" />
        <rect x="384" y="126" width="92" height="58" rx="12" fill={glowColor} fillOpacity={0.15 + 0.35 * titT} stroke={glowColor} strokeOpacity="0.8" strokeWidth="1.2">
          <title>Glow colour follows TIT ({fmtNum(tit, 1)} °C)</title>
        </rect>
        <text x="430" y="236" textAnchor="middle" fill={C.text} fontSize="13" fontWeight="600">
          Combustor
        </text>
        <line x1="430" y1="112" x2="430" y2="66" stroke={C.stroke} strokeWidth="1.5" />
        <text x="404" y="74" textAnchor="end" fill={C.muted} fontSize="11">
          fuel
        </text>

        {/* turbine */}
        <path d="M514 128 L684 100 L684 210 L514 182 Z" fill="url(#lpsMetal)" stroke={C.stroke} strokeWidth="1.5" />
        {[536, 562, 588, 614, 640, 666].map((x) => (
          <line key={x} x1={x} y1={128 - ((x - 514) / 170) * 28 + 6} x2={x} y2={182 + ((x - 514) / 170) * 28 - 6} stroke={C.blade} strokeWidth="1.5" />
        ))}
        <text x="599" y="236" textAnchor="middle" fill={C.text} fontSize="13" fontWeight="600">
          Turbine
        </text>

        {/* exhaust stack */}
        <path d="M684 118 L724 118 L724 44 L748 44 L748 118" fill="none" stroke={C.stroke} strokeWidth="1.5" />
        <rect x="724" y="30" width="24" height="14" fill={C.metalBottom} stroke={C.stroke} strokeWidth="1.5" />
        <text x="736" y="140" textAnchor="middle" fill={C.text} fontSize="12">
          exhaust
        </text>

        {/* shaft + generator */}
        <line x1="684" y1="170" x2="800" y2="170" stroke={C.stroke} strokeWidth="6" strokeLinecap="round" />
        <rect x="800" y="112" width="150" height="86" rx="28" fill="url(#lpsMetal)" stroke={C.stroke} strokeWidth="1.5" />
        <ellipse cx="800" cy="155" rx="12" ry="43" fill={C.metalBottom} stroke={C.stroke} strokeWidth="1.5" />
        <text x="875" y="160" textAnchor="middle" fill={C.text} fontSize="14" fontWeight="700">
          G
        </text>
        <text x="875" y="236" textAnchor="middle" fill={C.text} fontSize="13" fontWeight="600">
          Generator
        </text>
        <line x1="950" y1="155" x2="1012" y2="155" stroke={C.stroke} strokeWidth="1.5" markerEnd="url(#lpsArrow)" />
        <text x="982" y="176" textAnchor="middle" fill={C.muted} fontSize="11">
          grid
        </text>

        {/* flow particles */}
        <g aria-hidden="true">
          {geo.map((s) => {
            const total = s.cum[s.cum.length - 1];
            const base = phases.current[s.id] ?? 0;
            return Array.from({ length: s.count }).map((_, i) => {
              const d = base + (i * total) / s.count;
              const [x, y] = pointAt(s.pts, s.cum, d);
              const frac = (((d % total) + total) % total) / total;
              const color = particleColor(s.kind, frac);
              return (
                <g key={`${s.id}-${i}`}>
                  {s.kind === "elec" ? <circle cx={x} cy={y} r={s.r * 2} fill={color} opacity={0.45} filter="url(#lpsSoft)" /> : null}
                  <circle cx={x} cy={y} r={s.r} fill={color} stroke={s.kind === "air" ? "#0284c7" : "none"} strokeOpacity={0.4} strokeWidth={0.8} />
                </g>
              );
            });
          })}
        </g>

        {/* frequency dial */}
        <g transform="translate(1076 92)">
          <circle r="46" fill="#ffffff" stroke="#cbd5e1" strokeWidth="1.5" />
          {[-120, -60, 0, 60, 120].map((a) => {
            const rad = ((a - 90) * Math.PI) / 180;
            return <line key={a} x1={Math.cos(rad) * 36} y1={Math.sin(rad) * 36} x2={Math.cos(rad) * 44} y2={Math.sin(rad) * 44} stroke={a === 0 ? "#16a34a" : "#94a3b8"} strokeWidth={a === 0 ? 2.5 : 1.5} />;
          })}
          <text x={-33} y={34} fill={C.muted} fontSize="9" textAnchor="middle">{nominal - span}</text>
          <text x={33} y={34} fill={C.muted} fontSize="9" textAnchor="middle">{nominal + span}</text>
          <line x1="0" y1="0" x2="0" y2="-38" stroke="#0f172a" strokeWidth="2.5" strokeLinecap="round" transform={`rotate(${needleDeg})`} />
          <circle r="4" fill="#0f172a" />
          <text y="20" textAnchor="middle" fill={C.text} fontSize="13" fontWeight="700" fontFamily="JetBrains Mono, monospace">
            {freq !== null ? freq.toFixed(3) : "—"}
          </text>
          <text y="62" textAnchor="middle" fill={C.text} fontSize="11" fontWeight="600">
            frequency (Hz, model)
          </text>
          <title>Grid frequency from the model's internal state (internal.freq_hz)</title>
        </g>

        {/* energy closure badge */}
        <g transform="translate(1016 176)">
          <rect width="120" height="50" rx="8" fill={closureStyle.fill} stroke={closureStyle.stroke} strokeWidth="1.5" />
          <text x="60" y="18" textAnchor="middle" fill={closureStyle.text} fontSize="10" fontWeight="700" letterSpacing="0.5">
            ENERGY CLOSURE
          </text>
          <text x="60" y="39" textAnchor="middle" fill={closureStyle.text} fontSize="16" fontWeight="700" fontFamily="JetBrains Mono, monospace">
            {closure !== null ? `${fmtNum(closure, 2)} %` : "—"}
          </text>
          <title>Model energy balance check (energy_closure_pct)</title>
        </g>

        {/* live tag chips, coloured by provenance */}
        {TAGS.map((t) => {
          const v = num(record?.[t.key as keyof StepRecord]);
          const s = prov(t.key);
          const isFault = record?.provenance?.[t.key] === "synthetic_fault";
          const unit = (MEASUREMENTS[t.key]?.unit ?? "").split(" ")[0];
          const w = t.anchor ? 96 : 112;
          return (
            <g key={t.key}>
              {t.anchor ? (
                <>
                  <line x1={t.x} y1={t.y + 14} x2={t.anchor.x} y2={t.anchor.y} stroke={s.stroke} strokeWidth="1.2" strokeDasharray="3 3" />
                  <circle cx={t.anchor.x} cy={t.anchor.y} r="4" fill={s.stroke} />
                </>
              ) : null}
              {isFault ? (
                <rect x={t.x - w / 2 - 4} y={t.y - 18} width={w + 8} height="36" rx="9" fill="none" stroke="#facc15" strokeWidth="3" className="lps-fault" />
              ) : null}
              <rect x={t.x - w / 2} y={t.y - 14} width={w} height="28" rx="6" fill={s.fill} stroke={s.stroke} strokeWidth={isFault ? 2.5 : 1.5} />
              <text x={t.x} y={t.y - 1} textAnchor="middle" fill={s.text} fontSize="12" fontWeight="700" fontFamily="JetBrains Mono, monospace">
                {t.key}
              </text>
              <text x={t.x} y={t.y + 11} textAnchor="middle" fill={C.text} fontSize="11" fontFamily="JetBrains Mono, monospace">
                {v !== null ? `${fmtNum(v, t.key === "AFDP" ? 2 : 1)} ${unit}` : "—"}
              </text>
              <title>{`${MEASUREMENTS[t.key]?.name ?? t.key} — ${s.label}`}</title>
            </g>
          );
        })}
      </svg>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-ink-300">
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm border border-green-600 bg-green-50" /> REAL INPUT (UCI ambient row)</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm border border-blue-600 bg-blue-50" /> SIMULATED (model output)</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm border-2 border-yellow-400 bg-yellow-100" /> SYNTHETIC FAULT</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-sky-300" /> air</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-orange-500" /> fuel</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-red-600" /> hot gas</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-yellow-400" /> electricity</span>
      </div>
    </div>
  );
}

export default LivePlantSchematic;
