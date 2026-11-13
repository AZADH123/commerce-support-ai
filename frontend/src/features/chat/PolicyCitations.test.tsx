import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { PolicyCitation } from "../../api/types";
import { PolicyCitations } from "./PolicyCitations";

const citations: PolicyCitation[] = [
  {
    document_id: 4,
    title: "Refund policy",
    version: 2,
    topic: "refund",
    effective_date: "2026-06-01",
    source: "Store Operations Handbook 2026, §5 Refunds (v2, effective 2026-06-01)",
    chunk_index: 0,
    snippet: "Refunds are issued within 3-5 business days after approval.",
    score: 0.82,
  },
  {
    document_id: 1,
    title: "Shipping policy",
    version: 1,
    topic: "shipping",
    effective_date: "2026-01-01",
    source: "Store Operations Handbook 2026, §2 Shipping (v1)",
    chunk_index: 0,
    snippet: "Standard shipping takes 3-5 business days.",
    score: 0.71,
  },
];

describe("PolicyCitations", () => {
  it("renders versioned citations with source and snippet", () => {
    render(<PolicyCitations citations={citations} />);
    expect(screen.getByRole("list", { name: "Policy citations" })).toBeInTheDocument();
    expect(screen.getByText("Refund policy · v2")).toBeInTheDocument();
    expect(screen.getByText(/§5 Refunds \(v2/)).toBeInTheDocument();
    expect(screen.getByText(/3-5 business days after approval/)).toBeInTheDocument();
  });

  it("renders nothing without citations", () => {
    const { container } = render(<PolicyCitations citations={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
