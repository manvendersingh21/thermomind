import type { KeyboardEvent } from "react";
import { fmtNum } from "../../lib/format";
import type { Motor, MotorState } from "./types";

type WindingLevel = "normal" | "approaching" | "alarm" | "limit";

/** Winding colors (reserved for state; always paired with text). Same palette idea as the thermal map. */
export const WINDING_STYLE: Record<WindingLevel, { stroke: string; fill: string; text: string; label: string }> = {
  normal: { stroke: "#16a34a", fill: "#dcfce7", text: "#166534", label: "NORMAL" },
  approaching: { stroke: "#ca8a04", fill: "#fef9c3", text: "#854d0e", label: "APPROACHING ALARM" },
  alarm: { stroke: "#dc2626", fill: "#fee2e2", text: "#991b1b", label: "ABOVE ALARM" },
  limit: { stroke: "#b91c1c", fill: "#fecaca", text: "#7f1d1d", label: "AT/ABOVE LIMIT" },
};

const APPROACH_MARGIN_K = 15;

export function windingLevel(m: Pick<Motor, "winding_c" | "alarm_c" | "limit_c">): WindingLevel {
  if (m.winding_c >= m.limit_c) return "limit";
  if (m.winding_c >= m.alarm_c) return "alarm";
  if (m.winding_c >= m.alarm_c - APPROACH_MARGIN_K) return "approaching";
  return "normal";
}

const MOTOR_STATE: Record<MotorState, { label: string; color: string; bg: string }> = {
  running: { label: "RUNNING", color: "#166534", bg: "#dcfce7" },
  starting: { label: "STARTING", color: "#1e40af", bg: "#dbeafe" },
  standby: { label: "STANDBY", color: "#334155", bg: "#e2e8f0" },
  stopped: { label: "STOPPED", color: "#334155", bg: "#f1f5f9" },
  tripped: { label: "TRIPPED", color: "#991b1b", bg: "#fecaca" },
};

export function motorStateLabel(s: string): string {
  return (MOTOR_STATE[s as MotorState]?.label ?? s.toUpperCase());
}

const TEXT = "#334155";
const MUTED = "#64748b";
const LINE = "#94a3b8";
const SCALE_MAX = 170;

const CELL_W = 108;
const X0 = 30;
const GAP = 16;
const GROUPS: { key: string; title: string; ids: string[] }[] = [
  { key: "cooling_water", title: "Cooling-water pumps", ids: ["CWP_A", "CWP_B"] },
  { key: "feedwater", title: "Boiler feedwater pumps", ids: ["BFP_A", "BFP_B"] },
  { key: "ct_fans", title: "Cooling-tower fans", ids: ["CTF_1", "CTF_2", "CTF_3"] },
  { key: "lube_oil", title: "Lube-oil pump", ids: ["LOP"] },
];

const FRAME_TOP = 50;
const FRAME_BOTTOM = 386;
const ICON_CY = 92;
const BAR_TOP = 190;
const BAR_BOTTOM = 310;

function barY(c: number): number {
  const v = Math.max(0, Math.min(SCALE_MAX, c));
  return BAR_BOTTOM - ((BAR_BOTTOM - BAR_TOP) * v) / SCALE_MAX;
}

/** Pump impeller (pumps/LOP) or fan blades (cooling-tower fans) glyph, spinning is not animated: state is text. */
function Glyph({ fan, cx, cy, color }: { fan: boolean; cx: number; cy: number; color: string }) {
  if (fan) {
    return (
      <g stroke={color} strokeWidth={1.6} fill="none">
        <circle cx={cx} cy={cy} r={15} />
        {[0, 120, 240].map((a) => (
          <path key={a} transform={`rotate(${a} ${cx} ${cy})`} d={`M ${cx} ${cy} C ${cx + 9} ${cy - 3}, ${cx + 10} ${cy - 11}, ${cx + 2} ${cy - 13} Z`} fill={color} fillOpacity={0.25} />
        ))}
        <circle cx={cx} cy={cy} r={2} fill={color} />
      </g>
    );
  }
  return (
    <g stroke={color} strokeWidth={1.6} fill="none">
      <circle cx={cx} cy={cy} r={15} />
      {[0, 90, 180, 270].map((a) => (
        <path key={a} transform={`rotate(${a} ${cx} ${cy})`} d={`M ${cx} ${cy} Q ${cx + 12} ${cy - 2} ${cx + 11} ${cy - 11}`} />
      ))}
      <circle cx={cx} cy={cy} r={2} fill={color} />
    </g>
  );
}

