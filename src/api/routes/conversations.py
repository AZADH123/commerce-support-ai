"""Customer conversation history endpoints (owner-scoped)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from src.api.deps import get_current_user, get_db
from src.api.schemas import ConversationDetail, ConversationSummary, MessageOut
from src.context import Principal
from src.services import conversations as conversations_service

router = APIRouter(prefix="/api", tags=["conversations"])


@router.get("/conversations", response_model=list[ConversationSummary])
def list_conversations(
    principal: Principal = Depends(get_current_user),
    session=Depends(get_db),
):
    items, _total = conversations_service.list_conversations(
        session, customer_id=principal.user_id
    )
    summaries = []
    for conversation in items:
        last_message = None
        if conversation.messages:
            last_message = conversation.messages[-1].content[:200]
        summaries.append(
            ConversationSummary(
                id=conversation.id,
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
                last_message=last_message,
            )
        )
    return summaries


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: int,
    principal: Principal = Depends(get_current_user),
    session=Depends(get_db),
):
    conversation = conversations_service.get_conversation_for_customer(
        session, conversation_id=conversation_id, customer_id=principal.user_id
    )
    messages = [
        MessageOut(
            id=message.id,
            role=message.role,
            content=message.content,
            agent=message.agent,
            cached=message.cached,
            created_at=message.created_at,
            citations=message.citations or [],
        )
        for message in conversation.messages
    ]
    return ConversationDetail(id=conversation.id, messages=messages)
