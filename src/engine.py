"""Event-driven simulation engine with dual-mode dispatch: Greedy and Hungarian."""

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
from .adaptive import AdaptiveWeightEngine
from .hungarian import HungarianAssigner

logger = logging.getLogger(__name__)


class EventType(Enum):
    ORDER_ARRIVES = "ORDER_ARRIVES"
    PREP_DONE = "PREP_DONE"
    DELIVERY_DONE = "DELIVERY_DONE"


class DispatchMode(Enum):
    GREEDY = "greedy"
    HUNGARIAN = "hungarian"


@dataclass(order=True)
class Event:
    time: float
    sequence: int = field(compare=True)
    event_type: EventType = field(compare=False)
    data: dict[str, Any] = field(compare=False, default_factory=dict)


class SimulationEngine:
    """Min-heap event timeline with switchable dispatch strategy."""

    def __init__(
        self,
        queue: OrderQueue,
        registry: AgentRegistry,
        scorer: Scorer,
        metrics: MetricsCollector,
        graph: EnvironmentGraph,
        adaptive: Optional[AdaptiveWeightEngine] = None,
        hungarian: Optional[HungarianAssigner] = None,
        mode: DispatchMode = DispatchMode.HUNGARIAN,
    ) -> None:
        self.queue: OrderQueue = queue
        self.registry: AgentRegistry = registry
        self.scorer: Scorer = scorer
        self.metrics: MetricsCollector = metrics
        self.graph: EnvironmentGraph = graph
        self.adaptive: Optional[AdaptiveWeightEngine] = adaptive
        self.hungarian: Optional[HungarianAssigner] = hungarian
        self.mode: DispatchMode = mode
        self._timeline: list[Event] = []
        self._seq: int = 0

        # Assignment log for dashboard replay
        self.assignment_log: list[dict[str, Any]] = []

    def _schedule(self, time: float, event_type: EventType, data: dict[str, Any]) -> None:
        event = Event(time=time, sequence=self._seq, event_type=event_type, data=data)
        heapq.heappush(self._timeline, event)
        self._seq += 1

    def run(self, orders: list[Order]) -> None:
        """Load all orders as ORDER_ARRIVES events and process the full timeline."""
        for order in orders:
            self._schedule(order.timestamp, EventType.ORDER_ARRIVES, {"order": order})

        processed: int = 0
        while self._timeline:
            event: Event = heapq.heappop(self._timeline)

            if event.event_type == EventType.ORDER_ARRIVES:
                self._handle_order_arrives(event)
                processed += 1
            elif event.event_type == EventType.PREP_DONE:
                self._handle_prep_done(event)
            elif event.event_type == EventType.DELIVERY_DONE:
                self._handle_delivery_done(event)

        logger.info(
            "Simulation [%s] processed %d arrival events",
            self.mode.value, processed,
        )

    def _handle_order_arrives(self, event: Event) -> None:
        order: Order = event.data["order"]
        current_time: float = event.time

        elapsed: float = current_time - order.timestamp
        if elapsed > order.sla_minutes:
            logger.warning(
                "Order %s: SLA already passed before assignment (elapsed=%.1f, sla=%d)",
                order.order_id, elapsed, order.sla_minutes,
            )

        self.queue.add(order)
        self._dispatch(current_time)

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

        order.state = OrderState.DELIVERED
        order.actual_delivery_time = event.time - order.timestamp

        agent.current_location = order.location
        if order in agent.active_orders:
            agent.active_orders.remove(order)
        self.registry.update_availability(agent)

        # Record metrics + adaptive feedback
        self.metrics.record_delivery(order)
        was_violation: bool = order.actual_delivery_time > order.sla_minutes
        if self.adaptive:
            self.adaptive.record_delivery(was_violation)
            self.adaptive.update_queue_depth(self.queue.depth)

        self._dispatch(event.time)

    def _dispatch(self, current_time: float) -> None:
        """Route to the correct dispatch strategy."""
        # Update adaptive weights before dispatching
        if self.adaptive:
            new_weights: dict[str, float] = self.adaptive.adapt()
            self.scorer.update_weights(new_weights)

        if self.mode == DispatchMode.HUNGARIAN and self.hungarian:
            self._dispatch_hungarian(current_time)
        else:
            self._dispatch_greedy(current_time)

    # ─── HUNGARIAN BATCH MODE ─────────────────────────────────────────

    def _dispatch_hungarian(self, current_time: float) -> None:
        """Batch-assign top N orders to available agents via Hungarian algorithm."""
        while not self.queue.is_empty:
            available_agents: list[Agent] = self.registry.get_available()
            if not available_agents:
                logger.warning("No agents available. Queue depth: %d", self.queue.depth)
                break

            # Collect up to BATCH_SIZE orders
            batch_orders: list[Order] = []
            batch_size: int = min(
                HungarianAssigner.BATCH_SIZE,
                self.queue.depth,
                len(available_agents),
            )

            for _ in range(batch_size):
                order = self.queue.pop_highest_priority()
                if order:
                    batch_orders.append(order)

            if not batch_orders:
                break

            all_agents: list[Agent] = self.registry.get_all()

            # Solve optimal assignment
            assignments: list[tuple[Order, Agent]] = self.hungarian.solve(
                batch_orders,
                available_agents,
                all_agents,
                self.scorer.w,
                self.scorer.priority_multipliers,
            )

            # Track which orders were assigned
            assigned_order_ids: set[str] = set()

            for order, agent in assignments:
                self._apply_assignment(order, agent, current_time)
                assigned_order_ids.add(order.order_id)

            # Requeue unassigned orders
            for order in batch_orders:
                if order.order_id not in assigned_order_ids:
                    order.state = OrderState.PENDING
                    self.queue.requeue(order)

            # If we couldn't assign anything, stop trying
            if not assignments:
                break

    # ─── GREEDY MODE (fallback / comparison) ─────────────────────────

    def _dispatch_greedy(self, current_time: float) -> None:
        """Assign orders one-at-a-time using greedy best-agent selection."""
        while not self.queue.is_empty:
            available_agents: list[Agent] = self.registry.get_available()
            if not available_agents:
                logger.warning("No agents available. Queue depth: %d", self.queue.depth)
                break

            order: Optional[Order] = self.queue.pop_highest_priority()
            if order is None:
                break

            all_agents: list[Agent] = self.registry.get_all()
            scored = self.scorer.score_all_candidates(order, available_agents, all_agents)

            if not scored:
                logger.warning(
                    "Order %s: No agents can reach location %s. Requeueing.",
                    order.order_id, order.location,
                )
                self.queue.requeue(order)
                break

            best_agent: Agent = scored[0][2]
            self._apply_assignment(order, best_agent, current_time)

    # ─── SHARED ASSIGNMENT LOGIC ─────────────────────────────────────

    def _apply_assignment(self, order: Order, agent: Agent, current_time: float) -> None:
        """Apply an assignment: update states and schedule prep event."""
        order.state = OrderState.ASSIGNED
        order.assigned_agent = agent.agent_id
        agent.active_orders.append(order)
        agent.cumulative_assignments += 1
        self.registry.update_availability(agent)

        # Log for dashboard replay
        self.assignment_log.append({
            "time": current_time,
            "order_id": order.order_id,
            "agent_id": agent.agent_id,
            "agent_from": agent.current_location,
            "order_location": order.location,
            "priority": order.priority.value,
        })

        self._schedule(
            current_time + order.prep_time,
            EventType.PREP_DONE,
            {"order": order, "agent": agent},
        )
