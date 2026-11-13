import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../../api/client";
import { EmptyState, ErrorState, Loading } from "../../components/states";
import { ConversationList } from "./ConversationList";
import { PolicyCitations } from "./PolicyCitations";

export function ChatPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState("");

  const rawId = searchParams.get("conversation");
  const conversationId = rawId ? Number(rawId) : undefined;

  const messagesQuery = useQuery({
    queryKey: ["conversation", conversationId],
    queryFn: () => api.getConversation(conversationId as number),
    enabled: conversationId !== undefined,
  });

  const sendMutation = useMutation({
    mutationFn: async (message: string) =>
      api.chat(
        conversationId !== undefined ? { message, conversation_id: conversationId } : { message },
      ),
    onSuccess: (res) => {
      if (conversationId === undefined) {
        setSearchParams({ conversation: String(res.conversation_id) });
      }
      setDraft("");
      void queryClient.invalidateQueries({ queryKey: ["conversations"] });
      void queryClient.invalidateQueries({ queryKey: ["conversation", res.conversation_id] });
    },
  });

  const pending = sendMutation.isPending;

  function submit(event: FormEvent) {
    event.preventDefault();
    const message = draft.trim();
    if (!message || pending) return;
    sendMutation.mutate(message);
  }

  function selectConversation(id: number) {
    setSearchParams({ conversation: String(id) });
  }

  const messages = messagesQuery.data?.messages ?? [];

  return (
    <section className="chat-layout">
      <aside className="chat-sidebar">
        <h2 className="sidebar-heading">History</h2>
        <ConversationList activeId={conversationId} onSelect={selectConversation} />
      </aside>

      <div className="chat-panel">
        <div className="chat-thread" aria-live="polite">
          {conversationId === undefined && (
            <EmptyState message="Start a new conversation by sending a message below." />
          )}
          {conversationId !== undefined && messagesQuery.isLoading && <Loading />}
          {conversationId !== undefined && messagesQuery.isError && (
            <ErrorState message="Could not load this conversation." />
          )}
          {messages.map((m) => (
            <div key={m.id} className={m.role === "user" ? "message message-user" : "message message-assistant"}>
              <div className="message-bubble">{m.content}</div>
              {m.role === "assistant" && m.agent && (
                <div className="message-meta">handled by {m.agent}</div>
              )}
              {m.role === "assistant" && <PolicyCitations citations={m.citations} />}
            </div>
          ))}
          {pending && (
            <div className="message message-assistant">
              <div className="message-bubble message-thinking">Thinking…</div>
            </div>
          )}
        </div>

        <form className="chat-composer" onSubmit={submit}>
          <label className="visually-hidden" htmlFor="chat-input">
            Message
          </label>
          <input
            id="chat-input"
            className="chat-input"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="How can we help?"
            autoComplete="off"
          />
          <button type="submit" className="button button-primary" disabled={pending || !draft.trim()}>
            Send
          </button>
        </form>
        {sendMutation.isError && (
          <div className="state state-error" role="alert">
            {sendMutation.error instanceof Error ? sendMutation.error.message : "Failed to send."}
          </div>
        )}
      </div>
    </section>
  );
}
