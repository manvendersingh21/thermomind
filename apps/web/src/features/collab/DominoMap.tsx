import { useEffect, useId, useMemo, useState } from "react";
import { errorMessage } from "../../api/client";
import { SourceBadge } from "../../components/SourceBadge";
import { getDependencyGraph } from "./api";
import type { DependencyGraph, GraphEdge, GraphNode } from "./types";
import "../../plant/plant.css";
import "./collab.css";

// ---- layout constants (viewBox units) ----------------------------------------------------
const COL_W = 236;
const PAD_X = 16;
const PAD_Y = 30;
const SUB_W = 188;
const SUB_H = 44;
const MEAS_W = 168;
const MEAS_H = 28;
const MEAS_INDENT = 20;
const GROUP_GAP = 22;

interface Placed {
  node: GraphNode;
  x: number;
  y: number;
  w: number;
  h: number;
}

function layout(nodes: GraphNode[]): { placed: Map<string, Placed>; width: number; height: number; layers: number } {
  const subs = nodes.filter((n) => n.kind === "subsystem");
  const meas = nodes.filter((n) => n.kind === "measurement");
  const layers = Math.max(1, ...nodes.map((n) => n.layer + 1));
  const placed = new Map<string, Placed>();
  const used = new Set<string>();
  const cursor: number[] = Array.from({ length: layers }, () => PAD_Y);

  const belongs = (m: GraphNode, s: GraphNode): boolean => {
    const key = m.subsystem;
    if (!key) return false;
    const bare = s.id.replace(/^s:/, "");
    return key === s.id || key === bare || key === s.label;
  };

  for (const s of subs) {
    const col = s.layer;
    const x = PAD_X + col * COL_W;
    let y = cursor[col] ?? PAD_Y;
    placed.set(s.id, { node: s, x, y, w: SUB_W, h: SUB_H });
    y += SUB_H + 8;
    for (const m of meas) {
      if (!belongs(m, s) || used.has(m.id)) continue;
      used.add(m.id);
      placed.set(m.id, { node: m, x: x + MEAS_INDENT, y, w: MEAS_W, h: MEAS_H });
      y += MEAS_H + 6;
    }
    cursor[col] = y + GROUP_GAP;
  }
  // measurements whose subsystem is unknown: stack at the bottom of their layer column
  for (const m of meas) {
    if (used.has(m.id)) continue;
    const col = Math.min(Math.max(m.layer, 0), layers - 1);
    const y = cursor[col] ?? PAD_Y;
    placed.set(m.id, { node: m, x: PAD_X + col * COL_W + MEAS_INDENT, y, w: MEAS_W, h: MEAS_H });
    cursor[col] = y + MEAS_H + 6;
  }
  const height = Math.max(160, ...cursor) + 4;
  const width = PAD_X * 2 + layers * COL_W - (COL_W - SUB_W);
  return { placed, width, height, layers };
}

function edgeGeometry(a: Placed, b: Placed): { d: string; mx: number; my: number } {
  const aMidY = a.y + a.h / 2;
  const bMidY = b.y + b.h / 2;
  if (Math.abs(a.x - b.x) < COL_W / 2) {
    // same column: loop out on the right-hand side
    const ax = a.x + a.w;
    const bx = b.x + b.w;
    const off = 34;
    return {
      d: `M ${ax} ${aMidY} C ${ax + off} ${aMidY}, ${bx + off} ${bMidY}, ${bx} ${bMidY}`,
      mx: Math.max(ax, bx) + off * 0.75,
      my: (aMidY + bMidY) / 2,
    };
  }
  const forward = a.x < b.x;
  const sx = forward ? a.x + a.w : a.x;
  const tx = forward ? b.x : b.x + b.w;
  const dx = Math.max(30, Math.abs(tx - sx) / 2);
  const dir = forward ? 1 : -1;
  return {
    d: `M ${sx} ${aMidY} C ${sx + dir * dx} ${aMidY}, ${tx - dir * dx} ${bMidY}, ${tx} ${bMidY}`,
    mx: (sx + tx) / 2,
    my: (aMidY + bMidY) / 2,
  };
}

