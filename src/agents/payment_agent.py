from langchain_core.tools import tool

from src import tools as backend_tools
from src.agents.base import run_tool_agent


@tool
def get_payment_status(order_id: int) -> dict:
    """Look up the payment status (pending/paid/refunded) for the customer's order."""
    return backend_tools.get_payment_status(order_id)


PAYMENT_TOOLS = [get_payment_status]

SYSTEM_PROMPT = (
    "You are the Payment Agent for an e-commerce support system. "
    "You can check the payment status of the customer's orders. "
    "Payments cannot be changed from chat; explain the current status to the customer. "
    "Always call a tool to get real data before answering; never guess. "
    "Reply concisely and naturally to the customer."
)


def run_payment_agent(user_message: str, history: list | None = None) -> dict:
    return run_tool_agent("payment", SYSTEM_PROMPT, PAYMENT_TOOLS, user_message, history)
