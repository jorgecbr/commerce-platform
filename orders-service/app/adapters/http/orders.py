"""HTTP layer for the orders resource.

The router is a translation layer and nothing else: validate the request, call
one use case, translate the result. If a business ``if`` ever appears in a
handler, that rule is in the wrong layer.
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field

from app.adapters.http.dependencies import (
    get_cancel_order,
    get_confirm_order,
    get_get_order,
    get_place_order,
)
from app.application.commands.change_order_status import CancelOrder, ConfirmOrder
from app.application.commands.place_order import (
    PlaceOrder,
    PlaceOrderLineRequest,
    PlaceOrderRequest,
)
from app.application.queries.get_order import GetOrder
from app.domain import OrderStatus

router = APIRouter(prefix="/orders", tags=["orders"])


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------


class OrderLineRequest(BaseModel):
    """One requested line as it arrives over HTTP."""

    model_config = ConfigDict(extra="forbid")

    sku: str = Field(min_length=3, max_length=32, examples=["SKU-001"])
    quantity: int = Field(ge=1, le=99, examples=[2])
    unit_price: Decimal = Field(gt=0, max_digits=12, decimal_places=2, examples=["10.00"])
    currency: str = Field(default="USD", min_length=3, max_length=3, examples=["USD"])


class CreateOrderRequest(BaseModel):
    """Body of ``POST /orders``."""

    model_config = ConfigDict(extra="forbid")

    customer_id: str = Field(min_length=1, max_length=64, examples=["customer-42"])
    lines: list[OrderLineRequest] = Field(min_length=1, max_length=50)


class MoneyResponse(BaseModel):
    """An amount in the minor unit plus its currency."""

    amount: int = Field(examples=[4550])
    currency: str = Field(examples=["USD"])


class OrderResponse(BaseModel):
    """An order as returned by the API."""

    id: UUID
    customer_id: str
    status: OrderStatus
    total: MoneyResponse
    created_at: datetime
    updated_at: datetime
    version: int


class ChangeStatusResponse(BaseModel):
    """Result of a lifecycle transition."""

    order_id: UUID
    status: OrderStatus
    occurred_at: datetime


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    body: CreateOrderRequest,
    place_order: Annotated[PlaceOrder, Depends(get_place_order)],
) -> OrderResponse:
    """Place a new order. It starts in ``pending`` and waits for stock."""
    result = await place_order.execute(
        PlaceOrderRequest(
            customer_id=body.customer_id,
            lines=tuple(
                PlaceOrderLineRequest(
                    sku=line.sku,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    currency=line.currency,
                )
                for line in body.lines
            ),
        )
    )
    return OrderResponse(
        id=result.order_id,
        customer_id=body.customer_id,
        status=OrderStatus.PENDING,
        total=MoneyResponse(amount=result.total.amount, currency=result.total.currency),
        created_at=result.created_at.value,
        updated_at=result.created_at.value,
        version=1,
    )


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: UUID,
    get_order_query: Annotated[GetOrder, Depends(get_get_order)],
) -> OrderResponse:
    """Return a single order."""
    order = await get_order_query.execute(order_id)
    return OrderResponse(
        id=order.id,
        customer_id=order.customer_id,
        status=order.status,
        total=MoneyResponse(amount=order.total.amount, currency=order.currency),
        created_at=order.created_at.value,
        updated_at=order.updated_at.value,
        version=order.version,
    )


@router.post("/{order_id}/confirm", response_model=ChangeStatusResponse)
async def confirm_order(
    order_id: UUID,
    confirm: Annotated[ConfirmOrder, Depends(get_confirm_order)],
) -> ChangeStatusResponse:
    """Confirm an order once its stock has been reserved."""
    result = await confirm.execute(order_id)
    return ChangeStatusResponse(
        order_id=result.order_id,
        status=OrderStatus.CONFIRMED,
        occurred_at=result.occurred_at.value,
    )


@router.post("/{order_id}/cancel", response_model=ChangeStatusResponse)
async def cancel_order(
    order_id: UUID,
    cancel: Annotated[CancelOrder, Depends(get_cancel_order)],
    reason: str = "cancelled by customer",
) -> ChangeStatusResponse:
    """Cancel an order. Terminal: the basket cannot be reopened."""
    result = await cancel.execute(order_id, reason=reason)
    return ChangeStatusResponse(
        order_id=result.order_id,
        status=OrderStatus.CANCELLED,
        occurred_at=result.occurred_at.value,
    )