function statLabel(e: GraphEdge): string {
  if (e.r !== null && e.slope !== null) return `r=${e.r.toFixed(2)} · slope ${e.slope.toFixed(2)}`;
  if (e.r !== null) return `r=${e.r.toFixed(2)}`;
  return e.label;
}

function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

function fmtMwh(v: number | null): string {
  return v === null ? "n/a" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}`;
}

interface Props {
  caseId?: string;
  measurement?: string;
  delta?: number;
}

export function DominoMap({ caseId, measurement, delta }: Props) {
  const uid = useId().replace(/:/g, "");
  const [meas, setMeas] = useState<string>(measurement ?? "");
  const [deltaTxt, setDeltaTxt] = useState<string>(delta !== undefined ? String(delta) : "");
  const [applied, setApplied] = useState<{ m: string; d: number | undefined }>({ m: measurement ?? "", d: delta });
  const [graph, setGraph] = useState<DependencyGraph | null>(null);
  const [options, setOptions] = useState<GraphNode[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  // follow prop changes (e.g. the what-if console driving this map)
  useEffect(() => {
    setMeas(measurement ?? "");
    setDeltaTxt(delta !== undefined ? String(delta) : "");
    setApplied({ m: measurement ?? "", d: delta });
  }, [measurement, delta]);

  useEffect(() => {
    const c = new AbortController();
    setLoading(true);
    setError(null);
    getDependencyGraph(
      { caseId, measurement: applied.m || undefined, delta: applied.m ? applied.d : undefined },
      c.signal,
    )
      .then((g) => {
        setGraph(g);
        setOptions((prev) => (prev.length ? prev : g.nodes.filter((n) => n.kind === "measurement")));
        setLoading(false);
      })
      .catch((e) => {
        if (c.signal.aborted) return;
        setError(errorMessage(e));
        setLoading(false);
      });
    return () => c.abort();
  }, [caseId, applied.m, applied.d]);

  const geo = useMemo(() => (graph ? layout(graph.nodes) : null), [graph]);
  const byId = useMemo(() => new Map((graph?.nodes ?? []).map((n) => [n.id, n])), [graph]);
  const pathIndex = useMemo(() => new Map((graph?.domino_path ?? []).map((id, i) => [id, i + 1])), [graph]);
  const implicatedId = graph?.nodes.find((n) => n.implicated)?.id ?? null;
  const selNode = selected ? (byId.get(selected) ?? null) : null;

  const applyPicker = () => {
    const d = deltaTxt.trim() === "" ? undefined : Number(deltaTxt);
    if (meas && (d === undefined || Number.isNaN(d))) {
      setError("Enter a numeric change (delta) for the chosen measurement.");
      return;
    }
    setApplied({ m: meas, d });
  };

  const visibleEdges = useMemo(() => {
    if (!graph) return [] as GraphEdge[];
    return graph.edges.filter((e) => {
      if (e.kind === "membership") return false;
      if (e.kind === "physical") return true;
      if (showAll) return true;
      const focus = [implicatedId, selected].filter(Boolean) as string[];
      return focus.includes(e.source) || focus.includes(e.target) || e.on_path;
    });
  }, [graph, showAll, implicatedId, selected]);

  const colTitles = ["Air in", "Compression", "Combustion", "Expansion and exhaust"];

  return (
    <section className="cb-root cb-section" aria-label="Domino effect map">
      <div className="cb-row" style={{ justifyContent: "space-between" }}>
        <h2 className="cb-h2">Domino effect map — how one issue can ripple through the plant</h2>
        <span className="cb-row">
          <SourceBadge variant="model" size="sm" label="MODEL-DERIVED ASSOCIATIONS" />
          {graph?.synthetic ? <SourceBadge variant="synthetic" size="sm" /> : null}
        </span>
      </div>
      <p className="cb-muted cb-small" style={{ margin: "0 0 8px" }}>
        Solid arrows are the physical gas-path order. Dashed lines are statistical associations learned from{" "}
        {graph ? `years ${graph.training_years.join(", ")}` : "the training years"}. Read-only: this map explains, it
        does not operate anything.
      </p>

      <form
        className="cb-row"
        style={{ marginBottom: 10 }}
        onSubmit={(e) => {
          e.preventDefault();
          applyPicker();
        }}
        aria-label="Optional what-if on the map"
      >
        <label className="cb-row cb-small">
          <span>What-if on</span>
          <select className="cb-input" value={meas} onChange={(e) => setMeas(e.target.value)} aria-label="Measurement for what-if">
            <option value="">(none)</option>
            {options.map((o) => (
              <option key={o.id} value={o.label}>
                {o.label}
                {o.unit ? ` (${o.unit})` : ""}
              </option>
            ))}
          </select>
        </label>
        <label className="cb-row cb-small">
          <span>change by</span>
          <input
            className="cb-input"
            style={{ width: 90 }}
            type="number"
            step="any"
            value={deltaTxt}
            onChange={(e) => setDeltaTxt(e.target.value)}
            disabled={!meas}
            aria-label="Change (delta) in the measurement's own unit"
          />
        </label>
        <button type="submit" className="cb-btn cb-btn-sm">
          Show on map
        </button>
        <label className="cb-row cb-small" style={{ marginLeft: "auto" }}>
          <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
          <span>Show all associations</span>
        </label>
      </form>

      {loading && !graph ? <div className="cb-muted" role="status">Loading dependency map…</div> : null}
      {error ? (
        <div className="pl-alert pl-alert-err" role="alert">
          {error}
        </div>
      ) : null}

      {graph && geo ? (
        <>
          {graph.implicated ? (
            <div className="pl-alert pl-alert-warn" style={{ marginBottom: 8 }}>
              <strong>Implicated: {graph.implicated.measurement}</strong> in {graph.implicated.subsystem}. {graph.implicated.reason}
            </div>
          ) : (
            <div className="cb-muted cb-small" style={{ marginBottom: 8 }}>
              No case or what-if selected, so nothing is implicated. Pick a case or a measurement to see a domino path.
            </div>
          )}

          {graph.whatif ? (
            <div className="pl-card pl-card-yellow" style={{ marginBottom: 8 }} aria-label="What-if effect on TEY">
              <div className="cb-row">
                <span className="cb-tag cb-tag-amber">MODEL-DERIVED</span>
                <strong>
                  Expected ΔTEY (MODEL-DERIVED):{" "}
                  {graph.whatif.applicable
                    ? `mean ${fmtMwh(graph.whatif.delta_tey_mean)} MWh (min ${fmtMwh(graph.whatif.delta_tey_min)}, max ${fmtMwh(graph.whatif.delta_tey_max)})`
                    : "not applicable"}
                </strong>
              </div>
              <div className="cb-small">
                {graph.whatif.measurement} {graph.whatif.delta > 0 ? "+" : ""}
                {graph.whatif.delta} {graph.whatif.unit}.{" "}
                {graph.whatif.ood_flag ? (
                  <strong>Out-of-distribution: outside the range the model saw in training, treat with extra caution. </strong>
                ) : graph.whatif.ood_flag === false ? (
                  "Within the training range. "
                ) : null}
                {graph.whatif.note}
              </div>
              <div className="cb-small cb-muted">{graph.whatif.label}</div>
            </div>
          ) : null}

          <div className={`cb-map-layout ${selNode ? "cb-has-panel" : ""}`}>
            <div>
              <div className="cb-svg-wrap">
                <svg
                  className="cb-svg"
                  viewBox={`0 0 ${geo.width} ${geo.height}`}
                  role="group"
                  aria-label="Dependency map of plant subsystems and measurements, left to right"
                >
                  <defs>
                    <marker id={`${uid}-ar`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                      <path d="M 0 0 L 10 5 L 0 10 z" fill="#5b6776" />
                    </marker>
                    <marker id={`${uid}-ap`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                      <path d="M 0 0 L 10 5 L 0 10 z" fill="#d98a00" />
                    </marker>
                  </defs>

                  {Array.from({ length: geo.layers }, (_, i) => (
                    <text key={i} x={PAD_X + i * COL_W} y={16} fontSize={12} fontWeight={700} fill="#5b6776">
                      {colTitles[i] ?? `Stage ${i + 1}`}
                    </text>
                  ))}

                  {/* statistical edges first (underneath) */}
                  {visibleEdges
                    .filter((e) => e.kind === "statistical")
                    .map((e, i) => {
                      const a = geo.placed.get(e.source);
                      const b = geo.placed.get(e.target);
                      if (!a || !b) return null;
                      const g = edgeGeometry(a, b);
                      return (
                        <g key={`s${i}`}>
                          <path d={g.d} fill="none" stroke={e.on_path ? "#d98a00" : "#7a8696"} strokeWidth={1.2} strokeDasharray="5 4" />
                          <text
                            x={g.mx}
                            y={g.my - 3}
                            textAnchor="middle"
                            fontSize={10}
                            fill="#3c4756"
                            stroke="#fbfcfd"
                            strokeWidth={3}
                            paintOrder="stroke"
                          >
                            {statLabel(e)}
                          </text>
                        </g>
                      );
                    })}

                  {/* physical edges */}
                  {visibleEdges
                    .filter((e) => e.kind === "physical")
                    .map((e, i) => {
                      const a = geo.placed.get(e.source);
                      const b = geo.placed.get(e.target);
                      if (!a || !b) return null;
                      const g = edgeGeometry(a, b);
                      return (
                        <path
                          key={`p${i}`}
                          d={g.d}
                          fill="none"
                          stroke={e.on_path ? "#d98a00" : "#5b6776"}
                          strokeWidth={e.on_path ? 4 : 1.8}
                          markerEnd={`url(#${uid}-${e.on_path ? "ap" : "ar"})`}
                        />
                      );
                    })}

                  {/* nodes */}
                  {Array.from(geo.placed.values()).map((p) => {
                    const n = p.node;
                    const step = pathIndex.get(n.id);
                    const isSel = selected === n.id;
                    const cls = [
                      "cb-node",
                      n.kind === "subsystem" ? "cb-sub" : "cb-meas",
                      n.on_path ? "cb-onpath" : "",
                      isSel ? "cb-selected" : "",
                    ].join(" ");
                    const label = n.kind === "subsystem" ? n.label : `${n.label}${n.unit ? ` (${n.unit})` : ""}`;
                    return (
                      <g
                        key={n.id}
                        className={cls}
                        role="button"
                        tabIndex={0}
                        aria-pressed={isSel}
                        aria-label={`${n.kind} ${n.label}${n.implicated ? ", implicated" : ""}${step ? `, domino path step ${step}` : ""}${n.stat_neighbour ? ", statistically associated with the implicated measurement" : ""}. Press Enter for details.`}
                        onClick={() => setSelected(isSel ? null : n.id)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            setSelected(isSel ? null : n.id);
                          }
                        }}
                      >
                        <rect className="cb-box" x={p.x} y={p.y} width={p.w} height={p.h} rx={n.kind === "subsystem" ? 10 : 14} />
                        {n.implicated ? (
                          <rect className="cb-pulse" x={p.x - 4} y={p.y - 4} width={p.w + 8} height={p.h + 8} rx={n.kind === "subsystem" ? 13 : 17} />
                        ) : null}
                        <text
                          x={p.x + 10}
                          y={p.y + (n.kind === "subsystem" ? 19 : 18)}
                          fontSize={n.kind === "subsystem" ? 13 : 11.5}
                          fontWeight={n.kind === "subsystem" ? 700 : 500}
                        >
                          {truncate(label, n.kind === "subsystem" ? 24 : 24)}
                        </text>
                        {n.kind === "subsystem" && n.owner_label ? (
                          <text x={p.x + 10} y={p.y + 35} fontSize={10} fill="#5b6776" style={{ fill: "#5b6776" }}>
                            {truncate(n.owner_label, 30)}
                          </text>
                        ) : null}
                        {n.implicated ? (
                          <text x={p.x + p.w - 8} y={p.y + 14} fontSize={9.5} fontWeight={700} textAnchor="end" style={{ fill: "#6b5300" }}>
                            IMPLICATED
                          </text>
                        ) : n.stat_neighbour ? (
                          <text x={p.x + p.w - 8} y={p.y + 14} fontSize={9} textAnchor="end" style={{ fill: "#5b6776" }}>
                            associated
                          </text>
                        ) : null}
                        {step ? (
                          <g>
                            <circle cx={p.x} cy={p.y} r={9} fill="#1b2430" />
                            <text x={p.x} y={p.y + 4} fontSize={11} fontWeight={700} textAnchor="middle" style={{ fill: "#fff" }}>
                              {step}
                            </text>
                          </g>
                        ) : null}
                      </g>
                    );
                  })}
                </svg>
              </div>

              <div className="cb-legend" aria-label="Legend">
                <span>
                  <svg width="30" height="10" aria-hidden="true"><line x1="0" y1="5" x2="30" y2="5" stroke="#5b6776" strokeWidth="2" /></svg>
                  Physical gas-path order
                </span>
                <span>
                  <svg width="30" height="10" aria-hidden="true"><line x1="0" y1="5" x2="30" y2="5" stroke="#7a8696" strokeWidth="1.5" strokeDasharray="5 4" /></svg>
                  Statistical association (r, slope)
                </span>
                <span>
                  <svg width="30" height="10" aria-hidden="true"><line x1="0" y1="5" x2="30" y2="5" stroke="#d98a00" strokeWidth="4" /></svg>
                  Domino path (numbered)
                </span>
                <span>
                  <svg width="22" height="14" aria-hidden="true"><rect x="2" y="2" width="18" height="10" rx="3" fill="none" stroke="#f5c518" strokeWidth="3" /></svg>
                  Implicated (labelled IMPLICATED)
                </span>
              </div>

              {graph.domino_path.length ? (
                <div>
                  <strong>Domino path:</strong>
                  <ol className="cb-path-list" aria-label="Domino path in order">
                    {graph.domino_path.map((id, i) => (
                      <li key={`${id}-${i}`}>
                        {i > 0 ? <span aria-hidden="true">→</span> : null}
                        <span className="cb-step" aria-hidden="true">{i + 1}</span>
                        <span>{byId.get(id)?.label ?? id}</span>
                      </li>
                    ))}
                  </ol>
                </div>
              ) : null}

              <p className="cb-small" style={{ margin: "8px 0 0" }}>
                <strong>Caveat: </strong>
                {graph.caveat}
              </p>
              <p className="cb-small cb-muted" style={{ margin: "2px 0 0" }}>
                Association threshold |r| ≥ {graph.threshold}. Click a node, or focus it and press Enter, to see who owns it and what to check.
              </p>
            </div>

            {selNode ? (
              <aside className="cb-panel" aria-label={`Details for ${selNode.label}`}>
                <div className="cb-row" style={{ justifyContent: "space-between" }}>
                  <h3 className="cb-h3" style={{ margin: 0 }}>
                    {selNode.label}
                    {selNode.unit ? <span className="cb-muted"> ({selNode.unit})</span> : null}
                  </h3>
                  <button type="button" className="cb-btn cb-btn-sm" onClick={() => setSelected(null)} aria-label="Close details">
                    Close
                  </button>
                </div>
                <div className="cb-small cb-muted">{selNode.kind === "subsystem" ? "Subsystem" : `Measurement in ${selNode.subsystem ?? "unknown subsystem"}`}</div>
                {selNode.description ? <p className="cb-small">{selNode.description}</p> : null}
                {selNode.how_it_works ? (
                  <>
                    <h4 className="cb-h3">How it works</h4>
                    <p className="cb-small" style={{ margin: 0 }}>{selNode.how_it_works}</p>
                  </>
                ) : null}
                <h4 className="cb-h3">Responsible</h4>
                <p className="cb-small" style={{ margin: 0 }}>
                  {selNode.owner_label ?? "No owner recorded"}
                  {selNode.owner_persona ? <span className="cb-muted"> ({selNode.owner_persona})</span> : null}
                </p>
                {selNode.what_to_check.length ? (
                  <>
                    <h4 className="cb-h3">What to check</h4>
                    <ul className="cb-small" style={{ margin: 0, paddingLeft: 18 }}>
                      {selNode.what_to_check.map((w, i) => (
                        <li key={i}>{w}</li>
                      ))}
                    </ul>
                  </>
                ) : null}
              </aside>
            ) : null}
          </div>
        </>
      ) : null}
    </section>
  );
}

export default DominoMap;
