import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { WhereToLook } from "../components/WhereToLook";
import type { DiagnosticReport } from "../api/types";
import { REVIEW_SENTENCE } from "../lib/subsystems";
import { report } from "../test/fixture";

const schem = () => <div data-testid="schem" />;

describe("WhereToLook", () => {
  it("S01-style informational/unknown report says Nothing to locate", () => {
    const s01: DiagnosticReport = {
      ...report,
      severity: "informational",
      hypotheses: [{ ...report.hypotheses[3], rank: 1 }],
    };
    render(<WhereToLook report={s01} scenarioSynthetic={false} renderSchematic={schem} />);
    expect(screen.getByText(/Nothing to locate/)).toBeInTheDocument();
    expect(screen.queryByText(/Look here/)).toBeNull();
  });
  it("null report says Nothing to locate", () => {
    render(<WhereToLook report={null} scenarioSynthetic={false} renderSchematic={schem} />);
    expect(screen.getByText(/Nothing to locate/)).toBeInTheDocument();
  });
  it("intake_restriction shows LOOK HERE (case-insensitive) and review sentence last", () => {
    const { container } = render(<WhereToLook report={report} scenarioSynthetic={true} renderSchematic={schem} />);
    expect(screen.getByText(/look here/i)).toBeInTheDocument();
    expect(screen.getByText("Synthetic scenario")).toBeInTheDocument();
    const items = container.querySelectorAll("ul.columns-2 li");
    expect(items[items.length - 1].textContent).toContain(REVIEW_SENTENCE);
  });
  it("inconclusive top hypothesis shows caveat", () => {
    const inc: DiagnosticReport = {
      ...report,
      hypotheses: report.hypotheses.map((h) => (h.rank === 1 ? { ...h, status: "inconclusive" as const } : h)),
    };
    render(<WhereToLook report={inc} scenarioSynthetic={false} renderSchematic={schem} />);
    expect(screen.getByText(/No confident location; verify data quality first/)).toBeInTheDocument();
    expect(screen.getAllByText(/Candidate area \(unconfirmed\)/).length).toBeGreaterThan(0);
  });
  it("states no control actions are possible", () => {
    render(<WhereToLook report={report} scenarioSynthetic={false} renderSchematic={schem} />);
    expect(screen.getByText(/No plant control actions are possible/)).toBeInTheDocument();
  });
});
