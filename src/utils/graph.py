"""Environment graph with Floyd-Warshall, path reconstruction, and edge delay tracking."""

import csv
import math
from typing import Optional


class EnvironmentGraph:
    """10x10 grid graph with pre-computed shortest paths via Floyd-Warshall.
    
    Also stores:
    - Path reconstruction via next-hop matrix
    - Direct edge delay multipliers for traffic risk analysis
    """

    GRID_SIZE: int = 10
    NUM_NODES: int = GRID_SIZE * GRID_SIZE  # 100

    def __init__(self) -> None:
        self._dist: list[list[float]] = []
        self._next: list[list[int]] = []          # next hop on shortest path
        self._edge_delay: list[list[float]] = []   # delay_multiplier of direct edges
        self._initialized: bool = False

    @staticmethod
    def _node_index(x: int, y: int) -> int:
        return y * EnvironmentGraph.GRID_SIZE + x

    @staticmethod
    def _index_to_coord(idx: int) -> tuple[int, int]:
        return (idx % EnvironmentGraph.GRID_SIZE, idx // EnvironmentGraph.GRID_SIZE)

    def load(self, filepath: str) -> None:
        """Load edges from CSV and run Floyd-Warshall with path reconstruction."""
        INF: float = float("inf")
        n: int = self.NUM_NODES

        # Initialize matrices
        self._dist = [[INF] * n for _ in range(n)]
        self._next = [[-1] * n for _ in range(n)]
        self._edge_delay = [[0.0] * n for _ in range(n)]

        for i in range(n):
            self._dist[i][i] = 0.0
            self._next[i][i] = i

        # Read edges
        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                from_x: int = int(row["from_x"].strip())
                from_y: int = int(row["from_y"].strip())
                to_x: int = int(row["to_x"].strip())
                to_y: int = int(row["to_y"].strip())
                base_dist: float = float(row["distance_minutes"].strip())
                delay_mult: float = float(row["delay_multiplier"].strip())

                weight: float = base_dist * delay_mult

                i: int = self._node_index(from_x, from_y)
                j: int = self._node_index(to_x, to_y)

                # Bidirectional
                if weight < self._dist[i][j]:
                    self._dist[i][j] = weight
                    self._next[i][j] = j
                    self._edge_delay[i][j] = delay_mult
                if weight < self._dist[j][i]:
                    self._dist[j][i] = weight
                    self._next[j][i] = i
                    self._edge_delay[j][i] = delay_mult

        # Floyd-Warshall with next-hop tracking
        for k in range(n):
            dk = self._dist[k]
            for i in range(n):
                di = self._dist[i]
                dik = di[k]
                if dik == INF:
                    continue
                ni = self._next[i]
                for j in range(n):
                    candidate: float = dik + dk[j]
                    if candidate < di[j]:
                        di[j] = candidate
                        ni[j] = self._next[i][k]  # next hop toward j is same as toward k

        self._initialized = True

    def get_distance(self, from_loc: tuple[int, int], to_loc: tuple[int, int]) -> float:
        """O(1) shortest-path distance lookup."""
        i: int = self._node_index(from_loc[0], from_loc[1])
        j: int = self._node_index(to_loc[0], to_loc[1])
        return self._dist[i][j]

    def has_path(self, from_loc: tuple[int, int], to_loc: tuple[int, int]) -> bool:
        return self.get_distance(from_loc, to_loc) != float("inf")

    def get_path(self, from_loc: tuple[int, int], to_loc: tuple[int, int]) -> list[tuple[int, int]]:
        """Reconstruct the shortest path as a list of (x, y) coordinates."""
        i: int = self._node_index(from_loc[0], from_loc[1])
        j: int = self._node_index(to_loc[0], to_loc[1])

        if self._dist[i][j] == float("inf"):
            return []

        path: list[tuple[int, int]] = [self._index_to_coord(i)]
        current: int = i
        while current != j:
            current = self._next[current][j]
            if current == -1:
                return []
            path.append(self._index_to_coord(current))
        return path

    def get_path_max_delay(self, from_loc: tuple[int, int], to_loc: tuple[int, int]) -> float:
        """Return the maximum delay_multiplier along the shortest path."""
        i: int = self._node_index(from_loc[0], from_loc[1])
        j: int = self._node_index(to_loc[0], to_loc[1])

        if self._dist[i][j] == float("inf"):
            return 0.0

        max_delay: float = 1.0
        current: int = i
        while current != j:
            next_hop: int = self._next[current][j]
            if next_hop == -1:
                break
            edge_d: float = self._edge_delay[current][next_hop]
            if edge_d > max_delay:
                max_delay = edge_d
            current = next_hop
        return max_delay

    def get_path_avg_delay(self, from_loc: tuple[int, int], to_loc: tuple[int, int]) -> float:
        """Return the average delay_multiplier along the shortest path."""
        i: int = self._node_index(from_loc[0], from_loc[1])
        j: int = self._node_index(to_loc[0], to_loc[1])

        if self._dist[i][j] == float("inf"):
            return 1.0
        if i == j:
            return 1.0

        total_delay: float = 0.0
        edge_count: int = 0
        current: int = i
        while current != j:
            next_hop: int = self._next[current][j]
            if next_hop == -1:
                break
            total_delay += self._edge_delay[current][next_hop]
            edge_count += 1
            current = next_hop

        return total_delay / edge_count if edge_count > 0 else 1.0
