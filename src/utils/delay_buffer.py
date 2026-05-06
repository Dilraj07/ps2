"""Dynamic Delay Buffering — traffic risk awareness for travel time estimates."""

from src.utils.graph import EnvironmentGraph


class DelayBuffer:
    """Inflates travel time estimates for routes passing through high-delay edges.

    If the shortest path includes edges with delay_multiplier >= threshold,
    the effective travel time is inflated to account for traffic variability.
    """

    # Edges with delay >= this trigger buffering
    HIGH_DELAY_THRESHOLD: float = 1.15

    # How much to inflate per unit of risk factor
    BUFFER_COEFFICIENT: float = 0.10

    def __init__(self, graph: EnvironmentGraph) -> None:
        self.graph: EnvironmentGraph = graph

    def get_buffered_travel_time(
        self, from_loc: tuple[int, int], to_loc: tuple[int, int]
    ) -> float:
        """Return travel time with traffic risk buffer applied.

        If any edge on the path has delay_multiplier >= HIGH_DELAY_THRESHOLD,
        inflate the effective travel time:
            effective = base_travel * (1 + BUFFER_COEFFICIENT * avg_delay_on_path)
        
        Otherwise, return the raw shortest-path distance.
        """
        base_travel: float = self.graph.get_distance(from_loc, to_loc)

        if base_travel == float("inf") or base_travel == 0.0:
            return base_travel

        max_delay: float = self.graph.get_path_max_delay(from_loc, to_loc)

        if max_delay >= self.HIGH_DELAY_THRESHOLD:
            avg_delay: float = self.graph.get_path_avg_delay(from_loc, to_loc)
            return base_travel * (1.0 + self.BUFFER_COEFFICIENT * avg_delay)

        return base_travel

    def get_risk_factor(
        self, from_loc: tuple[int, int], to_loc: tuple[int, int]
    ) -> float:
        """Return a 0.0-1.0 risk factor for the route.
        
        0.0 = all edges are delay 1.0 (no risk)
        1.0 = max theoretical delay
        """
        max_delay: float = self.graph.get_path_max_delay(from_loc, to_loc)
        # Normalize: delay range is 1.0 to 1.2, so risk = (max_delay - 1.0) / 0.2
        return min(1.0, max(0.0, (max_delay - 1.0) / 0.2))
