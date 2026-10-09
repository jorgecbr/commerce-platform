"""Add the frozen discount to orders.

The API reported a discounted total while the row stored the gross total, so
the two could disagree. The discount is now part of the aggregate and is
persisted alongside it.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("discount_amount", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_orders_discount_within_total",
        "orders",
        "discount_amount >= 0 AND discount_amount <= total_amount",
    )


def downgrade() -> None:
    op.drop_constraint("ck_orders_discount_within_total", "orders", type_="check")
    op.drop_column("orders", "discount_amount")
