import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { CaseEvent } from "../../api/types";
import { CaseTimeline } from "./CaseTimeline";

function events(transitions: string[]): CaseEvent[] {
  return transitions.map((transition, index) => ({
    id: index + 1,
    transition,
    reason: null,
    created_at: "2026-01-01T00:00:00Z",
    actor_id: null,
  }));
}

describe("CaseTimeline", () => {
  it("renders approved, processing, and refunded stages", () => {
    render(
      <CaseTimeline
        status="REFUNDED"
        events={events(["CREATED", "APPROVED", "PROCESSING", "REFUNDED"])}
      />,
    );
    expect(screen.getByRole("list", { name: "Case timeline" })).toBeInTheDocument();
    expect(screen.getByText("Approved")).toBeInTheDocument();
    expect(screen.getByText("Processing")).toBeInTheDocument();
    expect(screen.getByText("Refunded")).toBeInTheDocument();
  });

  it("adds a needs-attention branch", () => {
    render(
      <CaseTimeline
        status="NEEDS_ATTENTION"
        events={events(["CREATED", "APPROVED", "PROCESSING", "NEEDS_ATTENTION"])}
      />,
    );
    expect(screen.getByText("Needs attention")).toBeInTheDocument();
  });

  it("renders the rejected terminal state", () => {
    render(<CaseTimeline status="REJECTED" events={events(["CREATED", "REJECTED"])} />);
    expect(screen.getByText("Rejected")).toBeInTheDocument();
  });
});
