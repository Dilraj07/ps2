"""Agent registry with O(1) availability tracking."""

from src.models.datatypes import Agent


class AgentRegistry:
    """Master agent dictionary with a secondary available-pool set."""

    def __init__(self) -> None:
        self.agents: dict[str, Agent] = {}
        self._available: set[str] = set()

    def add(self, agent: Agent) -> None:
        """Register an agent and mark as available."""
        self.agents[agent.agent_id] = agent
        if agent.is_available:
            self._available.add(agent.agent_id)

    def get_available(self) -> list[Agent]:
        """Return list of agents currently below capacity."""
        return [self.agents[aid] for aid in self._available]

    def update_availability(self, agent: Agent) -> None:
        """Sync the available pool with the agent's current capacity."""
        if agent.is_available:
            self._available.add(agent.agent_id)
        else:
            self._available.discard(agent.agent_id)

    def get_all(self) -> list[Agent]:
        """Return all registered agents."""
        return list(self.agents.values())

    def get(self, agent_id: str) -> Agent:
        return self.agents[agent_id]
