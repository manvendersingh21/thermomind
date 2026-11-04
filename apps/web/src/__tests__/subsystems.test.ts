import { describe, expect, it } from "vitest";
import { REVIEW_SENTENCE, SUBSYSTEM_GUIDES, guideFor } from "../lib/subsystems";

const CONTROL_VERBS: RegExp[] = [
  /open (or close )?the valve/i,
  /close the valve/i,
  /set ?point/i,
  /\btrip\b/i,
  /shut ?down the unit/i,
  /\bbypass/i,
  /override (the )?interlock/i,
  /reduce (the )?load/i,
  /increase (the )?fuel/i,
];

describe("subsystem guides", () => {
  const guides = Object.values(SUBSYSTEM_GUIDES);
  it("has guides", () => expect(guides.length).toBeGreaterThanOrEqual(4));
  it.each(guides.map((g) => [g.hypothesis_key, g] as const))("%s: no control verbs in text", (_k, g) => {
    for (const t of [...g.engineer_checks, ...g.where_to_look]) {
      for (const re of CONTROL_VERBS) expect(t, `"${t}" matched ${re}`).not.toMatch(re);
    }
  });
  it.each(guides.map((g) => [g.hypothesis_key, g] as const))("%s: ends with review sentence", (_k, g) => {
    expect(g.engineer_checks[g.engineer_checks.length - 1]).toBe(REVIEW_SENTENCE);
  });
  it("guideFor falls back to unknown", () => {
    expect(guideFor("nope").hypothesis_key).toBe("unknown");
    expect(guideFor(null).hypothesis_key).toBe("unknown");
    expect(guideFor("intake_restriction").hypothesis_key).toBe("intake_restriction");
  });
});
