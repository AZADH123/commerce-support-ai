from datetime import date

import pytest
from sqlalchemy import select

from src import tools
from src.backend import db
from src.backend.models import PolicyChunk, PolicyDocument, User
from src.backend.seed import DEMO_SUBS
from src.knowledge.embeddings import HashingEmbedder
from src.knowledge.policies import (
    SAMPLE_POLICIES,
    active_document,
    ingest_policies,
    infer_topic,
    retrieve_policy,
)
from src.services import cases as cases_service
from src.services.exceptions import Unprocessable

EMBEDDER = HashingEmbedder()


def _user_id(session, key: str) -> int:
    return session.execute(select(User).where(User.sub == DEMO_SUBS[key])).scalar_one().id


def test_ingest_is_repeatable(seeded):
    session = db.get_session()
    try:
        first = ingest_policies(session, EMBEDDER)
        assert first["documents"] == len(SAMPLE_POLICIES)

        before_docs = session.execute(select(PolicyDocument)).scalars().all()
        before_chunks = session.execute(select(PolicyChunk)).scalars().all()

        second = ingest_policies(session, EMBEDDER)
        assert second == {"documents": 0, "chunks": 0}

        after_docs = session.execute(select(PolicyDocument)).scalars().all()
        after_chunks = session.execute(select(PolicyChunk)).scalars().all()
        assert len(after_docs) == len(before_docs)
        assert len(after_chunks) == len(before_chunks)
    finally:
        session.close()


def test_active_policy_is_highest_effective_version(seeded):
    session = db.get_session()
    try:
        ingest_policies(session, EMBEDDER)
        refund = active_document(session, store="default", topic="refund")
        assert refund is not None
        assert refund.version == 2
        assert refund.effective_date == date(2026, 6, 1)

        v1 = session.execute(
            select(PolicyDocument).where(
                PolicyDocument.topic == "refund", PolicyDocument.version == 1
            )
        ).scalar_one()
        assert v1.active is False
    finally:
        session.close()


def test_retrieval_returns_structured_citations(seeded):
    session = db.get_session()
    try:
        ingest_policies(session, EMBEDDER)
        results = retrieve_policy(
            session,
            store="default",
            query="How long does shipping take?",
            topic="shipping",
            top_k=2,
            embedder=EMBEDDER,
        )
        assert results
        citation = results[0].citation()
        assert citation["version"] == 1
        assert citation["topic"] == "shipping"
        assert citation["source"].startswith("Store Operations Handbook")
        assert citation["snippet"]
        assert "3-5 business days" in results[0].content
        assert citation["effective_date"] == "2026-01-01"
    finally:
        session.close()


def test_refund_citation_uses_active_version(seeded):
    session = db.get_session()
    try:
        ingest_policies(session, EMBEDDER)
        results = retrieve_policy(
            session,
            store="default",
            query="How long does a refund take?",
            topic="refund",
            embedder=EMBEDDER,
        )
        assert results
        assert results[0].version == 2
        assert "3-5 business days" in results[0].content
    finally:
        session.close()


def test_missing_evidence_returns_no_citations(seeded):
    session = db.get_session()
    try:
        # No ingestion in this test.
        results = retrieve_policy(
            session, store="default", query="What is your shipping policy?", embedder=EMBEDDER
        )
        assert results == []
    finally:
        session.close()

    answer = tools.answer_faq("What is your shipping policy?")
    assert answer["citations"] == []
    assert "3-5 business days" in answer["answer"]  # static fallback, no evidence


def test_answer_faq_returns_citations_when_ingested(seeded):
    session = db.get_session()
    try:
        ingest_policies(session, EMBEDDER)
    finally:
        session.close()

    answer = tools.answer_faq("How long does shipping take?")
    assert answer["citations"]
    assert answer["citations"][0]["version"] == 1
    assert "3-5 business days" in answer["answer"]


def test_case_records_active_policy_version(seeded, case_factory):
    session = db.get_session()
    try:
        ingest_policies(session, EMBEDDER)
    finally:
        session.close()

    case = case_factory("alice", 1001, "broken")
    assert case.policy_version == 2
    assert case.policy_document_id is not None


def test_eligibility_stays_a_business_rule(seeded):
    session = db.get_session()
    try:
        ingest_policies(session, EMBEDDER)
        alice = _user_id(session, "alice")
        # Shipping policy text cannot make a shipped order refund-eligible.
        with pytest.raises(Unprocessable):
            cases_service.request_refund(
                session, customer_id=alice, order_id=1002, reason="policy says refunds exist"
            )
    finally:
        session.close()


def test_infer_topic():
    assert infer_topic("what is your refund policy") == "refund"
    assert infer_topic("how long does shipping take") == "shipping"
    assert infer_topic("can I cancel my order") == "cancellation"
    assert infer_topic("tell me about returns") == "return"
    assert infer_topic("I need a manager") == "escalation"
    assert infer_topic("hello there") is None
