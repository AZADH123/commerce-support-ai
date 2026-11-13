import type { CaseEvent } from "../../api/types";
import { CASE_TIMELINE_STAGES, statusLabel } from "./status";

/**
 * Customer-visible refund timeline: APPROVED -> PROCESSING -> REFUNDED, with a
 * NEEDS_ATTENTION branch, and a terminal REJECTED state.
 */
export function CaseTimeline({ status, events }: { status: string; events: CaseEvent[] }) {
  if (status === "REJECTED") {
    return (
      <ol className="timeline" aria-label="Case timeline">
        <li className="timeline-step done current">
          <span className="timeline-dot" aria-hidden="true" />
          <span className="timeline-label">{statusLabel("REJECTED")}</span>
        </li>
      </ol>
    );
  }

  const reached = new Set(events.map((event) => event.transition));
  const stages: string[] = [...CASE_TIMELINE_STAGES];
  if (status === "NEEDS_ATTENTION") {
    stages.push("NEEDS_ATTENTION");
  }

  return (
    <ol className="timeline" aria-label="Case timeline">
      {stages.map((stage) => {
        const done = reached.has(stage) || status === stage;
        const current = status === stage;
        return (
          <li
            key={stage}
            className={`timeline-step${done ? " done" : ""}${current ? " current" : ""}`}
          >
            <span className="timeline-dot" aria-hidden="true" />
            <span className="timeline-label">{statusLabel(stage)}</span>
          </li>
        );
      })}
    </ol>
  );
}
