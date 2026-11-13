"""phase 2: refund execution, outbox, webhooks, notifications, policy KB

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-13

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

EMBEDDING_DIM = 384


def _embedding_type():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        from pgvector.sqlalchemy import Vector

        return Vector(EMBEDDING_DIM)
    return sa.JSON()


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    if is_postgres:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # --- payments: trusted provider reference, amount currency ---
    op.add_column("payments", sa.Column("provider", sa.String(length=20), nullable=False, server_default="local"))
    op.add_column("payments", sa.Column("provider_payment_id", sa.String(length=255), nullable=True))
    op.add_column("payments", sa.Column("currency", sa.String(length=8), nullable=False, server_default="usd"))

    # --- messages: customer-safe policy citations ---
    op.add_column("messages", sa.Column("citations", sa.JSON(), nullable=True))

    # --- policy knowledge base (created before cases references it) ---
    op.create_table(
        "policy_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store", sa.String(length=60), nullable=False, server_default="default"),
        sa.Column("topic", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=300), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("store", "topic", "version", name="uq_policy_store_topic_version"),
    )
    op.create_index("ix_policy_documents_store", "policy_documents", ["store"])
    op.create_index("ix_policy_documents_topic", "policy_documents", ["topic"])
    op.create_index("ix_policy_documents_active", "policy_documents", ["active"])

    op.create_table(
        "policy_chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("policy_documents.id"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", _embedding_type(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_policy_chunk_index"),
    )
    op.create_index("ix_policy_chunks_document_id", "policy_chunks", ["document_id"])

    # --- cases: policy provenance + execution linkage ---
    # SQLite cannot ALTER-in a foreign key; the FK matters on PostgreSQL (the
    # migration target). Tests build the schema with create_all, which includes it.
    if is_postgres:
        op.add_column(
            "cases",
            sa.Column(
                "policy_document_id", sa.Integer(), sa.ForeignKey("policy_documents.id"), nullable=True
            ),
        )
    else:
        op.add_column("cases", sa.Column("policy_document_id", sa.Integer(), nullable=True))
    op.add_column("cases", sa.Column("policy_version", sa.Integer(), nullable=True))

    # --- refund actions: one per case, stable idempotency key ---
    op.create_table(
        "refund_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.order_id"), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("payment_id", sa.Integer(), sa.ForeignKey("payments.payment_id"), nullable=True),
        sa.Column("provider", sa.String(length=20), nullable=False, server_default="local"),
        sa.Column("payment_ref", sa.String(length=255), nullable=True),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="usd"),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="PENDING"),
        sa.Column("provider_refund_id", sa.String(length=255), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("case_id", name="uq_refund_action_case"),
        sa.UniqueConstraint("idempotency_key", name="uq_refund_action_idempotency"),
    )
    op.create_index("ix_refund_actions_case_id", "refund_actions", ["case_id"])
    op.create_index("ix_refund_actions_order_id", "refund_actions", ["order_id"])
    op.create_index("ix_refund_actions_customer_id", "refund_actions", ["customer_id"])
    op.create_index("ix_refund_actions_status", "refund_actions", ["status"])
    op.create_index("ix_refund_actions_idempotency_key", "refund_actions", ["idempotency_key"])

    # --- transactional outbox ---
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("aggregate_type", sa.String(length=40), nullable=False),
        sa.Column("aggregate_id", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_outbox_events_event_type", "outbox_events", ["event_type"])
    op.create_index("ix_outbox_events_aggregate_id", "outbox_events", ["aggregate_id"])
    op.create_index("ix_outbox_events_status", "outbox_events", ["status"])
    op.create_index("ix_outbox_status_available", "outbox_events", ["status", "available_at"])

    # --- deduplicated webhook log ---
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="RECEIVED"),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("provider", "event_id", name="uq_webhook_provider_event"),
    )

    # --- durable notification delivery ---
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False, server_default="email"),
        sa.Column("to_email", sa.String(length=255), nullable=True),
        sa.Column("subject", sa.String(length=300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_notifications_case_id", "notifications", ["case_id"])
    op.create_index("ix_notifications_customer_id", "notifications", ["customer_id"])
    op.create_index("ix_notifications_status", "notifications", ["status"])

    # pgvector ANN index (PostgreSQL only).
    if is_postgres:
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_policy_chunks_embedding "
            f"ON policy_chunks USING hnsw (embedding vector_cosine_ops)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_policy_chunks_embedding")

    op.drop_table("notifications")
    op.drop_table("webhook_events")
    op.drop_table("outbox_events")
    op.drop_table("refund_actions")

    op.drop_column("cases", "policy_version")
    op.drop_column("cases", "policy_document_id")

    op.drop_table("policy_chunks")
    op.drop_table("policy_documents")

    op.drop_column("messages", "citations")

    op.drop_column("payments", "currency")
    op.drop_column("payments", "provider_payment_id")
    op.drop_column("payments", "provider")
