"""Routly — Smart Delivery Dispatch System entry point."""

import csv
import json
import logging
import os
import sys
import time
from datetime import datetime
from typing import Optional

from src.models import Order, Agent, Priority
from src.graph import EnvironmentGraph
from src.queue import OrderQueue
from src.registry import AgentRegistry
from src.scorer import Scorer
from src.engine import SimulationEngine
from src.metrics import MetricsCollector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("routly")


# ---------- Data Loaders with Validation (Issue 16) ---------- #

def _safe_read_csv(filepath: str) -> list[dict[str, str]]:
    """Read a CSV file with error handling for missing files and malformed data."""
    if not os.path.exists(filepath):
        logger.error("File not found: %s", filepath)
        raise FileNotFoundError(f"Required data file missing: {filepath}")

    rows: list[dict[str, str]] = []
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            logger.error("Empty or malformed CSV (no header): %s", filepath)
            raise ValueError(f"CSV has no header row: {filepath}")

        for line_num, row in enumerate(reader, start=2):  # line 1 = header
            # Check for rows that are entirely empty
            if all(v is None or v.strip() == "" for v in row.values()):
                continue
            rows.append(row)

    return rows


def _validate_int(value: str, field: str, record_id: str) -> Optional[int]:
    """Parse int with validation logging."""
    try:
        return int(value.strip())
    except (ValueError, AttributeError):
        logger.warning("Invalid integer for %s in record %s: '%s'. Skipping.", field, record_id, value)
        return None


def _validate_float(value: str, field: str, record_id: str) -> Optional[float]:
    """Parse float with validation logging."""
    try:
        return float(value.strip())
    except (ValueError, AttributeError):
        logger.warning("Invalid float for %s in record %s: '%s'. Skipping.", field, record_id, value)
        return None


def load_orders(filepath: str) -> list[Order]:
    """Load orders from CSV with full validation. Timestamps → minutes from earliest."""
    raw_rows = _safe_read_csv(filepath)

    if not raw_rows:
        logger.error("No orders found in %s", filepath)
        return []

    required_fields = {"order_id", "timestamp", "location_x", "location_y",
                       "prep_time_minutes", "priority", "sla_minutes"}

    # First pass: parse timestamps and validate
    parsed: list[tuple[dict[str, str], datetime]] = []
    for row in raw_rows:
        rid: str = row.get("order_id", "UNKNOWN").strip()

        # Check required fields
        missing = required_fields - set(row.keys())
        if missing:
            logger.warning("Order %s: Missing fields %s. Skipping.", rid, missing)
            continue

        # Parse timestamp
        ts_str: str = row["timestamp"].strip()
        try:
            ts: datetime = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            logger.warning("Order %s: Invalid timestamp '%s'. Skipping.", rid, ts_str)
            continue

        # Validate priority
        prio_str: str = row["priority"].strip()
        if prio_str not in ("high", "normal", "low"):
            logger.warning("Order %s: Invalid priority '%s'. Skipping.", rid, prio_str)
            continue

        parsed.append((row, ts))

    if not parsed:
        logger.error("No valid orders after validation in %s", filepath)
        return []

    # Earliest timestamp = simulation minute 0
    earliest: datetime = min(ts for _, ts in parsed)

    orders: list[Order] = []
    for row, ts in parsed:
        rid = row["order_id"].strip()
        minutes_from_epoch: float = (ts - earliest).total_seconds() / 60.0

        loc_x = _validate_int(row["location_x"], "location_x", rid)
        loc_y = _validate_int(row["location_y"], "location_y", rid)
        prep = _validate_int(row["prep_time_minutes"], "prep_time_minutes", rid)
        sla = _validate_int(row["sla_minutes"], "sla_minutes", rid)

        if any(v is None for v in (loc_x, loc_y, prep, sla)):
            continue

        # Range validation
        if not (0 <= loc_x <= 9 and 0 <= loc_y <= 9):
            logger.warning("Order %s: Location (%d,%d) outside 10x10 grid. Skipping.", rid, loc_x, loc_y)
            continue
        if prep < 0:
            logger.warning("Order %s: Negative prep_time %d. Skipping.", rid, prep)
            continue
        if sla <= 0:
            logger.warning("Order %s: Non-positive sla_minutes %d. Skipping.", rid, sla)
            continue

        orders.append(Order(
            order_id=rid,
            timestamp=minutes_from_epoch,
            location=(loc_x, loc_y),
            prep_time=prep,
            priority=Priority(row["priority"].strip()),
            sla_minutes=sla,
        ))

    logger.info("Loaded %d valid orders out of %d rows (epoch = %s)",
                len(orders), len(raw_rows), earliest.isoformat())
    return orders


