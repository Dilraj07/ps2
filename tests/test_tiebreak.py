import logging
from src.models.datatypes import Agent, Order, Priority
from src.core.scorer import Scorer
from src.utils.graph import EnvironmentGraph

logging.basicConfig(level=logging.DEBUG)

def test():
    # Mock environment graph
    graph = EnvironmentGraph()
    graph.get_distance = lambda *args: 5.0
    
    scorer = Scorer(graph)
    # Set weight of rating to 0 so it doesn't affect the main score, 
    # forcing a perfect tie in the `base_score` calculation.
    scorer.w["rating"] = 0.0
    
    order = Order(
        order_id="O1", timestamp=0.0, location=(0,0), 
        prep_time=5, priority=Priority.NORMAL, sla_minutes=30
    )
    
    print("--- SCENARIO 1: Same cost, different ratings ---")
    agent1 = Agent(agent_id="A1", current_location=(1,1), rating=4.5)
    agent2 = Agent(agent_id="A2", current_location=(1,1), rating=4.9)
    all_agents = [agent1, agent2]
    
    scored = scorer.score_all_candidates(order, all_agents, all_agents)
    for s in scored:
        print(f"Agent {s[2].agent_id} | Score: {s[0]:.4f} | Rating: {s[2].rating} | Tiebreaker Key: {s[1]}")
    
    winner = scored[0][2]
    print(f"Selected: {winner.agent_id} (Expected A2 because higher rating 4.9 > 4.5)")
    
    print("\n--- SCENARIO 2: Same cost, same ratings, different IDs ---")
    agent3 = Agent(agent_id="B2", current_location=(1,1), rating=4.5)
    agent4 = Agent(agent_id="A9", current_location=(1,1), rating=4.5)
    all_agents2 = [agent3, agent4]
    
    scored2 = scorer.score_all_candidates(order, all_agents2, all_agents2)
    for s in scored2:
        print(f"Agent {s[2].agent_id} | Score: {s[0]:.4f} | Rating: {s[2].rating} | Tiebreaker Key: {s[1]}")
        
    winner2 = scored2[0][2]
    print(f"Selected: {winner2.agent_id} (Expected A9 because lower ID string 'A9' < 'B2')")

if __name__ == '__main__':
    test()
