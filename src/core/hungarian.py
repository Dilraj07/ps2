"""Hungarian Algorithm for global-optimal batch assignment.

Uses scipy.optimize.linear_sum_assignment to solve the bipartite matching
problem: given N orders and M agents, find the assignment that maximizes
total system score (or equivalently, minimizes total cost).
"""

import logging
import time
from typing import Optional

import numpy as np
from scipy.optimize import linear_sum_assignment

from .models import Agent, Order
from .graph import EnvironmentGraph
from .delay_buffer import DelayBuffer

logger = logging.getLogger(__name__)

# Large penalty for infeasible pairings
INFEASIBLE_COST: float = 1e6


class HungarianAssigner:
    """Batch assignment using the Hungarian Algorithm.

    Instead of greedy one-at-a-time assignment, collects up to BATCH_SIZE
    pending orders + all available agents, builds a cost matrix, and solves
    the optimal matching globally.
    """

    BATCH_SIZE: int = 5  # Max orders per batch

    def __init__(
        self,
        graph: EnvironmentGraph,
        delay_buffer: DelayBuffer,
    ) -> None:
        self.graph: EnvironmentGraph = graph
        self.delay_buffer: DelayBuffer = delay_buffer
        # Performance tracking
        self.total_batches: int = 0
        self.total_batch_time_ms: float = 0.0

    def build_cost_matrix(
        self,
        orders: list[Order],
        agents: list[Agent],
        all_agents: list[Agent],
        weights: dict[str, float],
        priority_multipliers: dict[str, float],
    ) -> np.ndarray:
        """Build an N×M cost matrix where C[i][j] is the cost (negative score)
        of assigning order i to agent j.

        The Hungarian algorithm minimizes total cost, so we negate the scores.
        Infeasible pairings (unreachable, etc.) get a huge penalty.
        """
        import math

        n_orders: int = len(orders)
        n_agents: int = len(agents)

        # Square matrix (pad smaller dimension)
        size: int = max(n_orders, n_agents)
        cost_matrix: np.ndarray = np.full((size, size), INFEASIBLE_COST)

        max_assignments: int = max(
            (a.cumulative_assignments for a in all_agents), default=1
        )
        if max_assignments == 0:
            max_assignments = 1

        for i, order in enumerate(orders):
            for j, agent in enumerate(agents):
                # Get buffered travel time (traffic-aware)
                travel_time: float = self.delay_buffer.get_buffered_travel_time(
                    agent.current_location, order.location
                )

                if travel_time == float("inf"):
                    cost_matrix[i][j] = INFEASIBLE_COST
                    continue

                est_delivery_time: float = order.prep_time + travel_time

                # Travel score
                travel_score: float = max(0.0, 1.0 - (est_delivery_time / 60.0))

                # SLA score with exponential penalty
                sla_margin: float = order.sla_minutes - est_delivery_time
                if sla_margin >= 10.0:
                    sla_score: float = 1.0
                elif sla_margin >= 0.0:
                    sla_score = 0.5 + (sla_margin / 20.0)
                else:
                    sla_score = max(-2.0, 0.5 * math.exp(sla_margin / 5.0))

                # Inflate SLA risk for high-delay routes
                risk_factor: float = self.delay_buffer.get_risk_factor(
                    agent.current_location, order.location
                )
                if risk_factor > 0.5:
                    sla_score *= (1.0 - 0.15 * risk_factor)

                # Fairness score
                fairness_score: float = 1.0 - (agent.cumulative_assignments / max_assignments)

                # Rating score
                rating_score: float = agent.rating - 4.0

                # Weighted combination
                base_score: float = (
                    weights.get("sla", 0.4) * sla_score
                    + weights.get("travel", 0.3) * travel_score
                    + weights.get("fairness", 0.2) * fairness_score
                    + weights.get("rating", 0.1) * rating_score
                )

                # Priority multiplier
                mult: float = priority_multipliers.get(order.priority.value, 1.0)
                final_score: float = base_score * mult

                # Negate for minimization
                cost_matrix[i][j] = -final_score

        return cost_matrix

    def solve(
        self,
        orders: list[Order],
        agents: list[Agent],
        all_agents: list[Agent],
        weights: dict[str, float],
        priority_multipliers: dict[str, float],
    ) -> list[tuple[Order, Agent]]:
        """Run Hungarian algorithm and return optimal (order, agent) pairings.

        Only returns pairings that are feasible (not infeasible-cost).
        """
        if not orders or not agents:
            return []

        start: float = time.perf_counter()

        cost_matrix: np.ndarray = self.build_cost_matrix(
            orders, agents, all_agents, weights, priority_multipliers
        )

        row_ind, col_ind = linear_sum_assignment(cost_matrix)

        assignments: list[tuple[Order, Agent]] = []
        for r, c in zip(row_ind, col_ind):
            if r < len(orders) and c < len(agents):
                if cost_matrix[r][c] < INFEASIBLE_COST * 0.5:
                    assignments.append((orders[r], agents[c]))

        elapsed_ms: float = (time.perf_counter() - start) * 1000.0
        self.total_batches += 1
        self.total_batch_time_ms += elapsed_ms

        logger.debug(
            "Hungarian batch: %d orders × %d agents → %d assignments in %.2fms",
            len(orders), len(agents), len(assignments), elapsed_ms,
        )

        return assignments

    @property
    def avg_batch_time_ms(self) -> float:
        if self.total_batches == 0:
            return 0.0
        return self.total_batch_time_ms / self.total_batches
