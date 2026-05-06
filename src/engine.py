"""Event-driven discrete simulation engine."""

import heapq
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from .models import Agent, Order, OrderState, Priority
from .graph import EnvironmentGraph
from .queue import OrderQueue
from .registry import AgentRegistry
from .scorer import Scorer
from .metrics import MetricsCollector

logger = logging.getLogger(__name__)


class EventType(Enum):
    ORDER_ARRIVES = "ORDER_ARRIVES"
    PREP_DONE = "PREP_DONE"
    DELIVERY_DONE = "DELIVERY_DONE"


@dataclass(order=True)
class Event:
    time: float
    sequence: int = field(compare=True)  # Tie-break for heap stability
    event_type: EventType = field(compare=False)
    data: dict[str, Any] = field(compare=False, default_factory=dict)


class SimulationEngine:
    """Min-heap event timeline — no time.sleep(), pure discrete-event simulation."""

    def __init__(
        self,
        queue: OrderQueue,
        registry: AgentRegistry,
        scorer: Scorer,
        metrics: MetricsCollector,
        graph: EnvironmentGraph,
    ) -> None:
        self.queue: OrderQueue = queue
        self.registry: AgentRegistry = registry
        self.scorer: Scorer = scorer
        self.metrics: MetricsCollector = metrics
        self.graph: EnvironmentGraph = graph
        self._timeline: list[Event] = []
        self._seq: int = 0

    def _schedule(self, time: float, event_type: EventType, data: dict[str, Any]) -> None:
        event = Event(time=time, sequence=self._seq, event_type=event_type, data=data)
        heapq.heappush(self._timeline, event)
        self._seq += 1

    def run(self, orders: list[Order]) -> None:
        """Load all orders as ORDER_ARRIVES events and process the full timeline."""
        # Schedule all order arrivals
        for order in orders:
            self._schedule(order.timestamp, EventType.ORDER_ARRIVES, {"order": order})

        processed: int = 0
        # Process event timeline
        while self._timeline:
            event: Event = heapq.heappop(self._timeline)

            if event.event_type == EventType.ORDER_ARRIVES:
                self._handle_order_arrives(event)
                processed += 1
            elif event.event_type == EventType.PREP_DONE:
                self._handle_prep_done(event)
            elif event.event_type == EventType.DELIVERY_DONE:
                self._handle_delivery_done(event)

        logger.info("Simulation processed %d arrival events", processed)

    def _handle_order_arrives(self, event: Event) -> None:
        order: Order = event.data["order"]
        current_time: float = event.time

        # Edge case: SLA already passed at arrival processing time
        elapsed: float = current_time - order.timestamp
        if elapsed > order.sla_minutes:
            logger.warning(
                "Order %s: SLA already passed before assignment (elapsed=%.1f, sla=%d)",
                order.order_id, elapsed, order.sla_minutes,
            )

        # Enqueue and attempt assignment
        self.queue.add(order)
        self._try_assign_from_queue(current_time)

    def _handle_prep_done(self, event: Event) -> None:
        order: Order = event.data["order"]
        agent: Agent = event.data["agent"]

        order.state = OrderState.IN_TRANSIT

        travel_time: float = self.graph.get_distance(agent.current_location, order.location)

        self._schedule(
            event.time + travel_time,
            EventType.DELIVERY_DONE,
            {"order": order, "agent": agent, "travel_time": travel_time},
        )

    def _handle_delivery_done(self, event: Event) -> None:
        order: Order = event.data["order"]
        agent: Agent = event.data["agent"]

        # Finalize order
        order.state = OrderState.DELIVERED
        order.actual_delivery_time = event.time - order.timestamp

        # Update agent state: location moves to delivery destination
        agent.current_location = order.location
        if order in agent.active_orders:
            agent.active_orders.remove(order)
        self.registry.update_availability(agent)

        # Record metrics
        self.metrics.record_delivery(order)

        # Issue 11: Immediately try to assign pending orders to this freed agent
        self._try_assign_from_queue(event.time)

    def _try_assign_from_queue(self, current_time: float) -> None:
        """Attempt to assign the highest-priority pending order to the best available agent."""
        while not self.queue.is_empty:
            available_agents: list[Agent] = self.registry.get_available()

            if not available_agents:
                logger.warning(
                    "No agents available. Queue depth: %d", self.queue.depth
                )
                break

            order: Optional[Order] = self.queue.pop_highest_priority()
            if order is None:
                break

            all_agents: list[Agent] = self.registry.get_all()

            # Score all available agents with latency tracking (Issue 18)
            scored = self.scorer.score_all_candidates(order, available_agents, all_agents)

            if not scored:
                # No reachable agents — requeue and stop (Issue 17: disconnected location)
                logger.warning(
                    "Order %s: No agents can reach location %s. Requeueing.",
                    order.order_id, order.location,
                )
                self.queue.requeue(order)
                break

            best_agent: Agent = scored[0][2]

            # Apply assignment (Issue 9: atomic state updates)
            order.state = OrderState.ASSIGNED
            order.assigned_agent = best_agent.agent_id
            best_agent.active_orders.append(order)
            best_agent.cumulative_assignments += 1
            self.registry.update_availability(best_agent)

            # Schedule prep completion
            self._schedule(
                current_time + order.prep_time,
                EventType.PREP_DONE,
                {"order": order, "agent": best_agent},
            )
