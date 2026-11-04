import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AgentTimeline } from "../components/AgentTimeline";
import { evidenceById, events } from "../test/fixture";

describe("AgentTimeline", () => {
  it("renders tool_call, tool_result and validation events", () => {
    render(<AgentTimeline events={events} evidenceById={evidenceById} onOpenEvidence={() => {}} />);
    expect(screen.getAllByText("Tool call").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Tool result").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Validation").length).toBeGreaterThan(0);
  });
  it("shows tool name", () => {
    render(<AgentTimeline events={events} evidenceById={evidenceById} onOpenEvidence={() => {}} />);
    expect(screen.getAllByText("get_sensor_window").length).toBeGreaterThan(0);
  });
  it("never renders a field named reasoning, even if present in an event", () => {
    const evil = [{ ...events[0], reasoning: "SECRET CHAIN OF THOUGHT" }] as unknown as typeof events;
    const { container } = render(<AgentTimeline events={evil} evidenceById={evidenceById} onOpenEvidence={() => {}} />);
    expect(container.textContent).not.toMatch(/SECRET CHAIN OF THOUGHT/);
    expect(container.textContent?.toLowerCase()).not.toContain("reasoning");
  });
  it("fixture events carry no reasoning field and render none", () => {
    expect(events.some((e) => "reasoning" in e)).toBe(false);
    const { container } = render(<AgentTimeline events={events} evidenceById={evidenceById} onOpenEvidence={() => {}} />);
    expect(container.textContent).not.toMatch(/reasoning(?!=\d)/i); // token counts like reasoning=0 are usage metadata, not content
  });
  it("args are collapsed until expanded", () => {
    render(<AgentTimeline events={events} evidenceById={evidenceById} onOpenEvidence={() => {}} />);
    fireEvent.click(screen.getAllByText("show args")[0]);
    expect(screen.getByText("hide args")).toBeInTheDocument();
  });
  it("empty events show a message", () => {
    render(<AgentTimeline events={[]} evidenceById={evidenceById} onOpenEvidence={() => {}} />);
    expect(screen.getByText(/No agent events/)).toBeInTheDocument();
  });
});
