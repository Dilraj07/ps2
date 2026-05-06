"""Metrics collection using Welford's online algorithm."""

import math
import statistics
from typing import Any

from .models import Order


class WelfordStats:
    """Running mean and variance without storing all values."""

    def __init__(self) -> None:
        self.count: int = 0
        self.mean: float = 0.0
        self._m2: float = 0.0

    def update(self, value: float) -> None:
        self.count += 1
        delta: float = value - self.mean
        self.mean += delta / self.count
        delta2: float = value - self.mean
        self._m2 += delta * delta2

    @property
    def variance(self) -> float:
        if self.count < 2:
            return 0.0
        return self._m2 / (self.count - 1)

    @property
    def std_dev(self) -> float:
        return math.sqrt(self.variance)

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "mean": round(self.mean, 4),
            "variance": round(self.variance, 4),
            "std_dev": round(self.std_dev, 4),
        }


class MetricsCollector:
    """Aggregate delivery, SLA, and fairness metrics."""

    PRIORITY_KEYS: list[str] = ["high", "normal", "low"]

    def __init__(self) -> None:
        # Welford stats per priority + overall
        self.delivery_stats: dict[str, WelfordStats] = {
            k: WelfordStats() for k in self.PRIORITY_KEYS + ["all"]
        }
        # SLA counters
        self.sla_total: dict[str, int] = {k: 0 for k in self.PRIORITY_KEYS + ["all"]}
        self.sla_violations: dict[str, int] = {k: 0 for k in self.PRIORITY_KEYS + ["all"]}
        # SLA margin tracking (Issue 13: average margin = deadline - delivery_time)
        self.sla_margin_stats: dict[str, WelfordStats] = {
            k: WelfordStats() for k in self.PRIORITY_KEYS + ["all"]
        }
        # Fairness — populated at finalization
        self._agent_assignments: list[int] = []
        # Throughput tracking (Issue 19)
        self._first_delivery_time: float = float("inf")
        self._last_delivery_time: float = 0.0

    def record_delivery(self, order: Order) -> None:
        """Record a completed delivery into running stats."""
        p: str = order.priority.value
        dt: float = order.actual_delivery_time

        self.delivery_stats[p].update(dt)
        self.delivery_stats["all"].update(dt)

        self.sla_total[p] += 1
        self.sla_total["all"] += 1

        if dt > order.sla_minutes:
            self.sla_violations[p] += 1
            self.sla_violations["all"] += 1

        # SLA margin = deadline - actual delivery time (positive = met, negative = violated)
        margin: float = order.sla_minutes - dt
        self.sla_margin_stats[p].update(margin)
        self.sla_margin_stats["all"].update(margin)

        # Throughput: track simulation time span of deliveries
        if order.timestamp + dt < self._first_delivery_time:
            self._first_delivery_time = order.timestamp + dt
        if order.timestamp + dt > self._last_delivery_time:
            self._last_delivery_time = order.timestamp + dt

    def finalize_fairness(self, agents: list) -> None:
        """Compute fairness from final cumulative assignments."""
        self._agent_assignments = [a.cumulative_assignments for a in agents]

    @property
    def fairness_std_dev(self) -> float:
        if len(self._agent_assignments) < 2:
            return 0.0
        return statistics.stdev(self._agent_assignments)

    @property
    def fairness_min(self) -> int:
        return min(self._agent_assignments) if self._agent_assignments else 0

    @property
    def fairness_max(self) -> int:
        return max(self._agent_assignments) if self._agent_assignments else 0

    @property
    def fairness_range(self) -> int:
        return self.fairness_max - self.fairness_min

    @property
    def throughput_orders_per_minute(self) -> float:
        """Orders processed per simulation minute."""
        span: float = self._last_delivery_time - self._first_delivery_time
        if span <= 0:
            return 0.0
        total: int = self.delivery_stats["all"].count
        return total / span

    def _sla_rate(self, key: str) -> float:
        total: int = self.sla_total[key]
        if total == 0:
            return 0.0
        return round(self.sla_violations[key] / total * 100, 2)

    def _sla_compliance_rate(self, key: str) -> float:
        return round(100.0 - self._sla_rate(key), 2)

    def export_json(self) -> dict[str, Any]:
        """Build structured output dictionary."""
        result: dict[str, Any] = {
            "summary": {
                "total_orders": self.delivery_stats["all"].count,
                "average_delivery_time": round(self.delivery_stats["all"].mean, 4),
                "delivery_time_std_dev": round(self.delivery_stats["all"].std_dev, 4),
                "sla_violation_rate_percent": self._sla_rate("all"),
                "sla_compliance_rate_percent": self._sla_compliance_rate("all"),
                "sla_violations": self.sla_violations["all"],
                "average_sla_margin": round(self.sla_margin_stats["all"].mean, 4),
                "fairness_std_dev": round(self.fairness_std_dev, 4),
                "fairness_min_assignments": self.fairness_min,
                "fairness_max_assignments": self.fairness_max,
                "fairness_assignment_range": self.fairness_range,
                "agent_assignment_counts": self._agent_assignments,
                "throughput_orders_per_sim_minute": round(self.throughput_orders_per_minute, 4),
            },
            "breakdown_by_priority": {},
        }

        for p in self.PRIORITY_KEYS:
            result["breakdown_by_priority"][p] = {
                "delivery_stats": self.delivery_stats[p].to_dict(),
                "sla_total": self.sla_total[p],
                "sla_violations": self.sla_violations[p],
                "sla_violation_rate_percent": self._sla_rate(p),
                "sla_compliance_rate_percent": self._sla_compliance_rate(p),
                "average_sla_margin": round(self.sla_margin_stats[p].mean, 4),
            }

        return result
