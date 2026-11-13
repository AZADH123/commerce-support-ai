import pytest
from sqlalchemy import select

from src import context, tools
from src.backend import db
from src.backend.models import Case, User
from src.backend.seed import DEMO_SUBS
from src.context import Principal


def _principal(key: str) -> Principal:
    s = db.get_session()
    try:
        user = s.execute(select(User).where(User.sub == DEMO_SUBS[key])).scalar_one()
        return Principal(user_id=user.id, role=user.role, sub=user.sub, email=user.email, name=user.name)
    finally:
        s.close()


def _as(principal: Principal, fn, *args):
    token = context.set_principal(principal)
    try:
        return fn(*args)
    finally:
        context.reset_principal(token)


@pytest.fixture
def alice(seeded):
    return _principal("alice")


@pytest.fixture
def bob(seeded):
    return _principal("bob")


def test_tools_require_authentication(seeded):
    assert tools.get_order_status(1001) == {"error": "Not authenticated."}


def test_get_order_status_own(alice):
    assert _as(alice, tools.get_order_status, 1001) == {"order_id": 1001, "status": "delivered"}


def test_get_order_status_other_customer_is_hidden(alice):
    # 1004 belongs to bob; must look like "not found", never leak data.
    assert "error" in _as(alice, tools.get_order_status, 1004)


def test_get_order_details_own(alice):
    result = _as(alice, tools.get_order_details, 1001)
    assert result["item"] == "Wireless Headphones"
    assert result["status"] == "delivered"


def test_track_shipment_delivered(alice):
    assert _as(alice, tools.track_shipment, 1001)["tracking_message"] == "Delivered."


def test_refund_eligibility_delivered(alice):
    result = _as(alice, tools.check_refund_eligibility, 1001)
    assert result["eligible"] is True


def test_refund_eligibility_not_delivered(alice):
    result = _as(alice, tools.check_refund_eligibility, 1002)  # shipped
    assert result["eligible"] is False
    assert "delivered" in result["reason"]


def test_refund_eligibility_other_customer_hidden(alice):
    assert "error" in _as(alice, tools.check_refund_eligibility, 1004)


def test_request_refund_succeeds_when_eligible(alice):
    result = _as(alice, tools.request_refund, 1001, "Item not as described")
    assert result["success"] is True
    assert result["status"] == "PENDING_REVIEW"
    assert result["case_id"] > 0
    # Eligibility flips after the request is recorded.
    assert _as(alice, tools.check_refund_eligibility, 1001)["eligible"] is False


def test_request_refund_refuses_when_not_delivered(alice):
    result = _as(alice, tools.request_refund, 1002, "Changed my mind")
    assert result["success"] is False
    assert "delivered" in result["reason"]


def test_request_refund_refuses_other_customer_order(alice):
    result = _as(alice, tools.request_refund, 1004, "Mine now")
    assert result["success"] is False
    assert "does not belong" in result["reason"]


def test_request_refund_duplicate_active(alice):
    first = _as(alice, tools.request_refund, 1001, "First request")
    assert first["success"] is True
    second = _as(alice, tools.request_refund, 1001, "Second request")
    assert second["success"] is False
    assert "already" in second["reason"]


def test_get_payment_status_own(alice):
    assert _as(alice, tools.get_payment_status, 1003)["status"] == "pending"


def test_get_payment_status_other_hidden(alice):
    assert "error" in _as(alice, tools.get_payment_status, 1004)


def test_answer_faq(seeded):
    result = tools.answer_faq("How long does shipping take?")
    assert "3-5 business days" in result["answer"]
    # No policies ingested: missing evidence yields no citations, never a crash.
    assert result["citations"] == []


def test_escalate_persists_case_when_authenticated(alice):
    result = _as(alice, tools.escalate_to_human, "cannot resolve", "order 9999")
    assert result["escalated"] is True
    assert result["ticket_id"]
    s = db.get_session()
    try:
        case = s.execute(select(Case).where(Case.ticket_id == result["ticket_id"])).scalar_one()
        assert case.kind == "escalation"
        assert case.status == "OPEN"
    finally:
        s.close()
