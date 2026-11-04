import { fmtNum } from "../../lib/format";
import type { AssetId, AssetState, AssetStatus } from "./types";

/** Status colors (reserved for state; always paired with a text label, never color alone). */
export const STATE_STYLE: Record<AssetState, { stroke: string; fill: string; text: string; label: string }> = {
  normal: { stroke: "#16a34a", fill: "#dcfce7", text: "#166534", label: "NORMAL" },
  approaching: { stroke: "#ca8a04", fill: "#fef9c3", text: "#854d0e", label: "APPROACHING ALARM" },
  alarm: { stroke: "#dc2626", fill: "#fee2e2", text: "#991b1b", label: "ABOVE ALARM" },
  limit: { stroke: "#b91c1c", fill: "#fecaca", text: "#7f1d1d", label: "AT/ABOVE LIMIT" },
};

const LINE = "#64748b";
const TEXT = "#334155";
const MUTED = "#64748b";
const Y = 92; // one-line conductor height

const X: Record<AssetId | "GRID", number> = { GEN: 80, GCB: 255, GSU: 440, HVSG: 625, BUS: 790, GRID: 930 };

interface Props {
  status: AssetStatus[];
  /** Asset carrying the SYNTHETIC hot-connection defect (pulses yellow, SYNTHETIC badge). */
  syntheticAssetId?: AssetId | null;
  /** True when the map shows the what-if demand scenario instead of the baseline feed. */
  whatIf?: boolean;
  selected?: AssetId | null;
  onSelect?: (id: AssetId) => void;
}

function Symbol({ id, s }: { id: AssetId; s: (typeof STATE_STYLE)[AssetState] }) {
  const x = X[id];
  const common = { stroke: s.stroke, strokeWidth: 2.5, fill: s.fill };
  switch (id) {
    case "GEN":
      return (
        <g>
          <circle cx={x} cy={Y} r={28} {...common} />
          <text x={x} y={Y + 7} textAnchor="middle" fontSize={22} fontWeight={700} fill={s.text}>G</text>
        </g>
      );
    case "GSU":
      return (
        <g>
          <circle cx={x - 13} cy={Y} r={24} {...common} />
          <circle cx={x + 13} cy={Y} r={24} {...common} fillOpacity={0.6} />
        </g>
      );
    case "GCB":
    case "HVSG":
      return (
        <g>
          <rect x={x - 20} y={Y - 20} width={40} height={40} rx={4} {...common} />
          <line x1={x - 12} y1={Y + 12} x2={x + 12} y2={Y - 12} stroke={s.stroke} strokeWidth={2.5} />
        </g>
      );
    case "BUS":
      return <rect x={x - 6} y={Y - 42} width={12} height={84} rx={3} {...common} />;
  }
}

export function ThermalMap({ status, syntheticAssetId, whatIf, selected, onSelect }: Props) {
  const byId = new Map(status.map((s) => [s.asset_id, s]));
  const order: AssetId[] = ["GEN", "GCB", "GSU", "HVSG", "BUS"];
  return (
    <div className="overflow-x-auto">
      <svg
        viewBox="0 0 1000 250"
        className="w-full min-w-[640px]"
        role="img"
        aria-label={`One-line diagram, ${whatIf ? "what-if demand scenario" : "baseline"} simulated temperatures`}
      >
        <style>{`@keyframes tm-hot { 0%,100% { stroke-opacity: .25; } 50% { stroke-opacity: 1; } } .tm-hot { animation: tm-hot 1.4s ease-in-out infinite; }`}</style>
        {/* conductors */}
        <line x1={X.GEN + 28} y1={Y} x2={X.BUS - 6} y2={Y} stroke={LINE} strokeWidth={3} />
        <line x1={X.BUS + 6} y1={Y} x2={X.GRID - 26} y2={Y} stroke={LINE} strokeWidth={3} />
        {/* grid */}
        <g>
          <path d={`M ${X.GRID - 26} ${Y - 18} L ${X.GRID + 4} ${Y} L ${X.GRID - 26} ${Y + 18} Z`} fill="#dbeafe" stroke="#2563eb" strokeWidth={2} />
          <text x={X.GRID + 10} y={Y + 5} fontSize={14} fontWeight={600} fill={TEXT}>Grid</text>
        </g>
        {order.map((id) => {
          const st = byId.get(id);
          if (!st) return null;
          const s = STATE_STYLE[st.state];
          const synthetic = syntheticAssetId === id;
          const x = X[id];
          const isSel = selected === id;
          return (
            <g
              key={id}
              onClick={onSelect ? () => onSelect(id) : undefined}
              style={{ cursor: onSelect ? "pointer" : undefined }}
              role={onSelect ? "button" : undefined}
              aria-label={`${st.name}: ${fmtNum(st.current_c, 1)} °C, ${s.label}`}
            >
              <title>{`${st.name} — ${fmtNum(st.current_c, 1)} °C, margin to alarm ${fmtNum(st.margin_to_alarm_k, 1)} K (simulated)`}</title>
              {isSel ? <rect x={x - 66} y={Y - 80} width={132} height={216} rx={10} fill="#eff6ff" stroke="#93c5fd" /> : null}
              {synthetic ? (
                <rect className="tm-hot" x={x - 40} y={Y - 50} width={80} height={100} rx={10} fill="none" stroke="#ca8a04" strokeWidth={3} strokeDasharray="6 4" />
              ) : null}
              <Symbol id={id} s={s} />
              <text x={x} y={Y - 62} textAnchor="middle" fontSize={13} fontWeight={600} fill={TEXT}>{st.name}</text>
              <text x={x} y={Y + 70} textAnchor="middle" fontSize={20} fontWeight={700} fill={TEXT} fontFamily="ui-monospace, monospace">
                {fmtNum(st.current_c, 1)} °C
              </text>
              <text x={x} y={Y + 89} textAnchor="middle" fontSize={12} fill={MUTED}>
                {st.margin_to_alarm_k >= 0 ? `${fmtNum(st.margin_to_alarm_k, 1)} K to alarm` : `${fmtNum(-st.margin_to_alarm_k, 1)} K over alarm`}
              </text>
              <text x={x} y={Y + 106} textAnchor="middle" fontSize={11} fontWeight={700} fill={s.text}>{s.label}</text>
              {synthetic ? (
                <g>
                  <rect x={x - 38} y={Y + 113} width={76} height={18} rx={4} fill="#fef9c3" stroke="#ca8a04" />
                  <text x={x} y={Y + 126} textAnchor="middle" fontSize={11} fontWeight={700} fill="#854d0e">SYNTHETIC</text>
                </g>
              ) : null}
            </g>
          );
        })}
        <text x={10} y={244} fontSize={12} fill={MUTED}>
          {whatIf ? "WHAT-IF demand scenario · " : ""}simulated temperatures at the last sample of the window · not a measurement
        </text>
      </svg>
    </div>
  );
}

export default ThermalMap;
