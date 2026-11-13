from langchain_core.tools import tool

from src import tools as backend_tools
from src.agents.base import run_tool_agent


@tool
def check_refund_eligibility(order_id: int) -> dict:
    """Check whether the customer's order is eligible for a refund (delivered, no existing case)."""
    return backend_tools.check_refund_eligibility(order_id)


@tool
def request_refund(order_id: int, reason: str) -> dict:
    """Request a refund for the customer's delivered order. Creates a request that
    a human reviewer will approve or reject; it does not issue a refund directly."""
    return backend_tools.request_refund(order_id, reason)


@tool
def get_order_status(order_id: int) -> dict:
    """Look up the current status of the customer's order (useful before discussing a refund)."""
    return backend_tools.get_order_status(order_id)


REFUND_TOOLS = [check_refund_eligibility, request_refund, get_order_status]

SYSTEM_PROMPT = (
    "You are the Refund Agent for an e-commerce support system. "
    "Before requesting any refund, call check_refund_eligibility first. "
    "Only call request_refund if the order is eligible (delivered, no existing case). "
    "If it isn't eligible, explain why to the customer instead of requesting a refund. "
    "A refund request is submitted for human review; it is not issued automatically. "
    "Always call a tool to get real data before answering; never guess. "
    "Reply concisely and naturally to the customer."
)


def run_refund_agent(user_message: str, history: list | None = None) -> dict:
    return run_tool_agent("refund", SYSTEM_PROMPT, REFUND_TOOLS, user_message, history)
