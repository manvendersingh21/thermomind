import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { EvidenceDrawer } from "../components/EvidenceDrawer";
import { evidenceById } from "../test/fixture";

describe("EvidenceDrawer", () => {
  const syn = evidenceById.get("ev_afdp_01")!;
  const real = evidenceById.get("ev_at_05")!;
  it("shows unit, computation and range labels", () => {
    render(<EvidenceDrawer evidence={syn} onClose={() => {}} />);
    expect(screen.getByText("mbar")).toBeInTheDocument();
    expect(screen.getByText(syn.computation)).toBeInTheDocument();
    expect(screen.getByText("2014 • samples #1200–#1319")).toBeInTheDocument();
    expect(screen.getByText("2014 • samples #960–#1199")).toBeInTheDocument();
  });
  it("shows synthetic badge when is_synthetic", () => {
    render(<EvidenceDrawer evidence={syn} onClose={() => {}} />);
    expect(screen.getByText("SYNTHETIC = TRUE")).toBeInTheDocument();
    expect(screen.getByText("MEASURED + SYNTHETIC OVERLAY")).toBeInTheDocument();
  });
  it("shows non-synthetic badge for real observation", () => {
    render(<EvidenceDrawer evidence={real} onClose={() => {}} />);
    expect(screen.getByText("SYNTHETIC = FALSE")).toBeInTheDocument();
    expect(screen.queryByText("SYNTHETIC = TRUE")).toBeNull();
  });
  it("flags unverified citations", () => {
    render(<EvidenceDrawer evidence={null} missingId="ev_ghost" onClose={() => {}} />);
    expect(screen.getByText(/Treat the citation as unverified/)).toBeInTheDocument();
  });
  it("Escape closes", () => {
    const close = vi.fn();
    render(<EvidenceDrawer evidence={syn} onClose={close} />);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(close).toHaveBeenCalled();
  });
});
