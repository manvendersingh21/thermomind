import { describe, expect, it } from "vitest";
import type { Evidence, Hypothesis, Investigation } from "../../../api/types";
import type { ThermalEvaluateResponse } from "../../thermal/types";
import { fillLive } from "../data";
import { EQUIPMENT, EQUIPMENT_BY_ID, FLOW_PATHS } from "../layout";
import { locateCase } from "../locate";
import { emptyLive } from "../types";

function hyp(key: string, status: Hypothesis["status"], rank = 1): Hypothesis {
  return {
    name: key.replace(/_/g, " "),
    key,
    rank,
    supporting_evidence_ids: ["ev_a"],
    contradicting_evidence_ids: [],
    limitations: [],
    status,
    rationale: null,
    what_would_change_assessment: null,
  };
}

function ev(metric: string, delta: number, synthetic: boolean): Evidence {
  return { evidence_id: `ev_${metric}`, metric, delta, is_synthetic: synthetic } as unknown as Evidence;
}

function inv(opts: { key: string; status?: Hypothesis["status"]; synthetic?: boolean; severity?: string; evidence?: Evidence[]; affected?: string[] }): Investigation {
  return {
    case_id: "case_test",
    scenario_label: opts.synthetic ? "synthetic_overlay" : "real_only",
    scenario: { scenario_id: "S", title: "t", affected_measurements: opts.affected ?? [] },
    evidence: opts.evidence ?? [],
    report: { severity: opts.severity ?? "review", hypotheses: [hyp(opts.key, opts.status ?? "possible")], engineer_review_checks: [] },
  } as unknown as Investigation;
}

describe("twin locateCase", () => {
  it("pins an intake restriction to the filter house with a synthetic label and rings", () => {
    const loc = locateCase(
      inv({ key: "intake_restriction", synthetic: true, evidence: [ev("AFDP", 1.2, true)], affected: ["AFDP", "TEY", "CDP"] }),
      null,
      null,
      ["AFDP", "TEY", "CDP"],
    );
    expect(loc.located).toBe(true);
    expect(loc.primary).toBe("filter_house");
    expect(loc.hotspots[0].label).toBe("LOOK HERE — Intake filter house · AFDP ↑ synthetic overlay");
    expect(loc.rings).toEqual(expect.arrayContaining(["filter_house", "generator", "compressor"]));
    expect(loc.checks[loc.checks.length - 1]).toMatch(/issues no control actions/);
  });

  it("maps sensor_issue to the CDP transmitter and operating_condition to the ambient station", () => {
    expect(locateCase(inv({ key: "sensor_issue" }), null, null, []).primary).toBe("cdp_tx");
    expect(locateCase(inv({ key: "operating_condition", status: "inconclusive" }), null, null, []).hotspots[0].label).toMatch(/^CANDIDATE \(unconfirmed\) — Ambient station/);
  });

  it("says nothing to locate for a real-only case without a notable deviation", () => {
    const loc = locateCase(inv({ key: "unknown", severity: "informational" }), null, null, []);
    expect(loc.located).toBe(false);
    expect(loc.nothingMessage).toBe("No notable deviation — nothing to locate");
    expect(loc.hotspots).toHaveLength(0);
    expect(loc.rings).toHaveLength(0);
  });

  it("locates the hottest flagged electrical asset and lists breakers as SIMULATED, information only", () => {
    const thermal = {
      synthetic: true,
      synthetic_defect: { asset_id: "HVSG" },
      flags: [{ asset_id: "HVSG", flag: "hot_connection_pattern", severity: "warning", message: "HV switchgear rising faster than peers" }],
      status: [
        { asset_id: "GSU", name: "Step-up transformer", margin_to_alarm_k: 30, peak_c: 80, alarm_c: 110 },
        { asset_id: "HVSG", name: "HV switchgear", margin_to_alarm_k: 2, peak_c: 93, alarm_c: 95 },
      ],
    } as unknown as ThermalEvaluateResponse;
    const loc = locateCase(inv({ key: "unknown", severity: "informational" }), thermal, null, []);
    expect(loc.hotspots[0].equipment).toBe("hv_switchgear");
    expect(loc.hotspots[0].label).toMatch(/SIMULATED/);
    const names = loc.involved.map((i) => i.name);
    expect(names).toEqual(expect.arrayContaining(["Generator breaker 52G", "HV breaker 52H"]));
    expect(loc.involved.find((i) => i.name === "HV breaker 52H")?.note).toMatch(/SIMULATED.*this software issues no commands/);
    expect(loc.rings).toContain("hv_switchgear");
  });
});

describe("twin layout + live binding", () => {
  it("has unique equipment ids and flow paths with ≥2 points", () => {
    expect(new Set(EQUIPMENT.map((e) => e.id)).size).toBe(EQUIPMENT.length);
    expect(EQUIPMENT_BY_ID.breaker_52g.description).toMatch(/no commands/);
    for (const p of FLOW_PATHS) expect(p.points.length).toBeGreaterThanOrEqual(2);
  });

  it("normalises drivers into 0..1 and keeps raw values", () => {
    const live = emptyLive();
    fillLive(live, 1250, { TEY: 180, TIT: 900, AFDP: 5, CDP: 12.6, GTEP: 29, CO: 9.6, NOX: 40 }, null, null);
    expect(live.row).toBe(1250);
    expect(live.v.TEY).toBe(180);
    expect(live.n.tey).toBe(1);
    expect(live.n.tit).toBe(0);
    expect(live.n.afdp).toBeCloseTo(0.5, 5);
    expect(live.n.co).toBe(1);
    for (const v of Object.values(live.n)) expect(v).toBeGreaterThanOrEqual(0);
  });
});
