/**
 * Canvas host for the 3D twin with DOM overlays (banner, toolbar, hover tooltip, info card, legend).
 * The three.js scene is lazy-loaded; when WebGL is unavailable the SVG PlantSchematic is shown.
 */
import { Component, Suspense, lazy, useCallback, useMemo, useState, type ReactNode } from "react";
import { Crosshair, Eye, EyeOff, Info, Layers, LocateFixed, RotateCcw, X } from "lucide-react";
import { MEASUREMENTS } from "../../api/types";
import { PlantSchematic } from "../../components/PlantSchematic";
import { fmtNum } from "../../lib/format";
import type { SchematicPart } from "../../lib/subsystems";
import type { TwinController } from "./controller";
import { thermalTempsAt } from "./data";
import { EQUIPMENT_BY_ID } from "./layout";
import { LegendOverlay, ProvChip } from "./provenance";
import type { EquipmentId } from "./types";

const TwinScene = lazy(() => import("./scene/TwinScene"));

export const TWIN_BANNER = "3D twin is a generic combined-cycle plant driven by the UCI data — not the real facility; no control actions";

export function hasWebGL(): boolean {
  try {
    const c = document.createElement("canvas");
    return Boolean(window.WebGLRenderingContext && (c.getContext("webgl2") || c.getContext("webgl")));
  } catch {
    return false;
  }
}

class SceneBoundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(err: unknown) {
    console.warn("3D twin failed, showing SVG fallback", err);
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

const EQUIP_TO_PART: Partial<Record<EquipmentId, SchematicPart>> = {
  ambient_station: "ambient",
  filter_house: "intake",
  afdp_tx: "intake",
  compressor: "compressor",
  cdp_tx: "compressor",
  combustor: "combustor",
  turbine: "turbine",
  exhaust_diffuser: "exhaust",
  stack: "exhaust",
  hrsg: "exhaust",
  generator: "generator",
  breaker_52g: "generator",
  gsu_transformer: "generator",
  hv_switchgear: "generator",
  busbar: "generator",
};

function Fallback({ ctl, reason }: { ctl: TwinController; reason: string }) {
  const parts = [...new Set(ctl.location.hotspots.map((h) => EQUIP_TO_PART[h.equipment]).filter((p): p is SchematicPart => Boolean(p)))];
  return (
    <div className="flex h-full flex-col gap-2 overflow-auto bg-white p-3">
      <div className="flex items-start gap-2 rounded-md border border-yellow-400 bg-yellow-100 px-3 py-2 text-sm text-yellow-900">
        <Info size={16} className="mt-0.5 shrink-0" />
        {reason} Showing the 2D schematic instead (same data, same “look here” markers).
      </div>
      <PlantSchematic bare values={ctl.current.v} highlight={ctl.data.series?.syntheticMeasures ?? []} lookHere={parts} />
    </div>
  );
}

const unitShort = (k: string) => (MEASUREMENTS[k]?.unit ?? "").split(" ")[0];

function breakerState(tey: number | null | undefined) {
  if (tey === null || tey === undefined) return "unknown";
  return tey > 0 ? "closed (inferred from TEY > 0)" : "open (inferred from TEY = 0)";
}

function EquipmentReadout({ ctl, id, full }: { ctl: TwinController; id: EquipmentId; full: boolean }) {
  const e = EQUIPMENT_BY_ID[id];
  const synth = ctl.data.series?.syntheticMeasures ?? [];
  const t = thermalTempsAt(ctl.data.thermal, ctl.current.row);
  const status = e.thermalAsset ? ctl.data.thermal?.status.find((s) => s.asset_id === e.thermalAsset) : undefined;
  return (
    <div className="space-y-1">
      {e.measures.length > 0 ? (
        <table className="w-full text-xs">
          <tbody>
            {e.measures.map((m) => (
              <tr key={m}>
                <td className="pr-2 font-mono font-bold text-blue-700">{m}</td>
                <td className="pr-2 font-mono text-ink-50">
                  {fmtNum(ctl.current.v[m], 2)} <span className="text-ink-400">{unitShort(m)}</span>
                </td>
                <td className="text-right">{synth.includes(m) ? <ProvChip p="synthetic" /> : <ProvChip p="real" />}</td>
              </tr>
            ))}
            {id === "generator" && ctl.current.expectedTey !== null ? (
              <tr>
                <td className="pr-2 font-mono font-bold text-green-700">TEY exp.</td>
                <td className="pr-2 font-mono text-ink-50">
                  {fmtNum(ctl.current.expectedTey, 2)} <span className="text-ink-400">MWh</span>
                </td>
                <td className="text-right">
                  <ProvChip p="model" />
                </td>
              </tr>
            ) : null}
            {e.thermalAsset && t ? (
              <tr>
                <td className="pr-2 font-mono font-bold text-blue-700">Temp.</td>
                <td className="pr-2 font-mono text-ink-50">
                  {fmtNum(t[e.thermalAsset], 1)} <span className="text-ink-400">°C</span>
                  {status ? <span className="text-ink-400"> / alarm {fmtNum(status.alarm_c, 0)}</span> : null}
                </td>
                <td className="text-right">
                  <ProvChip p={ctl.data.thermal?.synthetic ? "synthetic" : "simulated"} />
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      ) : (
        <div className="text-xs text-ink-400">No measurement in the UCI data for this item.</div>
      )}
      {id === "breaker_52g" || id === "hv_switchgear" ? (
        <div className="text-xs text-ink-200">
          Breaker {id === "breaker_52g" ? "52G" : "52H"}: <b>{breakerState(ctl.current.v.TEY)}</b> <ProvChip p="simulated" />
          {full ? <div className="mt-1 text-ink-400">Switching is performed only by authorised personnel per permit; this software issues no commands.</div> : null}
        </div>
      ) : null}
    </div>
  );
}

function Tooltip({ ctl }: { ctl: TwinController }) {
  const h = ctl.hovered;
  if (!h) return null;
  const e = EQUIPMENT_BY_ID[h.id];
  return (
    <div
      className="pointer-events-none fixed z-50 w-64 rounded-lg border border-ink-600 bg-white/95 p-2.5 shadow-lg backdrop-blur"
      style={{ left: Math.min(h.x + 14, window.innerWidth - 270), top: Math.min(h.y + 14, window.innerHeight - 160) }}
      role="tooltip"
    >
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="text-sm font-semibold text-ink-50">{e.label}</span>
        <ProvChip p={e.provenance} />
      </div>
      <EquipmentReadout ctl={ctl} id={h.id} full={false} />
      <div className="mt-1 text-[10px] text-ink-400">Click for details</div>
    </div>
  );
}

function InfoCard({ ctl }: { ctl: TwinController }) {
  const id = ctl.selected;
  if (!id) return null;
  const e = EQUIPMENT_BY_ID[id];
  const hs = ctl.location.hotspots.filter((h) => h.equipment === id);
  return (
    <div className="absolute bottom-11 left-2 z-20 w-[min(340px,calc(100%-1rem))] rounded-lg border border-ink-600 bg-white/95 p-3 shadow-lg backdrop-blur">
      <div className="mb-1 flex items-start justify-between gap-2">
        <div>
          <div className="text-sm font-semibold text-ink-50">{e.label}</div>
          <div className="mt-0.5">
            <ProvChip p={e.provenance} />
          </div>
        </div>
        <button className="rounded p-1 hover:bg-ink-800" onClick={() => ctl.setSelected(null)} aria-label="Close info card">
          <X size={14} />
        </button>
      </div>
      {hs.map((h) => (
        <div key={h.id} className="mb-2 rounded border border-red-200 bg-red-50 px-2 py-1 text-xs font-semibold text-red-800">
          {h.label}
        </div>
      ))}
      <p className="mb-2 text-xs text-ink-200">{e.description}</p>
      <EquipmentReadout ctl={ctl} id={id} full />
      <div className="mt-2 flex items-center justify-between">
        <button className="btn btn-secondary px-2 py-1 text-xs" onClick={() => ctl.flyTo(id)}>
          <Crosshair size={13} /> Fly to
        </button>
        <span className="text-[10px] text-ink-400">Information only — no control actions.</span>
      </div>
    </div>
  );
}

interface Props {
  ctl: TwinController;
  /** CSS height of the canvas area, e.g. "60vh" or 420. */
  height: string | number;
  compact?: boolean;
  className?: string;
}

export function TwinView({ ctl, height, compact = false, className = "" }: Props) {
  const webgl = useMemo(hasWebGL, []);
  const [showLabels, setShowLabels] = useState(() => !compact && (typeof window === "undefined" || window.innerWidth >= 640));
  const [legend, setLegend] = useState(false);
  const [stats, setStats] = useState<{ calls: number; fps: number } | null>(null);
  const onStats = useCallback((s: { calls: number; fps: number }) => setStats({ calls: s.calls, fps: s.fps }), []);
  const primary = ctl.location.hotspots[0]?.equipment ?? null;
  const fallback = (reason: string) => <Fallback ctl={ctl} reason={reason} />;

  return (
    <div className={`relative overflow-hidden rounded-xl border border-ink-700 bg-[#f3f5f8] ${className}`} style={{ height }} data-testid="twin-view">
      {webgl ? (
        <SceneBoundary fallback={fallback("The 3D view failed to start (WebGL error).")}>
          <Suspense
            fallback={
              <div className="flex h-full items-center justify-center text-sm text-ink-400">Loading 3D plant…</div>
            }
          >
            <TwinScene
              live={ctl.live}
              hotspots={ctl.location.hotspots}
              syntheticRings={ctl.location.rings}
              hovered={ctl.hovered?.id ?? null}
              selected={ctl.selected}
              onHover={ctl.onHover}
              onSelect={ctl.setSelected}
              showLabels={showLabels}
              focus={ctl.focus.id}
              focusNonce={ctl.focus.nonce}
              onStats={onStats}
            />
          </Suspense>
        </SceneBoundary>
      ) : (
        fallback("WebGL is not available in this browser, so the 3D twin cannot be shown.")
      )}

      {/* persistent banner */}
      <div className="pointer-events-none absolute bottom-2 left-2 z-10 max-w-[calc(100%-1rem)] rounded-md border border-blue-200 bg-white/90 px-2 py-1 text-[11px] font-semibold text-blue-900 shadow-sm sm:max-w-[70%]" data-testid="twin-banner">
        {TWIN_BANNER}
      </div>

      {webgl ? (
        <div className="absolute right-2 top-2 z-10 flex gap-1">
          {primary ? (
            <button className="btn btn-secondary bg-white/90 px-2 py-1 text-xs" onClick={() => ctl.flyTo(primary)} title="Fly to the hot spot">
              <LocateFixed size={13} /> {compact ? "" : "Hot spot"}
            </button>
          ) : null}
          <button className="btn btn-secondary bg-white/90 px-2 py-1 text-xs" onClick={() => ctl.flyTo(null)} title="Reset view">
            <RotateCcw size={13} />
          </button>
          <button className="btn btn-secondary bg-white/90 px-2 py-1 text-xs" onClick={() => setShowLabels((v) => !v)} title="Toggle labels">
            {showLabels ? <EyeOff size={13} /> : <Eye size={13} />}
          </button>
          <button
            className={`btn px-2 py-1 text-xs ${legend ? "btn-primary" : "btn-secondary bg-white/90"}`}
            onClick={() => setLegend((v) => !v)}
            title="Legend & provenance"
          >
            <Layers size={13} /> {compact ? "" : "Legend"}
          </button>
        </div>
      ) : null}

      {legend ? <LegendOverlay onClose={() => setLegend(false)} /> : null}
      {webgl ? <InfoCard ctl={ctl} /> : null}
      {webgl ? <Tooltip ctl={ctl} /> : null}

      {stats && !compact ? (
        <div className="pointer-events-none absolute bottom-2 right-2 z-10 rounded bg-white/80 px-1.5 py-0.5 font-mono text-[10px] text-ink-400" data-testid="twin-stats">
          {stats.calls} draw calls · {stats.fps.toFixed(0)} fps
        </div>
      ) : null}
    </div>
  );
}