interface Props {
  motors: Motor[];
  selected?: string | null;
  onSelect?: (id: string) => void;
}

export function AuxBoard({ motors, selected, onSelect }: Props) {
  const byId = new Map(motors.map((m) => [m.asset_id, m]));
  let x = X0;
  const placed = GROUPS.map((g) => {
    const w = g.ids.length * CELL_W;
    const out = { ...g, x, w };
    x += w + GAP;
    return out;
  });

  const keyHandler = (id: string) => (e: KeyboardEvent<SVGGElement>) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onSelect?.(id);
    }
  };

  return (
    <svg
      viewBox="0 0 1000 420"
      width="100%"
      role="img"
      aria-label="Auxiliaries board (SIMULATED): cooling-water pumps A and B, boiler feedwater pumps A and B, cooling-tower fans 1 to 3 and lube-oil pump, each with winding temperature, current, vibration zone and state"
      className="block h-auto w-full"
    >
      <rect x={0} y={0} width={1000} height={420} fill="#ffffff" />
      {/* SIMULATED corner badge */}
      <g>
        <rect x={838} y={6} width={156} height={22} rx={5} fill="#fef9c3" stroke="#facc15" />
        <text x={916} y={21} textAnchor="middle" fontSize={12} fontWeight={700} fill="#713f12" letterSpacing={0.5}>SIMULATED</text>
      </g>

      {placed.map((g) => (
        <g key={g.key}>
          <text x={g.x + 4} y={42} fontSize={13} fontWeight={700} fill={TEXT}>{g.title}</text>
          <rect x={g.x} y={FRAME_TOP} width={g.w} height={FRAME_BOTTOM - FRAME_TOP} rx={10} fill="#f8fafc" stroke="#e2e8f0" />
          {g.ids.map((id, i) => {
            const m = byId.get(id);
            const cx = g.x + i * CELL_W + CELL_W / 2;
            if (!m) {
              return (
                <text key={id} x={cx} y={ICON_CY} textAnchor="middle" fontSize={12} fill={MUTED}>{id}: no data</text>
              );
            }
            const lvl = windingLevel(m);
            const ws = WINDING_STYLE[lvl];
            const ms = MOTOR_STATE[m.state] ?? MOTOR_STATE.stopped;
            const isSel = selected === m.asset_id;
            const off = m.state === "stopped" || m.state === "standby";
            const isFan = m.group === "ct_fans";
            const fillH = Math.max(0, BAR_BOTTOM - barY(m.winding_c));
            const label = `${m.name}: ${motorStateLabel(m.state)}${m.tagged_out ? ", TAGGED OUT" : ""}, winding ${fmtNum(m.winding_c, 1)} °C (${ws.label}), current ${fmtNum(m.current_a, 1)} A${m.vibration_zone ? `, vibration zone ${m.vibration_zone}` : ""}`;
            return (
              <g
                key={id}
                role="button"
                tabIndex={0}
                aria-pressed={isSel}
                aria-label={label}
                onClick={onSelect ? () => onSelect(m.asset_id) : undefined}
                onKeyDown={onSelect ? keyHandler(m.asset_id) : undefined}
                style={{ cursor: onSelect ? "pointer" : undefined, outline: "none" }}
              >
                <title>{label}</title>
                {isSel ? <rect x={cx - CELL_W / 2 + 3} y={FRAME_TOP + 4} width={CELL_W - 6} height={FRAME_BOTTOM - FRAME_TOP - 8} rx={8} fill="#eff6ff" stroke="#2563eb" strokeWidth={1.5} /> : null}
                {/* motor + shaft + driven glyph */}
                <line x1={cx - 20 + 22} y1={ICON_CY} x2={cx + 20} y2={ICON_CY} stroke={LINE} strokeWidth={3} />
                <circle
                  cx={cx - 20}
                  cy={ICON_CY}
                  r={22}
                  fill={ws.fill}
                  stroke={m.state === "tripped" ? "#b91c1c" : ws.stroke}
                  strokeWidth={m.state === "tripped" ? 4 : 2.5}
                  strokeDasharray={off ? "5 3" : undefined}
                />
                <text x={cx - 20} y={ICON_CY + 7} textAnchor="middle" fontSize={20} fontWeight={700} fill={ws.text}>M</text>
                <Glyph fan={isFan} cx={cx + 24} cy={ICON_CY} color={off ? LINE : TEXT} />
                <text x={cx} y={140} textAnchor="middle" fontSize={13} fontWeight={700} fill={TEXT}>{m.asset_id.replace("_", " ")}</text>
                <rect x={cx - 38} y={146} width={76} height={18} rx={4} fill={ms.bg} />
                <text x={cx} y={159} textAnchor="middle" fontSize={11} fontWeight={700} fill={ms.color} letterSpacing={0.4}>{ms.label}</text>
                {m.tagged_out ? (
                  <g>
                    <rect x={cx - 38} y={167} width={76} height={16} rx={4} fill="#fff7ed" stroke="#ea580c" />
                    <text x={cx} y={179} textAnchor="middle" fontSize={10} fontWeight={700} fill="#9a3412">TAGGED OUT</text>
                  </g>
                ) : null}
                {/* winding temperature bar */}
                <rect x={cx - 10} y={BAR_TOP} width={20} height={BAR_BOTTOM - BAR_TOP} rx={3} fill="#ffffff" stroke={LINE} />
                <rect x={cx - 10} y={BAR_BOTTOM - fillH} width={20} height={fillH} rx={3} fill={ws.stroke} fillOpacity={0.85} />
                <line x1={cx - 17} x2={cx + 17} y1={barY(m.alarm_c)} y2={barY(m.alarm_c)} stroke="#ca8a04" strokeWidth={2} />
                <line x1={cx - 17} x2={cx + 17} y1={barY(m.limit_c)} y2={barY(m.limit_c)} stroke="#b91c1c" strokeWidth={2} strokeDasharray="4 2" />
                <text x={cx + 20} y={barY(m.alarm_c) + 3} fontSize={9} fill="#854d0e">{fmtNum(m.alarm_c, 0)}</text>
                <text x={cx + 20} y={barY(m.limit_c) + 3} fontSize={9} fill="#7f1d1d">{fmtNum(m.limit_c, 0)}</text>
                <text x={cx - 20} y={BAR_TOP + 3} textAnchor="end" fontSize={9} fill={MUTED}>170</text>
                <text x={cx - 20} y={BAR_BOTTOM + 3} textAnchor="end" fontSize={9} fill={MUTED}>0</text>
                {/* readouts */}
                <text x={cx} y={328} textAnchor="middle" fontSize={15} fontWeight={700} fill={ws.text} fontFamily="ui-monospace, monospace">{fmtNum(m.winding_c, 1)} °C</text>
                <text x={cx} y={343} textAnchor="middle" fontSize={11} fontWeight={600} fill={ws.text}>{ws.label}</text>
                <text x={cx} y={357} textAnchor="middle" fontSize={12} fill={TEXT} fontFamily="ui-monospace, monospace">{fmtNum(m.current_a, 1)} A</text>
                <text x={cx} y={370} textAnchor="middle" fontSize={10} fill={MUTED} fontFamily="ui-monospace, monospace">
                  {m.expected_current_a !== null && m.expected_current_a !== undefined ? `exp ${fmtNum(m.expected_current_a, 1)} A` : "exp —"}
                </text>
                <text x={cx} y={382} textAnchor="middle" fontSize={10} fill={MUTED}>
                  {m.vibration_zone ? `vib zone ${m.vibration_zone} · ${fmtNum(m.vibration_mm_s, 1)} mm/s` : "vib —"}
                </text>
              </g>
            );
          })}
        </g>
      ))}

      {/* legend */}
      <g fontSize={11} fill={MUTED}>
        <text x={X0} y={408}>Winding bar 0–170 °C. Tick lines: solid = alarm, dashed = limit (class-F typical, not plant-specific).</text>
        {(["normal", "approaching", "alarm", "limit"] as WindingLevel[]).map((k, i) => (
          <g key={k}>
            <rect x={560 + i * 108} y={398} width={10} height={10} rx={2} fill={WINDING_STYLE[k].fill} stroke={WINDING_STYLE[k].stroke} />
            <text x={575 + i * 108} y={407} fontSize={10}>{k === "approaching" ? "approaching" : k === "limit" ? "at/above limit" : k === "alarm" ? "above alarm" : "normal"}</text>
          </g>
        ))}
      </g>
    </svg>
  );
}
