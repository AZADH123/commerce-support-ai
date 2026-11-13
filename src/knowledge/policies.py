"""Policy ingestion and retrieval with structured citations.

Policies are versioned documents with an effective date and source. Only the
active (highest effective version) document per (store, topic) is retrievable.
Retrieved text is treated as untrusted content by the FAQ agent; eligibility and
other business rules remain in ``src.services.cases`` and are never decided by
retrieved text.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select

from src.backend import constants as C
from src.backend.models import PolicyChunk, PolicyDocument
from src.knowledge.embeddings import Embedder, get_embedder

STORE_DEFAULT = "default"

# Sample store policies. Refund has two versions to exercise version selection.
SAMPLE_POLICIES = [
    {
        "store": STORE_DEFAULT,
        "topic": C.POLICY_TOPIC_SHIPPING,
        "title": "Shipping policy",
        "version": 1,
        "effective_date": date(2026, 1, 1),
        "source": "Store Operations Handbook 2026, §2 Shipping (v1)",
        "content": (
            "Standard shipping takes 3-5 business days. Expedited shipping (1-2 business days) "
            "is available at checkout. Orders over $50 ship free within the contiguous store region. "
            "Tracking information is emailed as soon as a shipment leaves the warehouse."
        ),
    },
    {
        "store": STORE_DEFAULT,
        "topic": C.POLICY_TOPIC_CANCELLATION,
        "title": "Cancellation policy",
        "version": 1,
        "effective_date": date(2026, 1, 1),
        "source": "Store Operations Handbook 2026, §3 Cancellations (v1)",
        "content": (
            "Orders can be cancelled free of charge before they ship. Once an order has shipped, "
            "it must be returned instead of cancelled. Cancellations are confirmed by email and the "
            "authorization is released within 1 business day."
        ),
    },
    {
        "store": STORE_DEFAULT,
        "topic": C.POLICY_TOPIC_RETURN,
        "title": "Return policy",
        "version": 1,
        "effective_date": date(2026, 1, 1),
        "source": "Store Operations Handbook 2026, §4 Returns (v1)",
        "content": (
            "Items can be returned within 30 days of delivery for a full refund, provided they are "
            "unused and in their original packaging. Return shipping is free for damaged or incorrect "
            "items. Refunds for returns are processed after the item is received and inspected."
        ),
    },
    {
        "store": STORE_DEFAULT,
        "topic": C.POLICY_TOPIC_REFUND,
        "title": "Refund policy",
        "version": 1,
        "effective_date": date(2026, 1, 1),
        "source": "Store Operations Handbook 2026, §5 Refunds (v1)",
        "content": (
            "Refunds are issued to the original payment method within 5-7 business days of approval. "
            "Only delivered orders qualify for a refund. A refund request is reviewed by a support "
            "specialist before any money is returned."
        ),
    },
    {
        "store": STORE_DEFAULT,
        "topic": C.POLICY_TOPIC_REFUND,
        "title": "Refund policy",
        "version": 2,
        "effective_date": date(2026, 6, 1),
        "source": "Store Operations Handbook 2026, §5 Refunds (v2, effective 2026-06-01)",
        "content": (
            "Refunds are issued to the original payment method within 3-5 business days after approval. "
            "Only delivered orders qualify. Damaged items may qualify for a full refund including shipping. "
            "Every refund is reviewed by a support specialist before execution and is sent to the payment "
            "provider in the original currency."
        ),
    },
    {
        "store": STORE_DEFAULT,
        "topic": C.POLICY_TOPIC_ESCALATION,
        "title": "Escalation policy",
        "version": 1,
        "effective_date": date(2026, 1, 1),
        "source": "Store Operations Handbook 2026, §6 Escalations (v1)",
        "content": (
            "Unresolved, abusive, or high-risk requests are escalated to a human support specialist. "
            "Customers receive a ticket reference and a follow-up within one business day. You can also "
            "reach human support at support@example.com, Monday to Friday, 9am-6pm."
        ),
    },
]


@dataclass
class RetrievedChunk:
    document_id: int
    title: str
    version: int
    topic: str
    effective_date: date
    source: str
    chunk_index: int
    content: str
    score: float

    def citation(self) -> dict:
        snippet = self.content if len(self.content) <= 300 else self.content[:297] + "…"
        return {
            "document_id": self.document_id,
            "title": self.title,
            "version": self.version,
            "topic": self.topic,
            "effective_date": self.effective_date.isoformat(),
            "source": self.source,
            "chunk_index": self.chunk_index,
            "snippet": snippet,
            "score": round(self.score, 4),
        }


def chunk_text(content: str, max_chars: int = 420) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if not current:
            current = paragraph
        elif len(current) + 1 + len(paragraph) <= max_chars:
            current = f"{current}\n{paragraph}"
        else:
            chunks.append(current)
            current = paragraph
    if current:
        chunks.append(current)

    result: list[str] = []
    for chunk in chunks:
        if len(chunk) <= max_chars:
            result.append(chunk)
            continue
        buffer = ""
        for sentence in re.split(r"(?<=[.!?])\s+", chunk):
            if not buffer:
                buffer = sentence
            elif len(buffer) + 1 + len(sentence) <= max_chars:
                buffer = f"{buffer} {sentence}"
            else:
                result.append(buffer)
                buffer = sentence
        if buffer:
            result.append(buffer)
    return result


def ingest_policies(session, embedder: Embedder | None = None, *, force: bool = False) -> dict:
    """Repeatable ingestion: one document per (store, topic, version)."""
    embedder = embedder or get_embedder()
    documents = 0
    chunks = 0
    today = date.today()

    for spec in SAMPLE_POLICIES:
        document = session.execute(
            select(PolicyDocument).where(
                PolicyDocument.store == spec["store"],
                PolicyDocument.topic == spec["topic"],
                PolicyDocument.version == spec["version"],
            )
        ).scalar_one_or_none()

        if (
            document is not None
            and not force
            and document.content == spec["content"]
            and document.chunks
        ):
            continue

        if document is None:
            document = PolicyDocument(
                store=spec["store"],
                topic=spec["topic"],
                title=spec["title"],
                version=spec["version"],
                effective_date=spec["effective_date"],
                source=spec["source"],
                content=spec["content"],
                active=False,
            )
            session.add(document)
            session.flush()
            documents += 1
        else:
            document.title = spec["title"]
            document.effective_date = spec["effective_date"]
            document.source = spec["source"]
            document.content = spec["content"]
            session.flush()

        for chunk in list(document.chunks):
            session.delete(chunk)
        session.flush()

        texts = chunk_text(document.content)
        vectors = embedder.embed(texts)
        for index, (text, vector) in enumerate(zip(texts, vectors)):
            session.add(
                PolicyChunk(
                    document_id=document.id,
                    chunk_index=index,
                    content=text,
                    embedding=vector,
                )
            )
            chunks += 1
        session.flush()

    # Activate the highest effective version per (store, topic).
    pairs = session.execute(select(PolicyDocument.store, PolicyDocument.topic).distinct()).all()
    for store, topic in pairs:
        documents_for_topic = list(
            session.execute(
                select(PolicyDocument).where(
                    PolicyDocument.store == store, PolicyDocument.topic == topic
                )
            ).scalars()
        )
        effective = [d for d in documents_for_topic if d.effective_date <= today]
        active = max(effective, key=lambda d: d.version) if effective else None
        for candidate in documents_for_topic:
            candidate.active = candidate is active

    session.commit()
    return {"documents": documents, "chunks": chunks}


def active_document(session, *, store: str, topic: str) -> PolicyDocument | None:
    return session.execute(
        select(PolicyDocument)
        .where(
            PolicyDocument.store == store,
            PolicyDocument.topic == topic,
            PolicyDocument.active.is_(True),
            PolicyDocument.effective_date <= date.today(),
        )
        .order_by(PolicyDocument.version.desc())
    ).scalars().first()


def infer_topic(question: str) -> str | None:
    text = question.lower()
    if "refund" in text or "money back" in text:
        return C.POLICY_TOPIC_REFUND
    if "return" in text:
        return C.POLICY_TOPIC_RETURN
    if "cancel" in text:
        return C.POLICY_TOPIC_CANCELLATION
    if "ship" in text or "delivery" in text or "deliver" in text or "track" in text:
        return C.POLICY_TOPIC_SHIPPING
    if "escalat" in text or "manager" in text or "human" in text or "support@example.com" in text:
        return C.POLICY_TOPIC_ESCALATION
    return None


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def retrieve_policy(
    session,
    *,
    store: str,
    query: str,
    topic: str | None = None,
    top_k: int = 3,
    embedder: Embedder | None = None,
) -> list[RetrievedChunk]:
    embedder = embedder or get_embedder()
    stmt = select(PolicyDocument).where(
        PolicyDocument.store == store,
        PolicyDocument.active.is_(True),
        PolicyDocument.effective_date <= date.today(),
    )
    if topic:
        stmt = stmt.where(PolicyDocument.topic == topic)
    documents = list(session.execute(stmt).scalars())

    candidates: list[tuple[PolicyDocument, PolicyChunk]] = []
    for document in documents:
        for chunk in document.chunks:
            if chunk.embedding:
                candidates.append((document, chunk))
    if not candidates:
        return []

    query_vector = embedder.embed([query])[0]
    scored = [
        (_cosine(query_vector, chunk.embedding or []), document, chunk)
        for document, chunk in candidates
    ]
    scored.sort(key=lambda item: item[0], reverse=True)

    results: list[RetrievedChunk] = []
    for score, document, chunk in scored[:top_k]:
        results.append(
            RetrievedChunk(
                document_id=document.id,
                title=document.title,
                version=document.version,
                topic=document.topic,
                effective_date=document.effective_date,
                source=document.source,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                score=score,
            )
        )
    return results
