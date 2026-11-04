import raw from "../../../../contracts/examples/investigation.json";
import type { AgentEvent, DiagnosticReport, Evidence } from "../api/types";

/** Illustrative example from contracts/examples (placeholder values, not a real run). */
const inv = raw as unknown as {
  report: DiagnosticReport;
  evidence: Evidence[];
  events: AgentEvent[];
};

export const report: DiagnosticReport = inv.report;
export const evidence: Evidence[] = inv.evidence;
export const events: AgentEvent[] = inv.events;
export const evidenceById = new Map(evidence.map((e) => [e.evidence_id, e]));
