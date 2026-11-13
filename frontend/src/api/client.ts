import type {
  Case,
  CaseDetail,
  ChatResponse,
  ConversationDetail,
  ConversationSummary,
  DecisionBody,
  Me,
  OidcConfig,
  Order,
  PaginatedCases,
  ReviewCaseDetail,
} from "./types";

// The access token lives only in memory (never in localStorage/sessionStorage
// or URLs), and is injected into every request here.
let accessToken: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

export function setOnUnauthorized(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (accessToken) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }

  const response = await fetch(path, { ...init, headers });

  if (response.status === 401) {
    onUnauthorized?.();
    throw new ApiError(401, "Your session has expired. Please sign in again.");
  }

  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // non-JSON error body; keep the generic message
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

function queryString(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") {
      search.set(key, String(value));
    }
  }
  const s = search.toString();
  return s ? `?${s}` : "";
}

export const api = {
  getAuthConfig: () => request<OidcConfig>("/api/auth/config"),
  getMe: () => request<Me>("/api/me"),

  chat: (body: { message: string; conversation_id?: number }) =>
    request<ChatResponse>("/chat", { method: "POST", body: JSON.stringify(body) }),

  listOrders: () => request<Order[]>("/api/orders"),

  listConversations: () => request<ConversationSummary[]>("/api/conversations"),
  getConversation: (id: number) => request<ConversationDetail>(`/api/conversations/${id}`),

  listCases: () => request<Case[]>("/api/cases"),
  getCase: (id: number) => request<CaseDetail>(`/api/cases/${id}`),

  reviewQueue: (params: { status?: string; kind?: string; limit?: number; offset?: number }) =>
    request<PaginatedCases>(`/api/review/cases${queryString(params)}`),
  reviewCase: (id: number) => request<ReviewCaseDetail>(`/api/review/cases/${id}`),
  approve: (id: number, body: DecisionBody) =>
    request<ReviewCaseDetail>(`/api/review/cases/${id}/approve`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  reject: (id: number, body: DecisionBody) =>
    request<ReviewCaseDetail>(`/api/review/cases/${id}/reject`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
