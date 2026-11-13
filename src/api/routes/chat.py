"""The main chat endpoint (kept at ``/chat``)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from langchain_core.messages import AIMessage, HumanMessage

from src import context
from src.api.deps import get_current_user, get_db
from src.api.schemas import ChatRequest, ChatResponse, RedactedToolCall, Usage
from src.context import Principal
from src.orchestrator import run_orchestrator
from src.services import conversations as conversations_service

router = APIRouter(tags=["chat"])


def _history(conversation) -> list:
    out: list = []
    for message in conversation.messages:
        if message.role == "user":
            out.append(HumanMessage(content=message.content))
        elif message.role == "assistant":
            out.append(AIMessage(content=message.content))
    return out


def _last_order_id(conversation) -> int | None:
    last = None
    for message in conversation.messages:
        for entry in message.trace or []:
            args = entry.get("args") or {}
            result = entry.get("result") or {}
            order_id = args.get("order_id")
            if order_id is None and isinstance(result, dict):
                order_id = result.get("order_id")
            if order_id is not None:
                last = order_id
    return last


def _redact_trace(trace: list) -> list[RedactedToolCall]:
    return [
        RedactedToolCall(agent=entry.get("agent", ""), tool=entry.get("tool", ""))
        for entry in (trace or [])
    ]


def _extract_citations(trace: list) -> list[dict]:
    """Collect customer-safe policy citations from tool results (deduplicated)."""
    seen: set[tuple] = set()
    citations: list[dict] = []
    for entry in trace or []:
        result = entry.get("result")
        if not isinstance(result, dict):
            continue
        for citation in result.get("citations") or []:
            if not isinstance(citation, dict):
                continue
            key = (citation.get("document_id"), citation.get("version"), citation.get("chunk_index"))
            if key in seen:
                continue
            seen.add(key)
            citations.append(citation)
    return citations


@router.post("/chat", response_model=ChatResponse)
def chat(
    req: ChatRequest,
    principal: Principal = Depends(get_current_user),
    session=Depends(get_db),
):
    # Bind the request identity and session so agent tools resolve ownership
    # from the authenticated request, not from model-generated arguments.
    session_token = context.set_session(session)
    principal_token = context.set_principal(principal)
    try:
        if req.conversation_id is not None:
            conversation = conversations_service.get_conversation_for_customer(
                session, conversation_id=req.conversation_id, customer_id=principal.user_id
            )
            history = _history(conversation)
        else:
            conversation = conversations_service.create_conversation(
                session, customer_id=principal.user_id
            )
            history = []

        context_note = ""
        last_order = _last_order_id(conversation)
        if last_order is not None:
            context_note = f"(Context: the customer was last discussing order {last_order}.)\n"
        augmented_message = context_note + req.message

        try:
            result = run_orchestrator(augmented_message, history=history)
        except Exception:  # orchestrator already retries + escalates internally
            raise HTTPException(
                status_code=502, detail="Support service unavailable; please try again later."
            ) from None

        conversations_service.add_message(
            session,
            conversation_id=conversation.id,
            role="user",
            content=req.message,
        )
        citations = _extract_citations(result["trace"])
        conversations_service.add_message(
            session,
            conversation_id=conversation.id,
            role="assistant",
            content=result["reply"],
            agent=result["agent"],
            trace=result["trace"],
            citations=citations,
            usage=result.get("usage"),
            cached=result.get("cached", False),
        )

        return ChatResponse(
            conversation_id=conversation.id,
            reply=result["reply"],
            agent=result["agent"],
            trace=_redact_trace(result["trace"]),
            usage=Usage(**(result.get("usage") or {})),
            cached=result.get("cached", False),
            citations=citations,
        )
    finally:
        context.reset_session(session_token)
        context.reset_principal(principal_token)
