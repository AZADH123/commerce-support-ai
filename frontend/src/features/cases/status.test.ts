import { describe, expect, it } from "vitest";
import {
  casePollingInterval,
  executionStatusLabel,
  statusLabel,
  transitionLabel,
} from "./status";

describe("statusLabel", () => {
  it("maps known statuses to friendly labels", () => {
    expect(statusLabel("PENDING_REVIEW")).toBe("Pending review");
    expect(statusLabel("APPROVED")).toBe("Approved");
    expect(statusLabel("PROCESSING")).toBe("Processing");
    expect(statusLabel("REFUNDED")).toBe("Refunded");
    expect(statusLabel("NEEDS_ATTENTION")).toBe("Needs attention");
    expect(statusLabel("REJECTED")).toBe("Rejected");
    expect(statusLabel("OPEN")).toBe("Open");
  });

  it("passes through unknown statuses", () => {
    expect(statusLabel("SOMETHING_ELSE")).toBe("SOMETHING_ELSE");
  });
});

describe("transitionLabel", () => {
  it("maps known transitions", () => {
    expect(transitionLabel("CREATED")).toBe("Requested");
    expect(transitionLabel("APPROVED")).toBe("Approved");
    expect(transitionLabel("PROCESSING")).toBe("Processing started");
    expect(transitionLabel("REFUNDED")).toBe("Refunded");
    expect(transitionLabel("NEEDS_ATTENTION")).toBe("Needs attention");
    expect(transitionLabel("REJECTED")).toBe("Rejected");
  });
});

describe("executionStatusLabel", () => {
  it("maps execution action statuses", () => {
    expect(executionStatusLabel("PENDING")).toBe("Queued");
    expect(executionStatusLabel("SUBMITTING")).toBe("Submitting to provider");
    expect(executionStatusLabel("SUCCEEDED")).toBe("Succeeded");
    expect(executionStatusLabel("RETRYABLE")).toBe("Retrying");
    expect(executionStatusLabel("NEEDS_ATTENTION")).toBe("Needs attention");
    expect(executionStatusLabel(null)).toBe("—");
  });
});

describe("casePollingInterval", () => {
  it("polls while a case is still moving", () => {
    expect(casePollingInterval("APPROVED")).toBe(5000);
    expect(casePollingInterval("PROCESSING")).toBe(5000);
  });

  it("stops polling on terminal or attention states", () => {
    expect(casePollingInterval("REFUNDED")).toBe(false);
    expect(casePollingInterval("REJECTED")).toBe(false);
    expect(casePollingInterval("NEEDS_ATTENTION")).toBe(false);
    expect(casePollingInterval(undefined)).toBe(false);
  });
});