def load_agents(filepath: str, graph: EnvironmentGraph) -> list[Agent]:
    """Load agents from CSV with validation. Verify locations exist in graph."""
    raw_rows = _safe_read_csv(filepath)

    required_fields = {"agent_id", "current_x", "current_y", "rating"}
    agents: list[Agent] = []

    for row in raw_rows:
        rid: str = row.get("agent_id", "UNKNOWN").strip()

        missing = required_fields - set(row.keys())
        if missing:
            logger.warning("Agent %s: Missing fields %s. Skipping.", rid, missing)
            continue

        cx = _validate_int(row["current_x"], "current_x", rid)
        cy = _validate_int(row["current_y"], "current_y", rid)
        rating = _validate_float(row["rating"], "rating", rid)

        if any(v is None for v in (cx, cy, rating)):
            continue

        # Referential integrity: location must be on the grid
        if not (0 <= cx <= 9 and 0 <= cy <= 9):
            logger.warning("Agent %s: Location (%d,%d) outside 10x10 grid. Skipping.", rid, cx, cy)
            continue

        # Rating range validation
        if not (1.0 <= rating <= 5.0):
            logger.warning("Agent %s: Rating %.1f outside [1.0, 5.0]. Skipping.", rid, rating)
            continue

        agents.append(Agent(
            agent_id=rid,
            current_location=(cx, cy),
            rating=rating,
        ))

    logger.info("Loaded %d valid agents out of %d rows", len(agents), len(raw_rows))
    return agents


def load_constraints(filepath: str) -> dict[str, str]:
    """Load constraints from CSV into a key-value dict."""
    if not os.path.exists(filepath):
        logger.warning("Constraints file not found: %s. Using defaults.", filepath)
        return {}

    constraints: dict[str, str] = {}
    raw_rows = _safe_read_csv(filepath)
    for row in raw_rows:
        key: str = row.get("constraint", "").strip()
        value: str = row.get("value", "").strip()
        if key:
            constraints[key] = value
    logger.info("Loaded %d constraints", len(constraints))
    return constraints


def apply_constraints(constraints: dict[str, str]) -> dict[str, float]:
    """Extract and apply constraint values, returning priority multipliers."""
    # Max active orders per agent
    max_orders_str = constraints.get("max_active_orders_per_agent", "2")
    try:
        Agent.MAX_ACTIVE_ORDERS = int(max_orders_str)
    except ValueError:
        Agent.MAX_ACTIVE_ORDERS = 2
    logger.info("Constraint: max_active_orders_per_agent = %d", Agent.MAX_ACTIVE_ORDERS)

    # Priority multipliers
    priority_multipliers: dict[str, float] = {
        "high": float(constraints.get("priority_weight_high", "1.5")),
        "normal": float(constraints.get("priority_weight_normal", "1.0")),
        "low": float(constraints.get("priority_weight_low", "0.8")),
    }
    logger.info("Constraint: priority_multipliers = %s", priority_multipliers)

    # Decision latency target
    latency_str = constraints.get("decision_latency_target_seconds", "5")
    try:
        Scorer.LATENCY_TARGET_S = float(latency_str)
    except ValueError:
        Scorer.LATENCY_TARGET_S = 5.0
    logger.info("Constraint: decision_latency_target = %.1fs", Scorer.LATENCY_TARGET_S)

    return priority_multipliers


# ---------- Main ---------- #

