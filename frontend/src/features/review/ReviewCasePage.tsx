import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client";
import { ErrorState, Loading } from "../../components/states";
import { executionStatusLabel, statusLabel, transitionLabel } from "../cases/status";

export function ReviewCasePage() {
  const { caseId } = useParams();
  const id = Number(caseId);
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  const query = useQuery({
    queryKey: ["review-case", id],
    queryFn: () => api.reviewCase(id),
    enabled: Number.isInteger(id),
  });

  const decisionMutation = useMutation({
    mutationFn: (action: "approve" | "reject") =>
      action === "approve"
        ? api.approve(id, { reason: reason.trim() || undefined })
        : api.reject(id, { reason: reason.trim() }),
    onSuccess: () => {
      setReason("");
      setFormError(null);
      // Refetch so a concurrent decision elsewhere shows its updated state.
      void queryClient.invalidateQueries({ queryKey: ["review-case", id] });
      void queryClient.invalidateQueries({ queryKey: ["review-cases"] });
    },
  });

  function decide(action: "approve" | "reject", event: FormEvent) {
    event.preventDefault();
    if (action === "reject" && !reason.trim()) {
      setFormError("A reason is required to reject a case.");
      return;
    }
    setFormError(null);
    decisionMutation.mutate(action);
  }

  if (query.isLoading) return <Loading label="Loading case…" />;
  if (query.isError) return <ErrorState message="Could not load this case." />;
  if (!query.data) return null;

  const c = query.data;
  const isRefund = c.kind === "refund";
  const isPendingReview = c.status === "PENDING_REVIEW";

  return (
    <section className="page">
      <p>
        <Link className="back-link" to="/review">
          ← Back to queue
        </Link>
      </p>
      <h1>Case #{c.id}</h1>

      <div className="detail-grid">
        <div className="detail-field">
          <span className="detail-label">Type</span>
          <span>{isRefund ? "Refund request" : "Escalation"}</span>
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

      {isRefund && isPendingReview && (
        <form className="decision-form" onSubmit={(e) => decide("approve", e)}>
          <label className="filter" htmlFor="decision-reason">
            Decision reason (required to reject)
            <textarea
              id="decision-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
            />
          </label>
          <div className="decision-actions">
            <button type="submit" className="button button-primary" disabled={decisionMutation.isPending}>
              Approve
            </button>
            <button
              type="button"
              className="button button-danger"
              disabled={decisionMutation.isPending}
              onClick={(e) => decide("reject", e)}
            >
              Reject
            </button>
          </div>
          {formError && (
            <div className="state state-error" role="alert">
              {formError}
            </div>
          )}
          {decisionMutation.isError && (
            <div className="state state-error" role="alert">
              {decisionMutation.error instanceof Error ? decisionMutation.error.message : "Decision failed."}
            </div>
          )}
        </form>
      )}

      {!isPendingReview && <p className="decision-note">This case has already been decided.</p>}

      <h2>Execution</h2>
      {c.action ? (
        <div className="execution-panel">
          <div className="detail-grid">
            <div className="detail-field">
              <span className="detail-label">Provider</span>
              <span>{c.action.provider}</span>
            </div>
            <div className="detail-field">
              <span className="detail-label">Action status</span>
              <span className={`case-status status-${c.action.status.toLowerCase()}`}>
                {executionStatusLabel(c.action.status)}
              </span>
            </div>
            <div className="detail-field">
              <span className="detail-label">Amount</span>
              <span>
                {(c.action.amount_cents / 100).toFixed(2)} {c.action.currency.toUpperCase()}
              </span>
            </div>
            <div className="detail-field">
              <span className="detail-label">Attempts</span>
              <span>{c.action.attempts}</span>
            </div>
            <div className="detail-field">
              <span className="detail-label">Provider refund</span>
              <span>{c.action.provider_refund_id ?? "—"}</span>
            </div>
            <div className="detail-field">
              <span className="detail-label">Idempotency key</span>
              <span>{c.action.idempotency_key}</span>
            </div>
          </div>
          {c.action.last_error && (
            <div className="state state-error" role="alert">
              Last error: {c.action.last_error}
            </div>
          )}
        </div>
      ) : (
        <p className="decision-note">No refund action yet.</p>
      )}

      <h2>Notification delivery</h2>
      {c.notifications.length === 0 ? (
        <p className="decision-note">No notifications queued.</p>
      ) : (
        <ul className="event-list">
          {c.notifications.map((n) => (
            <li key={n.id} className="event-item">
              <span className="event-transition">{n.kind}</span>
              <span className="event-date">
                {n.status} · attempts {n.attempts}
              </span>
              {n.last_error && <span className="event-reason">{n.last_error}</span>}
            </li>
          ))}
        </ul>
      )}

      <h2>Outbox / recovery</h2>
      {c.outbox.length === 0 ? (
        <p className="decision-note">No outbox records.</p>
      ) : (
        <ul className="event-list">
          {c.outbox.map((o) => (
            <li key={o.id} className="event-item">
              <span className="event-transition">{o.event_type}</span>
              <span className="event-date">
                {o.status} · attempts {o.attempts}
              </span>
              {o.last_error && <span className="event-reason">{o.last_error}</span>}
            </li>
          ))}
        </ul>
      )}

      <h2>Audit history</h2>
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
