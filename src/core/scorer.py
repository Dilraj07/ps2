"""Multi-factor normalized scoring engine with delay buffer integration."""

import math
import time
import logging
from typing import Optional

from src.models.datatypes import Agent, Order, Priority
from src.utils.graph import EnvironmentGraph
from src.utils.delay_buffer import DelayBuffer

logger = logging.getLogger(__name__)


class Scorer:
    """Score agents for a given order using normalized, weighted metrics.
    
    Now integrates delay buffering for traffic-aware travel estimates
    and accepts mutable weights from the adaptive engine.
    """

    DEFAULT_WEIGHTS: dict[str, float] = {
        "sla": 0.40, "travel": 0.30, "fairness": 0.20, "rating": 0.10,
    }

    DEFAULT_PRIORITY_MULTIPLIERS: dict[str, float] = {
        "high": 1.5, "normal": 1.0, "low": 0.8,
    }

    LATENCY_TARGET_S: float = 5.0

    def __init__(
        self,
        graph: EnvironmentGraph,
        weights: Optional[dict[str, float]] = None,
        priority_multipliers: Optional[dict[str, float]] = None,
        delay_buffer: Optional[DelayBuffer] = None,
    ) -> None:
        self.graph: EnvironmentGraph = graph
        self.w: dict[str, float] = weights or self.DEFAULT_WEIGHTS.copy()
        self.priority_multipliers: dict[str, float] = (
            priority_multipliers or self.DEFAULT_PRIORITY_MULTIPLIERS.copy()
        )
        self.delay_buffer: Optional[DelayBuffer] = delay_buffer

        # Latency tracking
        self.total_decisions: int = 0
        self.total_decision_time_ms: float = 0.0
        self.max_decision_time_ms: float = 0.0

    def update_weights(self, new_weights: dict[str, float]) -> None:
        """Hot-swap weights from adaptive engine."""
        self.w = new_weights

    def _get_travel_time(self, from_loc: tuple[int, int], to_loc: tuple[int, int]) -> float:
        """Get travel time — buffered if delay_buffer is set, raw otherwise."""
        if self.delay_buffer:
            return self.delay_buffer.get_buffered_travel_time(from_loc, to_loc)
        return self.graph.get_distance(from_loc, to_loc)

    def score(self, agent: Agent, order: Order, all_agents: list[Agent]) -> float:
        """Compute composite score for assigning order to agent."""
        travel_time: float = self._get_travel_time(agent.current_location, order.location)

        if travel_time == float("inf"):
            return float("-inf")

        est_delivery_time: float = order.prep_time + travel_time

        # 1. Travel Score
        travel_score: float = max(0.0, 1.0 - (est_delivery_time / 60.0))

        # 2. SLA Score with exponential penalty
        sla_margin: float = order.sla_minutes - est_delivery_time
        if sla_margin >= 10.0:
            sla_score: float = 1.0
        elif sla_margin >= 0.0:
            sla_score = 0.5 + (sla_margin / 20.0)
        else:
            sla_score = max(-2.0, 0.5 * math.exp(sla_margin / 5.0))

        # Inflate SLA risk for routes through high-delay edges
        if self.delay_buffer:
            risk: float = self.delay_buffer.get_risk_factor(
                agent.current_location, order.location
            )
            if risk > 0.5:
                sla_score *= (1.0 - 0.15 * risk)

        # 3. Fairness Score
        max_assignments: int = max(
            (a.cumulative_assignments for a in all_agents), default=1
        )
        if max_assignments == 0:
            max_assignments = 1
        fairness_score: float = 1.0 - (agent.cumulative_assignments / max_assignments)

        # 4. Rating Score
        rating_score: float = agent.rating - 4.0

        # 5. Weighted combination
        base_score: float = (
            self.w["sla"] * sla_score
            + self.w["travel"] * travel_score
            + self.w["fairness"] * fairness_score
            + self.w["rating"] * rating_score
        )

        # 6. Priority multiplier
        multiplier: float = self.priority_multipliers.get(order.priority.value, 1.0)
        return base_score * multiplier

    def score_all_candidates(
        self, order: Order, available_agents: list[Agent], all_agents: list[Agent]
    ) -> list[tuple[float, tuple[float, str], Agent]]:
        """Score all available agents for an order (greedy mode). With latency tracking."""
        start: float = time.perf_counter()

        scored: list[tuple[float, tuple[float, str], Agent]] = []
        for agent in available_agents:
            s: float = self.score(agent, order, all_agents)
            if s == float("-inf"):
                continue
            scored.append((s, self.tiebreak_key(agent), agent))

        scored.sort(key=lambda x: (-x[0], x[1]))

        elapsed_ms: float = (time.perf_counter() - start) * 1000.0
        self.total_decisions += 1
        self.total_decision_time_ms += elapsed_ms
        if elapsed_ms > self.max_decision_time_ms:
            self.max_decision_time_ms = elapsed_ms

        if elapsed_ms > self.LATENCY_TARGET_S * 1000:
            logger.warning(
                "Decision latency %.1fms exceeds target for order %s",
                elapsed_ms, order.order_id,
            )

        return scored

    @property
    def avg_decision_time_ms(self) -> float:
        if self.total_decisions == 0:
            return 0.0
        return self.total_decision_time_ms / self.total_decisions

    @staticmethod
    def tiebreak_key(agent: Agent) -> tuple[float, str]:
        return (-agent.rating, agent.agent_id)
