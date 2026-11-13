import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import type { Case } from "../../api/types";
import { EmptyState, ErrorState, Loading } from "../../components/states";
import { statusLabel } from "./status";

export function CaseListPage() {
  const query = useQuery({ queryKey: ["cases"], queryFn: api.listCases });

  if (query.isLoading) return <Loading label="Loading your cases…" />;
  if (query.isError) return <ErrorState message="Could not load your cases." />;
  if (!query.data || query.data.length === 0) {
    return <EmptyState message="You have no cases yet." />;
  }

  return (
    <section className="page">
      <h1>My cases</h1>
      <ul className="case-list">
        {query.data.map((c: Case) => (
          <li key={c.id}>
            <Link className="case-card" to={`/cases/${c.id}`}>
              <span className="case-kind">{c.kind === "refund" ? "Refund" : "Escalation"}</span>
              <span className={`case-status status-${c.status.toLowerCase()}`}>{statusLabel(c.status)}</span>
              <span className="case-order">{c.order_id ? `Order #${c.order_id}` : `Ticket #${c.ticket_id ?? c.id}`}</span>
              <span className="case-reason">{c.reason ?? ""}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
