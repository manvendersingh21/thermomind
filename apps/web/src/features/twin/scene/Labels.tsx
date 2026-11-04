/** Small DOM name tags for the main equipment (drei Html; no draw calls). */
import { Html } from "@react-three/drei";
import { EQUIPMENT_BY_ID } from "../layout";
import type { EquipmentId } from "../types";

const LABELLED: { id: EquipmentId; text: string; dy?: number }[] = [
  { id: "ambient_station", text: "Ambient AT/AP/AH" },
  { id: "filter_house", text: "Filter house" },
  { id: "compressor", text: "Compressor", dy: -0.4 },
  { id: "combustor", text: "Combustor" },
  { id: "turbine", text: "Turbine", dy: -0.4 },
  { id: "hrsg", text: "HRSG" },
  { id: "stack", text: "Stack" },
  { id: "steam_turbine", text: "Steam turbine" },
  { id: "condenser", text: "Condenser", dy: -1.4 },
  { id: "cooling_tower", text: "Cooling tower" },
  { id: "generator", text: "Generator" },
  { id: "breaker_52g", text: "52G" },
  { id: "gsu_transformer", text: "GSU transformer" },
  { id: "hv_switchgear", text: "HV switchgear 52H" },
  { id: "busbar", text: "Busbar" },
  { id: "grid_line", text: "To grid" },
  { id: "fuel_skid", text: "Fuel gas" },
];

export function EquipmentLabels({ hovered }: { hovered: EquipmentId | null }) {
  return (
    <group>
      {LABELLED.map(({ id, text, dy = 0 }) => {
        const e = EQUIPMENT_BY_ID[id];
        const y = e.pos[1] + e.size[1] / 2 + 0.5 + dy;
        return (
          <Html key={id} position={[e.pos[0], y, e.pos[2]]} center zIndexRange={[9, 0]} style={{ pointerEvents: "none" }}>
            <div
              className={`whitespace-nowrap rounded border px-1.5 py-px text-[11px] font-semibold shadow-sm ${
                hovered === id ? "border-blue-500 bg-blue-600 text-white" : "border-ink-600 bg-white/90 text-ink-200"
              }`}
            >
              {text}
            </div>
          </Html>
        );
      })}
    </group>
  );
}
