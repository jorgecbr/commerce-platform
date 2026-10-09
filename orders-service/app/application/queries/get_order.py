"""Query side: read operations.

Separate from the commands on purpose. A command goes through the aggregate
because it changes state and must respect every invariant. A query only reads,
so it is free to use whatever shape is fastest to query — which, once the
read model lands, is a flat row rather than a rehydrated aggregate.
"""

from app.application.ports import OrderRepository
from app.domain import Order, OrderId, OrderNotFoundError


class GetOrder:
    """Load a single order."""

    def __init__(self, *, orders: OrderRepository) -> None:
        self._orders = orders

    async def execute(self, order_id: OrderId) -> Order:
        """Return the order, or raise when it does not exist."""
        order = await self._orders.get_by_id(order_id)
        if order is None:
            raise OrderNotFoundError(f"order-not-found: {order_id}")
        return order
