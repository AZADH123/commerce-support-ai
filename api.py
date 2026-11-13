"""FastAPI backend for the AI Customer Support Agent.

Entry point: ``uvicorn api:app``.

Endpoints:
    GET  /health                     liveness check (no auth)
    GET  /api/auth/config            public OIDC config for the browser PKCE flow
    GET  /api/me                     authenticated identity
    POST /chat                       main chat endpoint (authenticated, owner-scoped)
    GET  /api/orders                 customer's own orders (read-only)
    GET  /api/conversations          customer's conversation history
    GET  /api/conversations/{id}     one conversation's messages
    GET  /api/cases                  customer's refund/escalation cases
    GET  /api/cases/{id}             case detail + audit events
    GET  /api/review/cases           reviewer queue (pagination + filters)
    GET  /api/review/cases/{id}      reviewer case detail
    POST /api/review/cases/{id}/approve   reviewer approval
    POST /api/review/cases/{id}/reject    reviewer rejection
"""

import logging
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.api.routes import api_router
from src.api.routes.chat import router as chat_router
from src.logging_config import configure_logging
from src.services.exceptions import ServiceError

configure_logging()
logger = logging.getLogger("support_agent.api")

app = FastAPI(
    title="AI Customer Support Agent API",
    description=(
        "Multi-agent customer support system with OIDC authentication, "
        "owner-scoped orders/payments/conversations/cases, and durable refund review."
    ),
    version="2.0.0",
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
    logger.info(
        "request",
        extra={
            "extra_fields": {
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "latency_ms": elapsed_ms,
            }
        },
    )
    return response


@app.get("/health")
def health():
    return {"status": "ok"}


@app.exception_handler(ServiceError)
async def service_error_handler(_request: Request, exc: ServiceError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


app.include_router(chat_router)
app.include_router(api_router)