def main() -> None:
    run_start: float = time.perf_counter()
    run_timestamp: str = datetime.now().isoformat()

    base_dir: str = os.path.dirname(os.path.abspath(__file__))
    data_dir: str = os.path.join(base_dir, "data", "raw")
    output_dir: str = os.path.join(base_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    # --- Load data ---
    logger.info("=== Routly Smart Dispatch System ===")

    graph = EnvironmentGraph()
    graph.load(os.path.join(data_dir, "environment_edges.csv"))
    logger.info("Graph loaded: %d nodes, Floyd-Warshall complete", EnvironmentGraph.NUM_NODES)

    orders: list[Order] = load_orders(os.path.join(data_dir, "orders.csv"))
    agents: list[Agent] = load_agents(os.path.join(data_dir, "agents.csv"), graph)
    constraints: dict[str, str] = load_constraints(os.path.join(data_dir, "constraints.csv"))

    # --- Apply constraints from CSV ---
    priority_multipliers = apply_constraints(constraints)

    # --- Build components ---
    queue = OrderQueue()
    registry = AgentRegistry()
    for agent in agents:
        registry.add(agent)

    # Scoring weights
    weights: dict[str, float] = {
        "sla": 0.40,
        "travel": 0.30,
        "fairness": 0.20,
        "rating": 0.10,
    }

    scorer = Scorer(graph, weights, priority_multipliers)
    metrics = MetricsCollector()
    engine = SimulationEngine(queue, registry, scorer, metrics, graph)

    # --- Run simulation ---
    logger.info("Starting simulation with %d orders and %d agents...", len(orders), len(agents))
    sim_start: float = time.perf_counter()
    engine.run(orders)
    sim_elapsed_s: float = time.perf_counter() - sim_start

    # --- Finalize metrics ---
    metrics.finalize_fairness(registry.get_all())

    # --- Export JSON ---
    output_path: str = os.path.join(output_dir, "metrics.json")
    result: dict = metrics.export_json()

    # Add metadata (Issue 15)
    result["metadata"] = {
        "project": "Routly",
        "team": "Greater N0ida",
        "year": "2nd Year",
        "timestamp": run_timestamp,
        "dataset": {
            "orders_file": "data/raw/orders.csv",
            "agents_file": "data/raw/agents.csv",
            "environment_file": "data/raw/environment_edges.csv",
            "constraints_file": "data/raw/constraints.csv",
        },
        "total_agents": len(agents),
        "total_orders": len(orders),
        "scoring_weights": weights,
        "priority_multipliers": priority_multipliers,
        "max_active_orders_per_agent": Agent.MAX_ACTIVE_ORDERS,
    }

    # Performance metadata (Issues 18 & 19)
    result["performance"] = {
        "wall_clock_simulation_seconds": round(sim_elapsed_s, 4),
        "total_scoring_decisions": scorer.total_decisions,
        "avg_decision_latency_ms": round(scorer.avg_decision_time_ms, 4),
        "max_decision_latency_ms": round(scorer.max_decision_time_ms, 4),
        "decision_latency_target_ms": Scorer.LATENCY_TARGET_S * 1000,
        "orders_per_wall_second": round(len(orders) / sim_elapsed_s, 2) if sim_elapsed_s > 0 else 0,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    logger.info("Metrics written to %s", output_path)

    total_elapsed: float = time.perf_counter() - run_start

    # --- Console summary ---
    summary = result["summary"]
    perf = result["performance"]
    print("\n" + "=" * 60)
    print("  ROUTLY - Simulation Complete")
    print("=" * 60)
    print(f"  Total Orders Delivered:    {summary['total_orders']}")
    print(f"  Avg Delivery Time:         {summary['average_delivery_time']:.2f} min")
    print(f"  Delivery Time Std Dev:     {summary['delivery_time_std_dev']:.2f} min")
    print(f"  SLA Violations:            {summary['sla_violations']} ({summary['sla_violation_rate_percent']}%)")
    print(f"  SLA Compliance Rate:       {summary['sla_compliance_rate_percent']}%")
    print(f"  Avg SLA Margin:            {summary['average_sla_margin']:.2f} min")
    print(f"  Fairness Std Dev:          {summary['fairness_std_dev']:.2f}")
    print(f"  Fairness Range:            {summary['fairness_min_assignments']}-{summary['fairness_max_assignments']} (range={summary['fairness_assignment_range']})")
    print("-" * 60)
    for p in ["high", "normal", "low"]:
        bd = result["breakdown_by_priority"][p]
        ds = bd["delivery_stats"]
        print(f"  [{p.upper():6s}] "
              f"count={ds['count']:3d}  "
              f"avg={ds['mean']:6.2f}  "
              f"margin={bd['average_sla_margin']:5.1f}  "
              f"sla_viol={bd['sla_violations']}  "
              f"compliance={bd['sla_compliance_rate_percent']}%")
    print("-" * 60)
    print(f"  Simulation Wall Clock:     {perf['wall_clock_simulation_seconds']:.3f}s")
    print(f"  Scoring Decisions:         {perf['total_scoring_decisions']}")
    print(f"  Avg Decision Latency:      {perf['avg_decision_latency_ms']:.3f}ms")
    print(f"  Max Decision Latency:      {perf['max_decision_latency_ms']:.3f}ms")
    print(f"  Throughput:                {perf['orders_per_wall_second']:.0f} orders/sec")
    print(f"  Total Runtime:             {total_elapsed:.3f}s")
    print("=" * 60)


if __name__ == "__main__":
    main()
