import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EmptyState, ErrorState, Loading } from "./states";

describe("states", () => {
  it("renders a loading state with accessible status", () => {
    render(<Loading label="Loading cases…" />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading cases…");
  });

  it("renders an error state with an alert role", () => {
    render(<ErrorState message="Something broke" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Something broke");
  });

  it("renders an empty state", () => {
    render(<EmptyState message="Nothing here yet" />);
    expect(screen.getByText("Nothing here yet")).toBeInTheDocument();
  });
});
