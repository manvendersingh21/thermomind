import { describe, expect, it } from "vitest";
import { rangeLabel, sampleLabel } from "../lib/format";

describe("sample labels (no timestamps in UCI data)", () => {
  it("sampleLabel is year bullet sample #n", () => {
    expect(sampleLabel(2014, 1253)).toBe("2014 • sample #1253");
  });
  it("sampleLabel contains no date-like text", () => {
    expect(sampleLabel(2011, 0)).not.toMatch(/\d{4}-\d{2}|\d{1,2}:\d{2}|UTC/);
  });
  it("rangeLabel uses inclusive end", () => {
    expect(rangeLabel({ source_year: 2014, start: 1200, end: 1320 })).toBe("2014 • samples #1200–#1319");
  });
  it("rangeLabel handles null as em dash", () => {
    expect(rangeLabel(null)).toBe("—");
  });
  it("rangeLabel never fabricates dates", () => {
    expect(rangeLabel({ source_year: 2013, start: 5, end: 10 })).not.toMatch(/\d{4}-\d{2}-\d{2}|:/);
  });
});
