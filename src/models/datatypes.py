"""Data models for the Smart Delivery Dispatch System."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class OrderState(Enum):
    PENDING = "PENDING"
    ASSIGNED = "ASSIGNED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"


class Priority(Enum):
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


@dataclass
class Order:
    order_id: str
    timestamp: float          # Minutes from simulation epoch
    location: tuple[int, int]
    prep_time: int            # Minutes
    priority: Priority
    sla_minutes: int          # Deadline in minutes from order arrival
    state: OrderState = OrderState.PENDING
    assigned_agent: Optional[str] = None
    actual_delivery_time: float = 0.0  # Total minutes from order arrival to delivery


@dataclass
class Agent:
    agent_id: str
    current_location: tuple[int, int]
    rating: float
    active_orders: list = field(default_factory=list)
    cumulative_assignments: int = 0

    # Class-level config — set from constraints.csv at startup
    MAX_ACTIVE_ORDERS: int = 2

    @property
    def is_available(self) -> bool:
        return len(self.active_orders) < Agent.MAX_ACTIVE_ORDERS
