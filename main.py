"""Routly — Smart Delivery Dispatch System entry point.

Supports dual-mode dispatch:
  python main.py                  → Hungarian mode (default)
  python main.py --mode greedy    → Greedy mode (for comparison)
"""

import argparse
import csv
import json
import logging
import os
import sys
import time
import copy
from datetime import datetime
from typing import Optional

from src.models import Order, Agent, Priority
from src.graph import EnvironmentGraph
from src.queue import OrderQueue
from src.registry import AgentRegistry
from src.scorer import Scorer
from src.engine import SimulationEngine, DispatchMode
from src.metrics import MetricsCollector
from src.delay_buffer import DelayBuffer
from src.adaptive import AdaptiveWeightEngine
from src.hungarian import HungarianAssigner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("routly")


# ─── Data Loaders (with validation) ──────────────────────────────────

def _safe_read_csv(filepath: str) -> list[dict[str, str]]:
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Required data file missing: {filepath}")
    rows: list[dict[str, str]] = []
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if all(v is None or v.strip() == "" for v in row.values()):
                continue
            rows.append(row)
    return rows


def _validate_int(value: str, field: str, rid: str) -> Optional[int]:
    try:
        return int(value.strip())
    except (ValueError, AttributeError):
        logger.warning("Invalid int for %s in %s: '%s'", field, rid, value)
        return None


def _validate_float(value: str, field: str, rid: str) -> Optional[float]:
    try:
        return float(value.strip())
    except (ValueError, AttributeError):
        logger.warning("Invalid float for %s in %s: '%s'", field, rid, value)
        return None


def load_orders(filepath: str) -> list[Order]:
    raw_rows = _safe_read_csv(filepath)
    if not raw_rows:
        return []

    required = {"order_id", "timestamp", "location_x", "location_y",
                "prep_time_minutes", "priority", "sla_minutes"}

    parsed: list[tuple[dict[str, str], datetime]] = []
    for row in raw_rows:
        rid = row.get("order_id", "UNKNOWN").strip()
        missing = required - set(row.keys())
        if missing:
            logger.warning("Order %s: Missing %s. Skip.", rid, missing)
            continue
        try:
            ts = datetime.strptime(row["timestamp"].strip(), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            logger.warning("Order %s: Bad timestamp. Skip.", rid)
            continue
        if row["priority"].strip() not in ("high", "normal", "low"):
            logger.warning("Order %s: Bad priority. Skip.", rid)
            continue
        parsed.append((row, ts))

    if not parsed:
        return []

    earliest = min(ts for _, ts in parsed)
    orders: list[Order] = []
    for row, ts in parsed:
        rid = row["order_id"].strip()
        mins = (ts - earliest).total_seconds() / 60.0
        lx = _validate_int(row["location_x"], "location_x", rid)
        ly = _validate_int(row["location_y"], "location_y", rid)
        pt = _validate_int(row["prep_time_minutes"], "prep_time", rid)
        sla = _validate_int(row["sla_minutes"], "sla_minutes", rid)
        if any(v is None for v in (lx, ly, pt, sla)):
            continue
        if not (0 <= lx <= 9 and 0 <= ly <= 9):
            continue
        orders.append(Order(
            order_id=rid, timestamp=mins, location=(lx, ly),
            prep_time=pt, priority=Priority(row["priority"].strip()),
            sla_minutes=sla,
        ))

    logger.info("Loaded %d orders (epoch=%s)", len(orders), earliest.isoformat())
    return orders


def load_agents(filepath: str) -> list[Agent]:
    raw_rows = _safe_read_csv(filepath)
    agents: list[Agent] = []
    for row in raw_rows:
        rid = row.get("agent_id", "UNKNOWN").strip()
        cx = _validate_int(row.get("current_x", ""), "current_x", rid)
        cy = _validate_int(row.get("current_y", ""), "current_y", rid)
        rat = _validate_float(row.get("rating", ""), "rating", rid)
        if any(v is None for v in (cx, cy, rat)):
            continue
        if not (0 <= cx <= 9 and 0 <= cy <= 9):
            continue
        agents.append(Agent(agent_id=rid, current_location=(cx, cy), rating=rat))
    logger.info("Loaded %d agents", len(agents))
    return agents


def load_constraints(filepath: str) -> dict[str, str]:
    if not os.path.exists(filepath):
        return {}
    constraints: dict[str, str] = {}
    for row in _safe_read_csv(filepath):
        k = row.get("constraint", "").strip()
        v = row.get("value", "").strip()
        if k:
            constraints[k] = v
    return constraints


def apply_constraints(constraints: dict[str, str]) -> dict[str, float]:
    try:
        Agent.MAX_ACTIVE_ORDERS = int(constraints.get("max_active_orders_per_agent", "2"))
    except ValueError:
        Agent.MAX_ACTIVE_ORDERS = 2

    priority_multipliers: dict[str, float] = {
        "high": float(constraints.get("priority_weight_high", "1.5")),
        "normal": float(constraints.get("priority_weight_normal", "1.0")),
        "low": float(constraints.get("priority_weight_low", "0.8")),
    }

    try:
        Scorer.LATENCY_TARGET_S = float(constraints.get("decision_latency_target_seconds", "5"))
    except ValueError:
        Scorer.LATENCY_TARGET_S = 5.0

    return priority_multipliers


def run_simulation(
    mode: str = "hungarian",
    custom_weights: Optional[dict[str, float]] = None,
    return_engine: bool = False,
) -> dict:
    """Core simulation runner — used by main, API, Pareto search, and dashboard.
    
    Returns the full metrics dict. If return_engine=True, returns (metrics, engine).
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, "data", "raw")
    output_dir = os.path.join(base_dir, "output")
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Routly Smart Dispatch System")
    parser.add_argument("--mode", choices=["hungarian", "greedy"], default="hungarian",
                        help="Dispatch mode (default: hungarian)")
    args = parser.parse_args()

    logger.info("=== Routly Smart Dispatch System [%s mode] ===", args.mode.upper())

    result = run_simulation(mode=args.mode)

    # Save metrics
    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(base_dir, "output", "metrics.json")
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


if __name__ == "__main__":
    main()
