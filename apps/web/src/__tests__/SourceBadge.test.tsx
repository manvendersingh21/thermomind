import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SourceBadge, type SourceBadgeVariant } from "../components/SourceBadge";

const cases: [SourceBadgeVariant, string][] = [
  ["real", "REAL PUBLIC DATA"],
  ["synthetic", "SYNTHETIC OVERLAY"],
  ["model", "MODEL-DERIVED"],
  ["review", "HUMAN REVIEW REQUIRED"],
  ["meta", "META LIVE"],
  ["offline", "OFFLINE PREVIEW"],
];

describe("SourceBadge", () => {
  it.each(cases)("variant %s renders its honest label", (variant, text) => {
    render(<SourceBadge variant={variant} />);
    expect(screen.getByText(new RegExp(text))).toBeInTheDocument();
  });
  it("custom label overrides default", () => {
    render(<SourceBadge variant="synthetic" label="SYNTHETIC = TRUE" />);
    expect(screen.getByText("SYNTHETIC = TRUE")).toBeInTheDocument();
    expect(screen.queryByText("SYNTHETIC OVERLAY")).toBeNull();
  });
});
