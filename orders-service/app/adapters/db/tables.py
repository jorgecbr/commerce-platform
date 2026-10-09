"""SQLAlchemy table definitions.

Kept separate from the domain on purpose: the aggregate knows nothing about
columns, and these tables know nothing about invariants. The translation
between the two lives in ``mappers.py``.

The schema stores the *write model*: the order aggregate exactly as the domain
sees it. The read model used by the query side lands on its own tables so that
list queries never touch this shape.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for every table in this service."""


class OrderRow(Base):
    """Aggregate root, one row per order."""

    __tablename__ = "orders"
    __table_args__ = (
        # The version column is what makes optimistic concurrency possible:
        # the UPDATE carries "AND version = :expected" and a zero row count
        # means somebody else changed the row first.
        CheckConstraint("version >= 1", name="ck_orders_version_positive"),
        CheckConstraint("total_amount >= 0", name="ck_orders_total_non_negative"),
        Index("ix_orders_customer_created", "customer_id", "created_at"),
        Index("ix_orders_status_created", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(postgresql.UUID(as_uuid=True), primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    total_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    lines: Mapped[list["OrderLineRow"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", lazy="selectin"
    )


class OrderLineRow(Base):
    """Order line. Kept as rows because the aggregate owns a collection."""

    __tablename__ = "order_lines"
    __table_args__ = (
        # A duplicated SKU would mean two prices for one product, which the
        # domain already forbids. The database repeats the rule so a direct
        # SQL write cannot break the invariant behind its back.
        UniqueConstraint("order_id", "sku", name="uq_order_lines_order_sku"),
        CheckConstraint("quantity > 0", name="ck_order_lines_quantity_positive"),
        CheckConstraint("unit_price_amount >= 0", name="ck_order_lines_price_non_negative"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    sku: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    unit_price_currency: Mapped[str] = mapped_column(String(3), nullable=False)

    order: Mapped[OrderRow] = relationship(back_populates="lines")


class OutboxRow(Base):
    """Transactional outbox.

    An event is inserted here in the *same transaction* as the state change it
    describes. A separate relay then moves it to the broker. This is what
    removes the dual write problem: the order and its event either both
    survive a crash or neither does.
    """

    __tablename__ = "outbox_events"
    __table_args__ = (
        # The relay polls unpublished rows; this partial index keeps that scan
        # cheap no matter how large the table grows.
        Index(
            "ix_outbox_unpublished",
            "occurred_at",
            postgresql_where="published_at IS NULL",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(postgresql.JSONB, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(512), nullable=True)


class ProcessedMessageRow(Base):
    """Consumer-side idempotency ledger (the inbox).

    Before handling an incoming event we insert its id. A duplicate insert
    raises, which is how the consumer detects that it has already processed
    the message: at-least-once delivery plus a unique key gives the effect of
    exactly-once processing.
    """

    __tablename__ = "processed_messages"
    __table_args__ = (UniqueConstraint("consumer", "message_id", name="uq_processed_consumer_message"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    consumer: Mapped[str] = mapped_column(String(64), nullable=False)
    message_id: Mapped[str] = mapped_column(String(64), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
