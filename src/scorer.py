"""Multi-factor normalized scoring engine for agent-order assignment."""

import math
import time
import logging
from typing import Optional

from .models import Agent, Order, Priority
from .graph import EnvironmentGraph

logger = logging.getLogger(__name__)


class Scorer:
    """Score agents for a given order using normalized, weighted metrics."""

    # Default weights
    DEFAULT_WEIGHTS: dict[str, float] = {
        "sla": 0.40,
        "travel": 0.30,
        "fairness": 0.20,
        "rating": 0.10,
    }

    # Default priority multipliers
    DEFAULT_PRIORITY_MULTIPLIERS: dict[str, float] = {
        "high": 1.5,
        "normal": 1.0,
        "low": 0.8,
    }

    # Latency target (seconds) — from constraints.csv or default
    LATENCY_TARGET_S: float = 5.0

    def __init__(
        self,
        graph: EnvironmentGraph,
        weights: Optional[dict[str, float]] = None,
        priority_multipliers: Optional[dict[str, float]] = None,
    ) -> None:
        self.graph: EnvironmentGraph = graph
        self.w: dict[str, float] = weights or self.DEFAULT_WEIGHTS
        self.priority_multipliers: dict[str, float] = (
            priority_multipliers or self.DEFAULT_PRIORITY_MULTIPLIERS
        )
        # Latency tracking
        self.total_decisions: int = 0
        self.total_decision_time_ms: float = 0.0
        self.max_decision_time_ms: float = 0.0

    def score(self, agent: Agent, order: Order, all_agents: list[Agent]) -> float:
        """
        Compute a composite score for assigning `order` to `agent`.
        Returns negative infinity if the agent cannot reach the order.
        """
        travel_time: float = self.graph.get_distance(agent.current_location, order.location)

        # Unreachable — disqualify
        if travel_time == float("inf"):
            return float("-inf")

        est_delivery_time: float = order.prep_time + travel_time

        # --- 1. Travel Score: fast deliveries → score close to 1.0 ---
        travel_score: float = max(0.0, 1.0 - (est_delivery_time / 60.0))

        # --- 2. SLA Score (exponential penalty for violations) ---
        sla_margin: float = order.sla_minutes - est_delivery_time
        if sla_margin >= 10.0:
            sla_score: float = 1.0
        elif sla_margin >= 0.0:
            sla_score = 0.5 + (sla_margin / 20.0)
        else:
            # Harsh exponential penalty — drives score deep negative
            sla_score = max(-2.0, 0.5 * math.exp(sla_margin / 5.0))

        # --- 3. Fairness Score: prefer agents with fewer assignments ---
        max_assignments: int = max(
            (a.cumulative_assignments for a in all_agents), default=1
        )
        if max_assignments == 0:
            max_assignments = 1
        fairness_score: float = 1.0 - (agent.cumulative_assignments / max_assignments)

        # --- 4. Rating Score: 4.0–5.0 → 0.0–1.0 ---
        rating_score: float = agent.rating - 4.0

        # --- 5. Weighted combination ---
        base_score: float = (
            self.w["sla"] * sla_score
            + self.w["travel"] * travel_score
            + self.w["fairness"] * fairness_score
            + self.w["rating"] * rating_score
        )

        # --- 6. Priority multiplier (from constraints.csv) ---
        multiplier: float = self.priority_multipliers.get(order.priority.value, 1.0)
        return base_score * multiplier

    def score_all_candidates(
        self, order: Order, available_agents: list[Agent], all_agents: list[Agent]
    ) -> list[tuple[float, tuple[float, str], Agent]]:
        """Score all available agents for an order, with latency tracking.
        Returns sorted list of (score, tiebreak_key, agent), best first."""
        start: float = time.perf_counter()

        scored: list[tuple[float, tuple[float, str], Agent]] = []
        for agent in available_agents:
            s: float = self.score(agent, order, all_agents)
            if s == float("-inf"):
                continue
            scored.append((s, self.tiebreak_key(agent), agent))

        # Sort: highest score first, then tiebreak
        scored.sort(key=lambda x: (-x[0], x[1]))

        elapsed_ms: float = (time.perf_counter() - start) * 1000.0
        self.total_decisions += 1
        self.total_decision_time_ms += elapsed_ms
        if elapsed_ms > self.max_decision_time_ms:
            self.max_decision_time_ms = elapsed_ms

        # Log warning if latency exceeds target
        if elapsed_ms > self.LATENCY_TARGET_S * 1000:
            logger.warning(
                "Decision latency %.1fms exceeds target %.0fms for order %s",
                elapsed_ms, self.LATENCY_TARGET_S * 1000, order.order_id,
            )

        return scored

    @property
    def avg_decision_time_ms(self) -> float:
        if self.total_decisions == 0:
            return 0.0
        return self.total_decision_time_ms / self.total_decisions

    @staticmethod
    def tiebreak_key(agent: Agent) -> tuple[float, str]:
        """
        Tiebreaker: higher rating first, then lower alphabetical agent_id.
        Used as sort key — negate rating for descending order.
        """
        return (-agent.rating, agent.agent_id)
