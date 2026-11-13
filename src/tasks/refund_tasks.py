"""Taskiq tasks: refund execution and notification delivery."""

from __future__ import annotations

from src.backend import db
from src.integrations.email import get_email_adapter
from src.integrations.payments import get_payment_adapter
from src.services.notifications import send_notification
from src.services.refund_execution import execute_action
from src.tasks.broker import broker


@broker.task
async def execute_refund_task(case_id: int) -> None:
    session = db.get_session()
    try:
        execute_action(session, case_id=case_id, adapter=get_payment_adapter())
    finally:
        session.close()


@broker.task
async def send_notification_task(notification_id: int) -> None:
    session = db.get_session()
    try:
        send_notification(session, notification_id=notification_id, adapter=get_email_adapter())
    finally:
        session.close()
