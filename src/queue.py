"""Three-tier priority queue for order dispatch."""

from collections import deque
from typing import Optional

from .models import Order, Priority, OrderState


class OrderQueue:
    """Separate FIFO queues per priority level — no sorting overhead."""

    def __init__(self) -> None:
        self._high: deque[Order] = deque()
        self._normal: deque[Order] = deque()
        self._low: deque[Order] = deque()

    def add(self, order: Order) -> None:
        """Enqueue order at the back of its priority line."""
        if order.state != OrderState.PENDING:
            return
        q = self._get_queue(order.priority)
        q.append(order)

    def pop_highest_priority(self) -> Optional[Order]:
        """Dequeue the front order from the highest non-empty priority line."""
        if self._high:
            return self._high.popleft()
        if self._normal:
            return self._normal.popleft()
        if self._low:
            return self._low.popleft()
        return None

    def requeue(self, order: Order) -> None:
        """Place order back at the front of its priority line (preserves place)."""
        q = self._get_queue(order.priority)
        q.appendleft(order)

    @property
    def depth(self) -> int:
        """Total number of pending orders across all priority levels."""
        return len(self._high) + len(self._normal) + len(self._low)

    @property
    def is_empty(self) -> bool:
        return self.depth == 0

    def _get_queue(self, priority: Priority) -> deque:
        if priority == Priority.HIGH:
            return self._high
        if priority == Priority.NORMAL:
            return self._normal
        return self._low
