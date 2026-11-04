/** Provenance chips + "Legend & provenance" overlay for the 3D twin. */
import { Layers, X } from "lucide-react";
import type { Provenance } from "./types";

export const PROV: Record<Provenance, { label: string; cls: string; dot: string }> = {
  real: { label: "REAL DATA", cls: "border-green-300 bg-green-50 text-green-800", dot: "bg-green-600" },
  model: { label: "MODEL-DERIVED", cls: "border-dashed border-green-400 bg-white text-green-800", dot: "bg-green-400" },
  simulated: { label: "SIMULATED", cls: "border-blue-300 bg-blue-50 text-blue-800", dot: "bg-blue-600" },
  synthetic: { label: "SYNTHETIC", cls: "border-yellow-400 bg-yellow-100 text-yellow-900", dot: "bg-yellow-400" },
  illustrative: { label: "ILLUSTRATIVE", cls: "border-ink-600 bg-ink-800 text-ink-300", dot: "bg-ink-500" },
};

export function ProvChip({ p, label }: { p: Provenance; label?: string }) {
  const s = PROV[p];
  return (
    <span className={`inline-flex items-center whitespace-nowrap rounded border px-1.5 py-px text-[10px] font-bold tracking-wide ${s.cls}`}>
      {label ?? s.label}
    </span>
  );
}

const FLOW_KEY: { color: string; label: string; driver: string }[] = [
  { color: "#7cc4f5", label: "Air", driver: "speed ∝ TEY" },
  { color: "#f97316", label: "Fuel gas", driver: "illustrative; combustor glow = TIT" },
  { color: "#ef4444", label: "Hot gas → exhaust", driver: "colour = TIT, cools to grey" },
  { color: "#ffffff", label: "Steam", driver: "illustrative, ∝ TEY" },
  { color: "#06b6d4", label: "Condensate / cooling water", driver: "illustrative, ∝ TEY" },
  { color: "#facc15", label: "Electricity pulses", driver: "rate & glow = TEY" },
  { color: "#a16207", label: "Dust at intake", driver: "amount = AFDP" },
  { color: "#9ca3af", label: "Stack plume", driver: "size = GTEP, tint = CO / NOx" },
];

export function LegendOverlay({ onClose }: { onClose: () => void }) {
  return (
    <div className="absolute right-2 top-12 z-20 max-h-[calc(100%-4rem)] w-[min(360px,calc(100%-1rem))] overflow-y-auto rounded-lg border border-ink-600 bg-white/95 p-3 text-xs text-ink-200 shadow-lg backdrop-blur">
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-sm font-semibold text-ink-50">
          <Layers size={15} /> Legend &amp; provenance
        </div>
        <button className="rounded p-1 hover:bg-ink-800" onClick={onClose} aria-label="Close legend">
          <X size={14} />
        </button>
      </div>
      <ul className="space-y-1.5">
        <li className="flex gap-2">
          <ProvChip p="real" />
          <span>UCI hourly series (AT, AP, AH, AFDP, GTEP, TIT, TAT, TEY, CDP, CO, NOx) drive flow speed, glow, gauges, dust and plume. TEY in MWh as published; CDP unit under validation.</span>
        </li>
        <li className="flex gap-2">
          <ProvChip p="model" />
          <span>Expected TEY from the baseline model; electrical temperatures come from the thermal model.</span>
        </li>
        <li className="flex gap-2">
          <ProvChip p="simulated" />
          <span>Electrical temperatures (generator, 52G, GSU, 52H, busbar) and breaker states — no thermal sensors or breaker status are connected.</span>
        </li>
        <li className="flex gap-2">
          <ProvChip p="synthetic" />
          <span>Yellow rings mark equipment whose values carry a synthetic scenario overlay (demo transformation, not a real fault).</span>
        </li>
        <li className="flex gap-2">
          <ProvChip p="illustrative" />
          <span>Generic geometry, steam / water circuits, fuel flow and the steam turbine — not in the data, not the real facility.</span>
        </li>
      </ul>
      <div className="mt-3 border-t border-ink-700 pt-2 font-semibold text-ink-100">Flows</div>
      <ul className="mt-1 grid grid-cols-1 gap-1">
        {FLOW_KEY.map((f) => (
          <li key={f.label} className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 shrink-0 rounded-full border border-ink-500" style={{ background: f.color }} />
            <span className="font-medium text-ink-100">{f.label}</span>
            <span className="text-ink-400">— {f.driver}</span>
          </li>
        ))}
      </ul>
      <div className="mt-3 border-t border-ink-700 pt-2 font-semibold text-ink-100">Markers</div>
      <ul className="mt-1 space-y-1">
        <li className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full bg-red-600" /> LOOK HERE — rank-1 hypothesis location</li>
        <li className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full bg-amber-500" /> Other screening flag in the window (emissions / electrical)</li>
        <li className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full border-2 border-yellow-400" /> SYNTHETIC overlay ring</li>
      </ul>
      <p className="mt-3 text-[11px] text-ink-400">
        Data: Kaya, Tüfekci &amp; Gürgen (2019), UCI Gas Turbine CO and NOx Emission Data Set, CC BY 4.0. Rows have no timestamps (year + sample index only). Equipment text written for ThermoMind.
      </p>
    </div>
  );
}
