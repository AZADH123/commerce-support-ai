"""Conversation/message persistence scoped to the owning customer."""

from __future__ import annotations

from sqlalchemy import select

from src.backend.models import Conversation, Message
from src.services.exceptions import NotFound


def create_conversation(session, *, customer_id: int) -> Conversation:
    conversation = Conversation(customer_id=customer_id)
    session.add(conversation)
    session.commit()
    return conversation


def get_conversation_for_customer(session, *, conversation_id: int, customer_id: int) -> Conversation:
    conversation = session.execute(
        select(Conversation).where(Conversation.id == conversation_id, Conversation.customer_id == customer_id)
    ).scalar_one_or_none()
    if conversation is None:
        raise NotFound(f"No conversation found with id {conversation_id}.")
    return conversation


def list_conversations(session, *, customer_id: int, limit: int = 50, offset: int = 0):
    stmt = (
        select(Conversation)
        .where(Conversation.customer_id == customer_id)
        .order_by(Conversation.updated_at.desc())
    )
    total = len(list(session.execute(stmt).scalars()))
    items = list(session.execute(stmt.limit(limit).offset(offset)).scalars())
    return items, total


def add_message(
    session,
    *,
    conversation_id: int,
    role: str,
    content: str,
    agent: str | None = None,
    trace: list | None = None,
    citations: list | None = None,
    usage: dict | None = None,
    cached: bool = False,
) -> Message:
    message = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        agent=agent,
        trace=trace,
        citations=citations,
        usage=usage,
        cached=cached,
    )
    session.add(message)
    # Keep the conversation's updated_at fresh for history ordering.
    conversation = session.get(Conversation, conversation_id)
    if conversation is not None:
        from src.backend.models import utcnow

        conversation.updated_at = utcnow()
        session.add(conversation)
    session.commit()
    return message
