import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LivePlantSchematic } from "../../../components/LivePlantSchematic";
import SimulatorPage from "../SimulatorPage";
import type { StepRecord } from "../api";

class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(globalThis as unknown as { ResizeObserver: typeof RO }).ResizeObserver = RO;

afterEach(() => vi.unstubAllGlobals());

describe("SimulatorPage", () => {
  it("shows the banner and a not-available notice on 404", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 })),
    );
    render(
      <MemoryRouter>
        <SimulatorPage />
      </MemoryRouter>,
    );
    expect(screen.getByText(/PHYSICS SIMULATION — a software model calibrated to public data/)).toBeTruthy();
    expect(await screen.findAllByText(/simulator backend not available/)).not.toHaveLength(0);
  });
});

describe("LivePlantSchematic", () => {
  it("renders all 11 channel chips with provenance and tolerates missing fields", () => {
    const rec: StepRecord = {
      t_s: 10,
      AT: 15,
      AFDP: 4.2,
      TIT: 1080,
      TEY: 140,
      internal: { freq_hz: 50.01 },
      provenance: { AT: "real_input", AFDP: "synthetic_fault", TIT: "simulated" },
      energy_closure_pct: 99.2,
    };
    const { container } = render(<LivePlantSchematic record={rec} running={false} />);
    for (const k of ["AT", "AP", "AH", "AFDP", "GTEP", "TIT", "TAT", "CDP", "TEY", "CO", "NOX"]) {
      expect(screen.getAllByText(k).length).toBeGreaterThan(0);
    }
    expect(container.querySelector(".lps-fault")).not.toBeNull();
    expect(screen.getByText("50.010")).toBeTruthy();
    render(<LivePlantSchematic record={null} running />);
  });
});
