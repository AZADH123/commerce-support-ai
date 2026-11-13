import threading

import pytest
from sqlalchemy import create_engine, select

from src.backend import db
from src.backend.models import Case, CaseEvent, User
from src.backend.seed import DEMO_SUBS, seed
from src.services import cases as cases_service
from src.services import escalation as escalation_service
from src.services.exceptions import Conflict, Forbidden, NotFound, Unprocessable


def _user_id(session, key: str) -> int:
    return session.execute(select(User).where(User.sub == DEMO_SUBS[key])).scalar_one().id


def test_request_refund_creates_pending_case(seeded):
    s = db.get_session()
    try:
        alice = _user_id(s, "alice")
        case = cases_service.request_refund(s, customer_id=alice, order_id=1001, reason="broken")
        assert case.status == "PENDING_REVIEW"
        assert [e.transition for e in case.events] == ["CREATED"]
    finally:
        s.close()


def test_request_refund_rejects_other_customers_order(seeded):
    s = db.get_session()
    try:
        alice = _user_id(s, "alice")
        with pytest.raises(Forbidden):
            cases_service.request_refund(s, customer_id=alice, order_id=1004, reason="not mine")
    finally:
        s.close()


def test_request_refund_rejects_ineligible_status(seeded):
    s = db.get_session()
    try:
        alice = _user_id(s, "alice")
        with pytest.raises(Unprocessable):
            cases_service.request_refund(s, customer_id=alice, order_id=1002, reason="shipped")
    finally:
        s.close()


def test_request_refund_rejects_missing_order(seeded):
    s = db.get_session()
    try:
        alice = _user_id(s, "alice")
        with pytest.raises(NotFound):
            cases_service.request_refund(s, customer_id=alice, order_id=9999, reason="nope")
    finally:
        s.close()


def test_request_refund_duplicate_is_conflict(seeded):
    s = db.get_session()
    try:
        alice = _user_id(s, "alice")
        cases_service.request_refund(s, customer_id=alice, order_id=1001, reason="first")
        with pytest.raises(Conflict):
            cases_service.request_refund(s, customer_id=alice, order_id=1001, reason="second")
    finally:
        s.close()


def test_approve_then_repeat_yields_one_event(seeded, case_factory):
    case = case_factory("alice", 1001, "broken")
    s = db.get_session()
    try:
        reviewer = _user_id(s, "reviewer")
        approved = cases_service.approve(s, case_id=case.id, reviewer_id=reviewer, reason="ok")
        assert approved.status == "APPROVED"

        again = cases_service.approve(s, case_id=case.id, reviewer_id=reviewer, reason="again")
        assert again.status == "APPROVED"

        events = s.execute(select(CaseEvent).where(CaseEvent.case_id == case.id)).scalars().all()
        transitions = [e.transition for e in events]
        assert transitions.count("APPROVED") == 1
        assert transitions == ["CREATED", "APPROVED"]
    finally:
        s.close()


def test_reject_flow(seeded, case_factory):
    case = case_factory("alice", 1001, "broken")
    s = db.get_session()
    try:
        reviewer = _user_id(s, "reviewer")
        rejected = cases_service.reject(s, case_id=case.id, reviewer_id=reviewer, reason="not eligible")
        assert rejected.status == "REJECTED"
        assert rejected.decision_reason == "not eligible"
        assert rejected.decided_by == reviewer
    finally:
        s.close()


def test_cannot_decide_escalation_case(seeded):
    s = db.get_session()
    try:
        alice = _user_id(s, "alice")
        reviewer = _user_id(s, "reviewer")
        case = escalation_service.escalate(s, customer_id=alice, reason="unresolved", context="x")
        with pytest.raises(Unprocessable):
            cases_service.approve(s, case_id=case.id, reviewer_id=reviewer, reason="nope")
    finally:
        s.close()


def test_escalation_case_is_persisted(seeded):
    s = db.get_session()
    try:
        alice = _user_id(s, "alice")
        case = escalation_service.escalate(s, customer_id=alice, reason="needs human", context="order 1001")
        assert case.status == "OPEN"
        assert case.kind == "escalation"
        assert case.ticket_id
    finally:
        s.close()


def _make_file_engine(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'race.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    from src.backend.db import init_db, get_session_factory

    init_db(engine)
    factory = get_session_factory(engine)
    s = factory()
    seed(s)
    s.close()
    return engine, factory


def test_concurrent_approve_yields_one_event(tmp_path):
    """Two reviewers approve simultaneously; exactly one APPROVED event results."""
    engine, factory = _make_file_engine(tmp_path)

    setup = factory()
    alice = _user_id(setup, "alice")
    reviewer = _user_id(setup, "reviewer")
    case = cases_service.request_refund(setup, customer_id=alice, order_id=1001, reason="broken")
    case_id = case.id
    setup.close()

    results = []
    errors = []

    def approve_worker():
        session = factory()
        try:
            results.append(cases_service.approve(session, case_id=case_id, reviewer_id=reviewer, reason="ok"))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            session.close()

    threads = [threading.Thread(target=approve_worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert {r.status for r in results} == {"APPROVED"}

    check = factory()
    events = check.execute(select(CaseEvent).where(CaseEvent.case_id == case_id)).scalars().all()
    check.close()
    assert [e.transition for e in events].count("APPROVED") == 1
    engine.dispose()
