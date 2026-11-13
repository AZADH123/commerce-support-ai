import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { ConversationSummary } from "../../api/types";
import { EmptyState, Loading } from "../../components/states";

export function ConversationList({
  activeId,
  onSelect,
}: {
  activeId: number | undefined;
  onSelect: (id: number) => void;
}) {
  const query = useQuery({ queryKey: ["conversations"], queryFn: api.listConversations });

  if (query.isLoading) return <Loading label="Loading conversations…" />;
  if (query.isError) return <EmptyState message="Could not load conversations." />;
  if (!query.data || query.data.length === 0) {
    return <EmptyState message="No conversations yet." />;
  }

  return (
    <ul className="conversation-list" aria-label="Conversations">
      {query.data.map((c: ConversationSummary) => (
        <li key={c.id}>
          <button
            type="button"
            className={c.id === activeId ? "conversation-item active" : "conversation-item"}
            onClick={() => onSelect(c.id)}
          >
            <span className="conversation-preview">{c.last_message ?? "New conversation"}</span>
            <span className="conversation-date">
              {new Date(c.updated_at).toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" })}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}
