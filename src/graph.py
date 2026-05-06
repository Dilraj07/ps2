"""Environment graph with Floyd-Warshall all-pairs shortest paths."""

import csv
import math
from typing import Optional


class EnvironmentGraph:
    """10x10 grid graph with pre-computed shortest paths via Floyd-Warshall."""

    GRID_SIZE: int = 10
    NUM_NODES: int = GRID_SIZE * GRID_SIZE  # 100

    def __init__(self) -> None:
        # Flat 2D list: dist[i][j] where i,j = node indices
        self._dist: list[list[float]] = []
        self._initialized: bool = False

    @staticmethod
    def _node_index(x: int, y: int) -> int:
        """Convert (x, y) coordinate to flat index."""
        return y * EnvironmentGraph.GRID_SIZE + x

    def load(self, filepath: str) -> None:
        """Load edges from CSV and run Floyd-Warshall."""
        INF: float = float("inf")
        n: int = self.NUM_NODES

        # Initialize distance matrix
        self._dist = [[INF] * n for _ in range(n)]
        for i in range(n):
            self._dist[i][i] = 0.0

        # Read edges — comma-delimited CSV
        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                from_x: int = int(row["from_x"].strip())
                from_y: int = int(row["from_y"].strip())
                to_x: int = int(row["to_x"].strip())
                to_y: int = int(row["to_y"].strip())
                base_dist: float = float(row["distance_minutes"].strip())
                delay_mult: float = float(row["delay_multiplier"].strip())

                # Actual edge weight = base distance * delay multiplier
                weight: float = base_dist * delay_mult

                i: int = self._node_index(from_x, from_y)
                j: int = self._node_index(to_x, to_y)

                # Bidirectional — take minimum if duplicate edges
                self._dist[i][j] = min(self._dist[i][j], weight)
                self._dist[j][i] = min(self._dist[j][i], weight)

        # Floyd-Warshall: O(V^3) — runs once, ~100^3 = 1M iterations
        for k in range(n):
            dk = self._dist[k]
            for i in range(n):
                di = self._dist[i]
                dik = di[k]
                if dik == INF:
                    continue
                for j in range(n):
                    candidate: float = dik + dk[j]
                    if candidate < di[j]:
                        di[j] = candidate

        self._initialized = True

    def get_distance(self, from_loc: tuple[int, int], to_loc: tuple[int, int]) -> float:
        """O(1) shortest-path lookup after Floyd-Warshall pre-computation."""
        i: int = self._node_index(from_loc[0], from_loc[1])
        j: int = self._node_index(to_loc[0], to_loc[1])
        return self._dist[i][j]

    def has_path(self, from_loc: tuple[int, int], to_loc: tuple[int, int]) -> bool:
        """Check if a finite path exists between two locations."""
        return self.get_distance(from_loc, to_loc) != float("inf")
