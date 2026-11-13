import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../../api/client";
import type { Case } from "../../api/types";
import { EmptyState, ErrorState, Loading } from "../../components/states";
import { statusLabel } from "../cases/status";

const LIMIT = 20;

export function ReviewQueuePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const status = searchParams.get("status") ?? "";
  const kind = searchParams.get("kind") ?? "";
  const offset = Number(searchParams.get("offset") ?? "0");

  const query = useQuery({
    queryKey: ["review-cases", status, kind, offset],
    queryFn: () => api.reviewQueue({ status, kind, limit: LIMIT, offset }),
  });

  function setFilter(key: "status" | "kind", value: string) {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    next.delete("offset");
    setSearchParams(next);
  }

  function setOffset(nextOffset: number) {
    const next = new URLSearchParams(searchParams);
    next.set("offset", String(nextOffset));
    setSearchParams(next);
  }

  if (query.isLoading) return <Loading label="Loading queue…" />;
  if (query.isError) return <ErrorState message="Could not load the review queue." />;
  const data = query.data;

  return (
    <section className="page">
      <h1>Review queue</h1>

      <div className="filters" role="group" aria-label="Queue filters">
        <label className="filter">
          Status
          <select value={status} onChange={(e) => setFilter("status", e.target.value)}>
            <option value="">All</option>
            <option value="PENDING_REVIEW">Pending review</option>
            <option value="APPROVED">Approved</option>
            <option value="REJECTED">Rejected</option>
            <option value="OPEN">Open</option>
          </select>
        </label>
        <label className="filter">
          Kind
          <select value={kind} onChange={(e) => setFilter("kind", e.target.value)}>
            <option value="">All</option>
            <option value="refund">Refund</option>
            <option value="escalation">Escalation</option>
          </select>
        </label>
      </div>

      {data && data.items.length === 0 ? (
        <EmptyState message="No cases match these filters." />
      ) : (
        <>
          <ul className="case-list">
            {(data?.items ?? []).map((c: Case) => (
              <li key={c.id}>
                <Link className="case-card" to={`/review/${c.id}`}>
                  <span className="case-kind">{c.kind === "refund" ? "Refund" : "Escalation"}</span>
                  <span className={`case-status status-${c.status.toLowerCase()}`}>{statusLabel(c.status)}</span>
                  <span className="case-order">
                    {c.order_id ? `Order #${c.order_id}` : `Ticket #${c.ticket_id ?? c.id}`}
                  </span>
                  <span className="case-reason">{c.reason ?? ""}</span>
                </Link>
              </li>
            ))}
          </ul>

          <nav className="pagination" aria-label="Pagination">
            <button
              type="button"
              className="button button-ghost"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - LIMIT))}
            >
              Previous
            </button>
            <span>
              {data ? `${offset + 1}–${Math.min(offset + LIMIT, data.total)} of ${data.total}` : ""}
            </span>
            <button
              type="button"
              className="button button-ghost"
              disabled={!data || offset + LIMIT >= data.total}
              onClick={() => setOffset(offset + LIMIT)}
            >
              Next
            </button>
          </nav>
        </>
      )}
    </section>
  );
}
