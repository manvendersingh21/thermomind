/** Pure helpers for the case comparison page. Every statement produced here is derived from stored data. */
import type { DataQualityReport, Evidence, Hypothesis, Investigation } from "../../api/types";
import { fmtNum } from "../../lib/format";
import type {
  DataQualityRow,
  EvidenceDiff,
  HypothesisCell,
  HypothesisDiffRow,
  SharedEvidenceRow,
  ToolCallSummary,
  ZBand,
} from "./types";

// --- default selection ------------------------------------------------------

function byNewest(list: Investigation[]): Investigation[] {
  return [...list].sort((x, y) => (x.created_at_utc < y.created_at_utc ? 1 : x.created_at_utc > y.created_at_utc ? -1 : 0));
}

function newestWhere(sorted: Investigation[], pred: (i: Investigation) => boolean): Investigation | undefined {
  return sorted.find(pred);
}

/** Newest S02 meta_live vs newest S03 meta_live; else S02 vs S03 in any mode; else the two newest cases. */
export function pickDefaults(list: Investigation[]): { a: string | null; b: string | null } {
  const sorted = byNewest(list);
  const isS = (p: string) => (i: Investigation) => i.scenario.scenario_id.startsWith(p);
  const live = (i: Investigation) => i.mode === "meta_live";
  const a1 = newestWhere(sorted, (i) => isS("S02")(i) && live(i));
  const b1 = newestWhere(sorted, (i) => isS("S03")(i) && live(i));
  if (a1 && b1) return { a: a1.case_id, b: b1.case_id };
  const a2 = newestWhere(sorted, isS("S02"));
  const b2 = newestWhere(sorted, isS("S03"));
  if (a2 && b2) return { a: a2.case_id, b: b2.case_id };
  return { a: sorted[0]?.case_id ?? null, b: sorted[1]?.case_id ?? null };
}

export function caseOptionLabel(i: Investigation): string {
  const mode = i.mode === "meta_live" ? "meta live" : "offline preview";
  return `${i.case_id} · ${i.scenario.scenario_id} · ${mode} · ${i.status.replace(/_/g, " ")}`;
}

// --- hypotheses -------------------------------------------------------------

function slug(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
}

function hypKey(h: Hypothesis): string {
  return h.key ?? slug(h.name);
}

function cell(h: Hypothesis | undefined): HypothesisCell | null {
  if (!h) return null;
  return { rank: h.rank, status: h.status, supporting: h.supporting_evidence_ids.length, contradicting: h.contradicting_evidence_ids.length };
}

export function diffHypotheses(a: Investigation, b: Investigation): HypothesisDiffRow[] {
  const ha = new Map((a.report?.hypotheses ?? []).map((h) => [hypKey(h), h] as const));
  const hb = new Map((b.report?.hypotheses ?? []).map((h) => [hypKey(h), h] as const));
  const keys = Array.from(new Set([...ha.keys(), ...hb.keys()]));
  const rows: HypothesisDiffRow[] = keys.map((key) => {
    const x = ha.get(key);
    const y = hb.get(key);
    const ca = cell(x);
    const cb = cell(y);
    const differs = !ca || !cb || ca.rank !== cb.rank || ca.status !== cb.status;
    return { key, name: x?.name ?? y?.name ?? key, a: ca, b: cb, differs };
  });
  const best = (r: HypothesisDiffRow) => Math.min(r.a?.rank ?? 99, r.b?.rank ?? 99);
  return rows.sort((p, q) => best(p) - best(q));
}

export function topHypothesis(inv: Investigation): Hypothesis | null {
  const hs = inv.report?.hypotheses ?? [];
  if (hs.length === 0) return null;
  return [...hs].sort((p, q) => p.rank - q.rank)[0];
}

// --- evidence ---------------------------------------------------------------

export function zBand(delta: number | null): ZBand {
  if (delta === null) return "none";
  const d = Math.abs(delta);
  if (d < 0.5) return "small";
  if (d < 2) return "moderate";
  return "large";
}

export function diffEvidence(a: Investigation, b: Investigation): EvidenceDiff {
  const ea = new Map(a.evidence.map((e) => [e.evidence_id, e] as const));
  const eb = new Map(b.evidence.map((e) => [e.evidence_id, e] as const));
  const shared: SharedEvidenceRow[] = [];
  const onlyA: Evidence[] = [];
  const onlyB: Evidence[] = [];
  for (const [id, x] of ea) {
    const y = eb.get(id);
    if (!y) {
      onlyA.push(x);
      continue;
    }
    const zDelta = x.z_score !== null && y.z_score !== null ? y.z_score - x.z_score : null;
    shared.push({ id, metric: x.metric, unit: x.unit, title: x.title, a: x, b: y, zDelta, band: zBand(zDelta) });
  }
  for (const [id, y] of eb) if (!ea.has(id)) onlyB.push(y);
  shared.sort((p, q) => Math.abs(q.zDelta ?? -1) - Math.abs(p.zDelta ?? -1));
  return { shared, onlyA, onlyB };
}

// --- agent events -----------------------------------------------------------

