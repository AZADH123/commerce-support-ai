export function statusLabel(status: string): string {
  switch (status) {
    case "PENDING_REVIEW":
      return "Pending review";
    case "APPROVED":
      return "Approved";
    case "PROCESSING":
      return "Processing";
    case "REFUNDED":
      return "Refunded";
    case "NEEDS_ATTENTION":
      return "Needs attention";
    case "REJECTED":
      return "Rejected";
    case "OPEN":
      return "Open";
    default:
      return status;
  }
}

export function transitionLabel(transition: string): string {
  switch (transition) {
    case "CREATED":
      return "Requested";
    case "ESCALATED":
      return "Escalated";
    case "APPROVED":
      return "Approved";
    case "REJECTED":
      return "Rejected";
    case "PROCESSING":
      return "Processing started";
    case "REFUNDED":
      return "Refunded";
    case "NEEDS_ATTENTION":
      return "Needs attention";
    case "RETRY":
      return "Retry";
    default:
      return transition;
  }
}

export function executionStatusLabel(status: string | null | undefined): string {
  if (!status) return "—";
  switch (status) {
    case "PENDING":
      return "Queued";
    case "SUBMITTING":
      return "Submitting to provider";
    case "SUCCEEDED":
      return "Succeeded";
    case "RETRYABLE":
      return "Retrying";
    case "PERMANENT_FAILURE":
      return "Permanently failed";
    case "UNCERTAIN":
      return "Reconciling";
    case "NEEDS_ATTENTION":
      return "Needs attention";
    default:
      return status;
  }
}

// The customer timeline for a refund case.
export const CASE_TIMELINE_STAGES = ["APPROVED", "PROCESSING", "REFUNDED"] as const;

/**
 * Bounded polling for cases that are still moving. Returns false (stop polling)
 * for terminal or attention states, so the UI stops when the screen closes or
 * the case settles.
 */
export function casePollingInterval(status: string | undefined): number | false {
  if (status === "APPROVED" || status === "PROCESSING") {
    return 5000;
  }
  return false;
}
