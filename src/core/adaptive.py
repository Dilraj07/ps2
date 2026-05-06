"""Adaptive Weight Engine — real-time weight shifting under system stress."""

import logging
import copy
from collections import deque
from typing import Optional

logger = logging.getLogger(__name__)


class AdaptiveWeightEngine:
    """Monitors recent deliveries and dynamically adjusts scoring weights.

    When SLA violations spike, SLA weight increases aggressively.
    When queue depth is high, travel weight increases (get orders out faster).
    When stress subsides, weights decay back to baseline exponentially.
    """

    # Sliding window size for recent delivery monitoring
    WINDOW_SIZE: int = 20

    # Stress thresholds
    SLA_WARN_THRESHOLD: float = 0.05     # 5% violation rate → moderate shift
    SLA_CRITICAL_THRESHOLD: float = 0.15  # 15% violation rate → emergency shift
    QUEUE_DEPTH_THRESHOLD: int = 10       # Deep queue → boost travel weight

    # Decay rate back to baseline (per adaptation cycle)
    DECAY_ALPHA: float = 0.10

    # Weight profiles
    BASELINE_WEIGHTS: dict[str, float] = {
        "sla": 0.40, "travel": 0.30, "fairness": 0.20, "rating": 0.10,
    }
    MODERATE_STRESS_WEIGHTS: dict[str, float] = {
        "sla": 0.55, "travel": 0.25, "fairness": 0.10, "rating": 0.10,
    }
    CRITICAL_STRESS_WEIGHTS: dict[str, float] = {
        "sla": 0.65, "travel": 0.25, "fairness": 0.05, "rating": 0.05,
    }
    QUEUE_PRESSURE_WEIGHTS: dict[str, float] = {
        "sla": 0.35, "travel": 0.40, "fairness": 0.15, "rating": 0.10,
    }

    def __init__(self, baseline: Optional[dict[str, float]] = None) -> None:
        self._baseline: dict[str, float] = baseline or copy.deepcopy(self.BASELINE_WEIGHTS)
        self._current: dict[str, float] = copy.deepcopy(self._baseline)

        # Sliding window of (was_sla_violated: bool)
        self._recent_violations: deque[bool] = deque(maxlen=self.WINDOW_SIZE)
        self._total_deliveries: int = 0
        self._total_violations: int = 0
        self._current_queue_depth: int = 0

        # Track adaptation events
        self.adaptation_count: int = 0
        self._last_stress_level: str = "normal"

    @property
    def current_weights(self) -> dict[str, float]:
        return copy.deepcopy(self._current)

    @property
    def stress_level(self) -> str:
        return self._last_stress_level

    def record_delivery(self, was_violation: bool) -> None:
        """Record a delivery outcome into the sliding window."""
        self._recent_violations.append(was_violation)
        self._total_deliveries += 1
        if was_violation:
            self._total_violations += 1

    def update_queue_depth(self, depth: int) -> None:
        self._current_queue_depth = depth

    def adapt(self) -> dict[str, float]:
        """Evaluate current stress and adjust weights. Returns current weights."""
        if len(self._recent_violations) < 3:
            # Not enough data yet
            return self.current_weights

        # Calculate recent violation rate
        recent_violations: int = sum(1 for v in self._recent_violations if v)
        recent_rate: float = recent_violations / len(self._recent_violations)

        # Determine target weights based on stress
        target: dict[str, float]
        stress_level: str

        if recent_rate >= self.SLA_CRITICAL_THRESHOLD:
            target = self.CRITICAL_STRESS_WEIGHTS
            stress_level = "critical"
        elif recent_rate >= self.SLA_WARN_THRESHOLD:
            target = self.MODERATE_STRESS_WEIGHTS
            stress_level = "moderate"
        elif self._current_queue_depth >= self.QUEUE_DEPTH_THRESHOLD:
            target = self.QUEUE_PRESSURE_WEIGHTS
            stress_level = "queue_pressure"
        else:
            target = self._baseline
            stress_level = "normal"

        # Log stress transitions
        if stress_level != self._last_stress_level:
            logger.info(
                "Adaptive weights: %s → %s (violation_rate=%.1f%%, queue=%d)",
                self._last_stress_level, stress_level,
                recent_rate * 100, self._current_queue_depth,
            )
            self._last_stress_level = stress_level
            self.adaptation_count += 1

        # Exponential decay toward target
        for key in self._current:
            self._current[key] += self.DECAY_ALPHA * (target[key] - self._current[key])

        # Normalize to ensure weights sum to 1.0
        total: float = sum(self._current.values())
        if total > 0:
            for key in self._current:
                self._current[key] /= total

        return self.current_weights

    def set_baseline(self, weights: dict[str, float]) -> None:
        """Update baseline weights (e.g., from Pareto search results)."""
        self._baseline = copy.deepcopy(weights)
        logger.info("Adaptive engine: baseline updated to %s", weights)

    def get_stats(self) -> dict:
        return {
            "total_deliveries": self._total_deliveries,
            "total_violations": self._total_violations,
            "adaptation_count": self.adaptation_count,
            "current_stress_level": self._last_stress_level,
            "current_weights": self.current_weights,
        }
