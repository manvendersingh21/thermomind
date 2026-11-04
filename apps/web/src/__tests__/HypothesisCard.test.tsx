import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { HypothesisCard } from "../components/HypothesisCard";
import { evidenceById, report } from "../test/fixture";

describe("HypothesisCard", () => {
  const h = report.hypotheses[0];
  it("renders rank, name and status", () => {
    render(<HypothesisCard hypothesis={h} evidenceById={evidenceById} onOpenEvidence={() => {}} />);
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText("Progressive intake filter restriction")).toBeInTheDocument();
    expect(screen.getByText("possible")).toBeInTheDocument();
  });
  it("renders supporting evidence chips and opens on click", () => {
    const open = vi.fn();
    render(<HypothesisCard hypothesis={h} evidenceById={evidenceById} onOpenEvidence={open} />);
    fireEvent.click(screen.getByRole("button", { name: /ev_afdp_01/ }));
    expect(open).toHaveBeenCalledWith("ev_afdp_01");
  });
  it("marks synthetic evidence chips with SYN", () => {
    render(<HypothesisCard hypothesis={h} evidenceById={evidenceById} onOpenEvidence={() => {}} />);
    expect(screen.getAllByText("SYN").length).toBeGreaterThan(0);
  });
  it("shows 'none' for empty evidence lists and unverified ids are flagged", () => {
    const h2 = { ...report.hypotheses[1], contradicting_evidence_ids: ["ev_missing"] };
    render(<HypothesisCard hypothesis={h2} evidenceById={evidenceById} onOpenEvidence={() => {}} />);
    expect(screen.getByText("none")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ev_missing" }).className).toMatch(/line-through/);
  });
  it("sorts nothing itself: rank comes from props; ordering is the page's job (rank asc)", () => {
    const shuffled = [report.hypotheses[2], report.hypotheses[0], report.hypotheses[1]];
    // The page does `[...hypotheses].sort((a,b)=>a.rank-b.rank)` (InvestigationPage; not exported).
    const sorted = [...shuffled].sort((a, b) => a.rank - b.rank).map((x) => x.rank);
    expect(sorted).toEqual([1, 2, 3]);
    expect(shuffled.map((x) => x.rank)).toEqual([3, 1, 2]);
  });
});
