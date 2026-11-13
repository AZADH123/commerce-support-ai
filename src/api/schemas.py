"""Pydantic request/response models.

Customer-facing models deliberately omit internal tool arguments, raw tool
results, provider errors, and idempotency internals. The full trace is persisted
for audit but only a redacted ``{agent, tool}`` list is returned to customers.
Policy citations are customer-safe and returned separately.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="The customer's message")
    conversation_id: int | None = Field(None, description="Omit to start a new conversation")


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class RedactedToolCall(BaseModel):
    agent: str
    tool: str


class PolicyCitation(BaseModel):
    document_id: int
    title: str
    version: int
    topic: str
    effective_date: str
    source: str
    chunk_index: int
    snippet: str
    score: float


class ChatResponse(BaseModel):
    conversation_id: int
    reply: str
    agent: str
    trace: list[RedactedToolCall]
    usage: Usage
    cached: bool = False
    citations: list[PolicyCitation] = []


class MeResponse(BaseModel):
    id: int
    sub: str
    email: str | None
    name: str
    role: str


class OrderOut(BaseModel):
    order_id: int
    item: str
    status: str
    order_date: str
    amount: float

    model_config = {"from_attributes": True}


class ConversationSummary(BaseModel):
    id: int
    created_at: datetime
    updated_at: datetime
    last_message: str | None = None


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    agent: str | None = None
    cached: bool = False
    created_at: datetime
    citations: list[PolicyCitation] = []


class ConversationDetail(BaseModel):
    id: int
    messages: list[MessageOut]


class CaseEventOut(BaseModel):
    id: int
    transition: str
    reason: str | None = None
    created_at: datetime
    actor_id: int | None = None


class CaseOut(BaseModel):
    id: int
    kind: str
    order_id: int | None = None
    status: str
    reason: str | None = None
    ticket_id: str | None = None
    decision_reason: str | None = None
    decided_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    policy_version: int | None = None
    policy_document_id: int | None = None
    execution_status: str | None = None


class CaseDetail(CaseOut):
    events: list[CaseEventOut] = []
    order: OrderOut | None = None


class PaginatedCases(BaseModel):
    items: list[CaseOut]
    total: int
    limit: int
    offset: int


class DecisionRequest(BaseModel):
    reason: str | None = Field(
        None,
        max_length=2000,
        description="Reason for the decision (required when rejecting)",
    )


# --- reviewer-only execution visibility ---


class RefundActionOut(BaseModel):
    id: int
    status: str
    provider: str
    provider_refund_id: str | None = None
    payment_ref: str | None = None
    amount_cents: int
    currency: str
    attempts: int
    last_error: str | None = None
    idempotency_key: str
    processed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class NotificationOut(BaseModel):
    id: int
    kind: str
    status: str
    to_email: str | None = None
    attempts: int
    last_error: str | None = None
    created_at: datetime
    sent_at: datetime | None = None


class OutboxOut(BaseModel):
    id: int
    event_type: str
    status: str
    attempts: int
    last_error: str | None = None
    available_at: datetime
    processed_at: datetime | None = None


class ReviewCaseDetail(CaseDetail):
    action: RefundActionOut | None = None
    notifications: list[NotificationOut] = []
    outbox: list[OutboxOut] = []