export function summarizeToolCalls(inv: Investigation): ToolCallSummary {
  const calls = inv.events.filter((e) => e.kind === "tool_call");
  const sequence = calls.map((e) => ({ seq: e.seq, tool: e.tool_name ?? "(unnamed)", ok: e.ok }));
  const m = new Map<string, { count: number; failed: number }>();
  for (const s of sequence) {
    const c = m.get(s.tool) ?? { count: 0, failed: 0 };
    c.count += 1;
    if (!s.ok) c.failed += 1;
    m.set(s.tool, c);
  }
  const counts = Array.from(m, ([tool, v]) => ({ tool, ...v })).sort((p, q) => q.count - p.count || p.tool.localeCompare(q.tool));
  return { sequence, counts, total: sequence.length, failed: sequence.filter((s) => !s.ok).length };
}

// --- data quality -----------------------------------------------------------

function nonZero(rec: Record<string, number>): string[] {
  return Object.entries(rec)
    .filter(([, v]) => v > 0)
    .map(([k, v]) => `${k}: ${v}`);
}

function sameSet(x: string[], y: string[]): boolean {
  if (x.length !== y.length) return false;
  const s = new Set(x);
  return y.every((v) => s.has(v));
}

export function dataQualityRows(a: DataQualityReport | null, b: DataQualityReport | null): DataQualityRow[] {
  const mk = (label: string, fa: (d: DataQualityReport) => string[]): DataQualityRow => {
    const xa = a ? fa(a) : [];
    const xb = b ? fa(b) : [];
    return { label, a: xa, b: xb, differs: !sameSet(xa, xb) };
  };
  return [
    mk("Scenario label", (d) => [d.scenario_label.replace(/_/g, " ")]),
    mk("Missing values (count per measure)", (d) => nonZero(d.missing_values)),
    mk("Out of training range (count per measure)", (d) => nonZero(d.out_of_training_range)),
    mk("Sensor consistency flags", (d) => d.sensor_consistency_flags),
    mk("Synthetic measurements", (d) => d.synthetic_measurements),
    mk("Notes", (d) => d.notes),
  ];
}

// --- auto summary -----------------------------------------------------------

function clean(s: string): string {
  return s.replace(/_/g, " ");
}

function topLine(side: "A" | "B", inv: Investigation): string {
  const t = topHypothesis(inv);
  if (!t) return `case ${side} has no report hypotheses (status ${clean(inv.status)})`;
  return `case ${side} ranks ${t.name.toLowerCase()} #${t.rank} (${clean(t.status)})`;
}

/** Plain-English bullets; each states only values present in the two stored investigations. */
export function buildSummary(a: Investigation, b: Investigation): string[] {
  const out: string[] = [];
  const ta = topHypothesis(a);
  const tb = topHypothesis(b);
  if (ta && tb && hypKey(ta) === hypKey(tb)) {
    out.push(`Both cases rank ${ta.name.toLowerCase()} #1 (A: ${clean(ta.status)}, B: ${clean(tb.status)}).`);
  } else {
    const l1 = topLine("A", a);
    const l2 = topLine("B", b);
    out.push(`${l1.charAt(0).toUpperCase()}${l1.slice(1)}; ${l2}.`);
  }

  const hd = diffHypotheses(a, b).filter((r) => r.differs);
  if (hd.length > 0) {
    out.push(`${hd.length} hypothes${hd.length === 1 ? "is differs" : "es differ"} in rank or status: ${hd.map((r) => r.name).join(", ")}.`);
  } else if ((a.report?.hypotheses.length ?? 0) > 0 && (b.report?.hypotheses.length ?? 0) > 0) {
    out.push("All hypotheses have the same rank and status in both cases.");
  }

  const sa = a.report?.severity;
  const sb = b.report?.severity;
  if (sa && sb) {
    out.push(sa === sb ? `Both reports carry severity "${clean(sa)}".` : `Severity differs: A "${clean(sa)}", B "${clean(sb)}".`);
  }

  const ev = diffEvidence(a, b);
  const withDelta = ev.shared.filter((r) => r.zDelta !== null);
  const top = withDelta.slice(0, 3).filter((r) => Math.abs(r.zDelta ?? 0) >= 0.05);
  if (top.length > 0) {
    out.push(
      `Evidence z-scores that differ most between cases: ${top
        .map((r) => `${r.metric} z differs by ${fmtNum(Math.abs(r.zDelta ?? 0), 1)} (A ${fmtNum(r.a.z_score, 1)}, B ${fmtNum(r.b.z_score, 1)}; ${r.id})`)
        .join("; ")}.`,
    );
  }
  out.push(
    `${ev.shared.length} evidence id${ev.shared.length === 1 ? " appears" : "s appear"} in both cases; ${ev.onlyA.length} only in A, ${ev.onlyB.length} only in B.`,
  );

  const dq = dataQualityRows(a.data_quality, b.data_quality).filter((r) => r.differs && r.label !== "Notes");
  if (dq.length > 0) out.push(`Data-quality entries differ for: ${dq.map((r) => r.label.toLowerCase()).join(", ")}.`);

  const ca = summarizeToolCalls(a);
  const cb = summarizeToolCalls(b);
  out.push(`Tool calls recorded: A ${ca.total} (${ca.counts.length} distinct), B ${cb.total} (${cb.counts.length} distinct).`);

  const sy = (i: Investigation) => (i.scenario_label === "synthetic_overlay" ? "synthetic overlay" : "real data only");
  out.push(`Case A uses ${a.scenario.scenario_id} (${sy(a)}); case B uses ${b.scenario.scenario_id} (${sy(b)}).`);
  return out;
}
