import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client";
import { ErrorState, Loading } from "../../components/states";
import { CaseTimeline } from "./CaseTimeline";
import { casePollingInterval, executionStatusLabel, statusLabel, transitionLabel } from "./status";

export function CaseDetailPage() {
  const { caseId } = useParams();
  const id = Number(caseId);
  const query = useQuery({
    queryKey: ["case", id],
    queryFn: () => api.getCase(id),
    enabled: Number.isInteger(id),
    // Bounded polling: every 5s while the case is still moving, then stop.
    refetchInterval: (query) => casePollingInterval(query.state.data?.status),
  });

  if (query.isLoading) return <Loading label="Loading case…" />;
  if (query.isError) return <ErrorState message="Could not load this case." />;
  if (!query.data) return null;

  const c = query.data;

  return (
    <section className="page">
      <p>
        <Link className="back-link" to="/cases">
          ← Back to my cases
        </Link>
      </p>
      <h1>Case #{c.id}</h1>

      <div className={`case-banner case-banner-${c.status.toLowerCase()}`} role="status">
        <span className="case-banner-status">{statusLabel(c.status)}</span>
        {c.kind === "refund" && c.execution_status && (
          <span className="case-banner-execution">
            Refund execution: {executionStatusLabel(c.execution_status)}
          </span>
        )}
        {(c.status === "APPROVED" || c.status === "PROCESSING") && (
          <span className="case-banner-hint">Checking for updates…</span>
        )}
      </div>

      {c.kind === "refund" && <CaseTimeline status={c.status} events={c.events} />}

      <div className="detail-grid">
        <div className="detail-field">
          <span className="detail-label">Type</span>
          <span>{c.kind === "refund" ? "Refund request" : "Escalation"}</span>
        </div>
        <div className="detail-field">
          <span className="detail-label">Status</span>
          <span className={`case-status status-${c.status.toLowerCase()}`}>{statusLabel(c.status)}</span>
        </div>
        {c.order_id !== null && (
          <div className="detail-field">
            <span className="detail-label">Order</span>
            <span>#{c.order_id}</span>
          </div>
        )}
        {c.ticket_id && (
          <div className="detail-field">
            <span className="detail-label">Ticket</span>
            <span>#{c.ticket_id}</span>
          </div>
        )}
        <div className="detail-field">
          <span className="detail-label">Reason</span>
          <span>{c.reason ?? "—"}</span>
        </div>
        {c.decision_reason && (
          <div className="detail-field">
            <span className="detail-label">Decision reason</span>
            <span>{c.decision_reason}</span>
          </div>
        )}
        {c.order && (
          <div className="detail-field">
            <span className="detail-label">Item</span>
            <span>{c.order.item}</span>
          </div>
        )}
        {c.policy_version !== null && (
          <div className="detail-field">
            <span className="detail-label">Refund policy</span>
            <span>Version {c.policy_version}</span>
          </div>
        )}
      </div>

      <h2>Timeline</h2>
      <ol className="event-list">
        {c.events.map((e) => (
          <li key={e.id} className="event-item">
            <span className="event-transition">{transitionLabel(e.transition)}</span>
            <span className="event-date">{new Date(e.created_at).toLocaleString()}</span>
            {e.reason && <span className="event-reason">{e.reason}</span>}
          </li>
        ))}
      </ol>
    </section>
  );
}
