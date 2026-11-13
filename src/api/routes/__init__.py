"""Aggregated API router (everything under ``/api`` plus the root ``/chat``)."""

from __future__ import annotations

from fastapi import APIRouter

from src.api.routes import auth, cases, conversations, orders, review, webhooks

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(conversations.router)
api_router.include_router(orders.router)
api_router.include_router(cases.router)
api_router.include_router(review.router)
api_router.include_router(webhooks.router)
