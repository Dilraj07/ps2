import argparse
import json
import logging
import os
import time
from datetime import datetime
from typing import Optional

from src.models.datatypes import Order, Agent, Priority
from src.utils.graph import EnvironmentGraph
from src.state.queue import OrderQueue
from src.state.registry import AgentRegistry
from src.core.scorer import Scorer
from src.core.engine import SimulationEngine, DispatchMode
from src.metrics.collector import MetricsCollector
from src.utils.delay_buffer import DelayBuffer
from src.core.adaptive import AdaptiveWeightEngine
from src.core.hungarian import HungarianAssigner
from src.data_access.loader import load_orders, load_agents
from src.config.settings import load_constraints, apply_constraints

logger = logging.getLogger("routly.cli")

def run_simulation(
    mode: str = "hungarian",
    custom_weights: Optional[dict[str, float]] = None,
    return_engine: bool = False,
) -> dict:
    """Core simulation runner — used by main, API, Pareto search, and dashboard.
    
    Returns the full metrics dict. If return_engine=True, returns (metrics, engine).
    """
    # Adjust base_dir since we are now in src/interfaces/
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    data_dir = os.path.join(base_dir, "data", "raw")
    output_dir = os.path.join(base_dir, "data", "results")
    os.makedirs(output_dir, exist_ok=True)

    run_start = time.perf_counter()
    run_timestamp = datetime.now().isoformat()

    # Load data
    graph = EnvironmentGraph()
    graph.load(os.path.join(data_dir, "environment_edges.csv"))

    orders = load_orders(os.path.join(data_dir, "orders.csv"))
    agents = load_agents(os.path.join(data_dir, "agents.csv"))
    constraints = load_constraints(os.path.join(data_dir, "constraints.csv"))
    priority_multipliers = apply_constraints(constraints)

    # Deep copy orders/agents for independent simulation runs
    sim_orders: list[Order] = [
        Order(
            order_id=o.order_id, timestamp=o.timestamp, location=o.location,
            prep_time=o.prep_time, priority=o.priority, sla_minutes=o.sla_minutes,
        )
        for o in orders
    ]
    sim_agents: list[Agent] = [
        Agent(agent_id=a.agent_id, current_location=a.current_location, rating=a.rating)
        for a in agents
    ]

    # Build components
    queue = OrderQueue()
    registry = AgentRegistry()
    for a in sim_agents:
        registry.add(a)

    weights = custom_weights or {"sla": 0.40, "travel": 0.30, "fairness": 0.20, "rating": 0.10}
    delay_buffer = DelayBuffer(graph)
    adaptive = AdaptiveWeightEngine(baseline=weights.copy())
    hungarian_assigner = HungarianAssigner(graph, delay_buffer)

    scorer = Scorer(graph, weights.copy(), priority_multipliers, delay_buffer)
    metrics = MetricsCollector()

    dispatch_mode = DispatchMode.HUNGARIAN if mode == "hungarian" else DispatchMode.GREEDY
    engine = SimulationEngine(
        queue, registry, scorer, metrics, graph,
        adaptive=adaptive, hungarian=hungarian_assigner, mode=dispatch_mode,
    )

    # Run
    sim_start = time.perf_counter()
    engine.run(sim_orders)
    sim_elapsed = time.perf_counter() - sim_start

    # Finalize
    metrics.finalize_fairness(registry.get_all())
    result = metrics.export_json()

    result["metadata"] = {
        "project": "Routly",
        "team": "Greater N0ida",
        "year": "2nd Year",
        "timestamp": run_timestamp,
        "mode": mode,
        "dataset": {
            "orders_file": "data/raw/orders.csv",
            "agents_file": "data/raw/agents.csv",
            "environment_file": "data/raw/environment_edges.csv",
        },
        "total_agents": len(sim_agents),
        "total_orders": len(sim_orders),
        "scoring_weights": weights,
        "priority_multipliers": priority_multipliers,
        "max_active_orders_per_agent": Agent.MAX_ACTIVE_ORDERS,
    }

    result["performance"] = {
        "wall_clock_seconds": round(sim_elapsed, 4),
        "total_scoring_decisions": scorer.total_decisions,
        "avg_decision_latency_ms": round(scorer.avg_decision_time_ms, 4),
        "max_decision_latency_ms": round(scorer.max_decision_time_ms, 4),
        "hungarian_batches": hungarian_assigner.total_batches,
        "avg_batch_time_ms": round(hungarian_assigner.avg_batch_time_ms, 4),
        "orders_per_wall_second": round(len(sim_orders) / sim_elapsed, 2) if sim_elapsed > 0 else 0,
    }

    result["adaptive"] = adaptive.get_stats()
    result["assignment_log"] = engine.assignment_log

    if return_engine:
        return result, engine

    return result


def run_cli() -> None:
    parser = argparse.ArgumentParser(description="Routly Smart Dispatch System")
    parser.add_argument("--mode", choices=["hungarian", "greedy"], default="hungarian",
                        help="Dispatch mode (default: hungarian)")
    args = parser.parse_args()

    logger.info("=== Routly Smart Dispatch System [%s mode] ===", args.mode.upper())

    result = run_simulation(mode=args.mode)

    # Save metrics
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    output_path = os.path.join(base_dir, "data", "results", "metrics.json")
    with open(output_path, "w", encoding="utf-8") as f:
        # Don't write assignment_log to file (too large)
        export = {k: v for k, v in result.items() if k != "assignment_log"}
        json.dump(export, f, indent=2)

    logger.info("Metrics written to %s", output_path)

    # Console summary
    s = result["summary"]
    p = result["performance"]
    print("\n" + "=" * 64)
    print(f"  ROUTLY [{args.mode.upper()}] - Simulation Complete")
    print("=" * 64)
    print(f"  Orders Delivered:      {s['total_orders']}")
    print(f"  Avg Delivery Time:     {s['average_delivery_time']:.2f} min")
    print(f"  SLA Compliance:        {s['sla_compliance_rate_percent']}%")
    print(f"  SLA Violations:        {s['sla_violations']} ({s['sla_violation_rate_percent']}%)")
    print(f"  Avg SLA Margin:        {s['average_sla_margin']:.2f} min")
    print(f"  Fairness Std Dev:      {s['fairness_std_dev']:.2f}")
    print(f"  Fairness Range:        {s['fairness_min_assignments']}-{s['fairness_max_assignments']}")
    print("-" * 64)
    for pr in ["high", "normal", "low"]:
        bd = result["breakdown_by_priority"][pr]
        ds = bd["delivery_stats"]
        print(f"  [{pr.upper():6s}] cnt={ds['count']:3d}  avg={ds['mean']:6.2f}  "
              f"margin={bd['average_sla_margin']:5.1f}  compliance={bd['sla_compliance_rate_percent']}%")
    print("-" * 64)
    print(f"  Wall Clock:            {p['wall_clock_seconds']:.3f}s")
    print(f"  Hungarian Batches:     {p['hungarian_batches']}")
    print(f"  Avg Batch Latency:     {p['avg_batch_time_ms']:.3f}ms")
    print(f"  Throughput:            {p['orders_per_wall_second']:.0f} orders/sec")
    ada = result["adaptive"]
    print(f"  Adaptive Shifts:       {ada['adaptation_count']} (final: {ada['current_stress_level']})")
    print("=" * 64)
