// Typed models matching the FastAPI response schemas.
// The canonical OpenAPI-derived types live in ./schema.d.ts (see scripts/gen-api.mjs).

export type Role = "customer" | "reviewer";

export interface Me {
  id: number;
  sub: string;
  email: string | null;
  name: string;
  role: Role;
}

export interface RedactedToolCall {
  agent: string;
  tool: string;
}

export interface Usage {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
}

export interface PolicyCitation {
  document_id: number;
  title: string;
  version: number;
  topic: string;
  effective_date: string;
  source: string;
  chunk_index: number;
  snippet: string;
  score: number;
}

export interface ChatResponse {
  conversation_id: number;
  reply: string;
  agent: string;
  trace: RedactedToolCall[];
  usage: Usage;
  cached: boolean;
  citations: PolicyCitation[];
}

export interface Order {
  order_id: number;
  item: string;
  status: string;
  order_date: string;
  amount: number;
}

export interface ConversationSummary {
  id: number;
  created_at: string;
  updated_at: string;
  last_message: string | null;
}

export interface Message {
  id: number;
  role: "user" | "assistant";
  content: string;
  agent: string | null;
  cached: boolean;
  created_at: string;
  citations: PolicyCitation[];
}

export interface ConversationDetail {
  id: number;
  messages: Message[];
}

export interface CaseEvent {
  id: number;
  transition: string;
  reason: string | null;
  created_at: string;
  actor_id: number | null;
}

export interface Case {
  id: number;
  kind: "refund" | "escalation";
  order_id: number | null;
  status: string;
  reason: string | null;
  ticket_id: string | null;
  decision_reason: string | null;
  decided_at: string | null;
  created_at: string;
  updated_at: string;
  policy_version: number | null;
  policy_document_id: number | null;
  execution_status: string | null;
}

export interface CaseDetail extends Case {
  events: CaseEvent[];
  order: Order | null;
}

export interface RefundAction {
  id: number;
  status: string;
  provider: string;
  provider_refund_id: string | null;
  payment_ref: string | null;
  amount_cents: number;
  currency: string;
  attempts: number;
  last_error: string | null;
  idempotency_key: string;
  processed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface NotificationInfo {
  id: number;
  kind: string;
  status: string;
  to_email: string | null;
  attempts: number;
  last_error: string | null;
  created_at: string;
  sent_at: string | null;
}

export interface OutboxInfo {
  id: number;
  event_type: string;
  status: string;
  attempts: number;
  last_error: string | null;
  available_at: string;
  processed_at: string | null;
}

export interface ReviewCaseDetail extends CaseDetail {
  action: RefundAction | null;
  notifications: NotificationInfo[];
  outbox: OutboxInfo[];
}

export interface PaginatedCases {
  items: Case[];
  total: number;
  limit: number;
  offset: number;
}

export interface OidcConfig {
  issuer: string;
  client_id: string;
  audience: string;
  scope: string;
  authorize_endpoint: string;
  token_endpoint: string;
  end_session_endpoint: string;
}

export interface DecisionBody {
  reason?: string;
}
