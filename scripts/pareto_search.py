"""Pareto Grid Search — find optimal weight configurations.

Runs N simulation configurations with random weights, collects
SLA compliance vs fairness metrics, and identifies the Pareto frontier.

Usage:
    python pareto_search.py               # 100 configs (default)
    python pareto_search.py --configs 50  # 50 configs
"""

import argparse
import json
import os
import random
import sys
import time
import logging

logging.basicConfig(level=logging.WARNING)

from main import run_simulation

logger = logging.getLogger("pareto")
logger.setLevel(logging.INFO)


def generate_random_weights() -> dict[str, float]:
    """Generate 4 random weights that sum to 1.0."""
    raw = [random.random() for _ in range(4)]
    total = sum(raw)
    normalized = [r / total for r in raw]
    return {
        "sla": round(normalized[0], 4),
        "travel": round(normalized[1], 4),
        "fairness": round(normalized[2], 4),
        "rating": round(normalized[3], 4),
    }


def is_dominated(point: dict, others: list[dict]) -> bool:
    """Check if a point is dominated by any other point.
    
    A point is dominated if another point is better on ALL objectives:
    - Higher SLA compliance
    - Lower fairness std dev (more fair)
    - Lower avg delivery time
    """
    for other in others:
        if other is point:
            continue
        if (other["sla_compliance"] >= point["sla_compliance"]
                and other["fairness_std_dev"] <= point["fairness_std_dev"]
                and other["avg_delivery_time"] <= point["avg_delivery_time"]):
            # Must be strictly better on at least one
            if (other["sla_compliance"] > point["sla_compliance"]
                    or other["fairness_std_dev"] < point["fairness_std_dev"]
                    or other["avg_delivery_time"] < point["avg_delivery_time"]):
                return True
    return False


def run_pareto_search(n_configs: int = 100, mode: str = "hungarian") -> dict:
    """Run N configurations and find the Pareto frontier."""
    logger.info("Starting Pareto search: %d configurations in %s mode", n_configs, mode)
    start = time.perf_counter()

    results: list[dict] = []

    for i in range(n_configs):
        weights = generate_random_weights()

        try:
            metrics = run_simulation(mode=mode, custom_weights=weights)
            summary = metrics["summary"]

            entry = {
                "config_id": i,
                "weights": weights,
                "sla_compliance": summary["sla_compliance_rate_percent"],
                "sla_violations": summary["sla_violations"],
                "fairness_std_dev": summary["fairness_std_dev"],
                "avg_delivery_time": summary["average_delivery_time"],
                "delivery_time_std_dev": summary["delivery_time_std_dev"],
                "avg_sla_margin": summary["average_sla_margin"],
            }
            results.append(entry)

            if (i + 1) % 10 == 0:
                logger.info(
                    "  [%d/%d] SLA=%.1f%% Fair=%.2f Avg=%.1f",
                    i + 1, n_configs,
                    entry["sla_compliance"],
                    entry["fairness_std_dev"],
                    entry["avg_delivery_time"],
                )
        except Exception as e:
            logger.warning("Config %d failed: %s", i, e)

    elapsed = time.perf_counter() - start
    logger.info("Search complete: %d configs in %.1fs", len(results), elapsed)

    # Identify Pareto frontier
    frontier: list[dict] = [r for r in results if not is_dominated(r, results)]
    frontier.sort(key=lambda x: x["sla_compliance"], reverse=True)

    # Pick recommended config: highest SLA compliance on frontier,
    # breaking ties by lowest fairness_std_dev
    recommended = max(
        frontier,
        key=lambda x: (x["sla_compliance"], -x["fairness_std_dev"], -x["avg_delivery_time"]),
    ) if frontier else results[0]

    output = {
        "search_params": {
            "n_configs": n_configs,
            "mode": mode,
            "elapsed_seconds": round(elapsed, 2),
        },
        "all_configurations": results,
        "pareto_frontier": frontier,
        "recommended": {
            "config_id": recommended["config_id"],
            "weights": recommended["weights"],
            "sla_compliance": recommended["sla_compliance"],
            "fairness_std_dev": recommended["fairness_std_dev"],
            "avg_delivery_time": recommended["avg_delivery_time"],
        },
    }

    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Routly Pareto Weight Search")
    parser.add_argument("--configs", type=int, default=100, help="Number of configurations")
    parser.add_argument("--mode", choices=["hungarian", "greedy"], default="hungarian")
    args = parser.parse_args()

    result = run_pareto_search(n_configs=args.configs, mode=args.mode)

    # Save
    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(base_dir, "output", "pareto_results.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    rec = result["recommended"]
    print("\n" + "=" * 60)
    print("  PARETO SEARCH COMPLETE")
    print("=" * 60)
    print(f"  Configurations tested:  {len(result['all_configurations'])}")
    print(f"  Pareto frontier size:   {len(result['pareto_frontier'])}")
    print(f"  Recommended weights:")
    for k, v in rec["weights"].items():
        print(f"    {k:10s} = {v:.4f}")
    print(f"  -> SLA Compliance:       {rec['sla_compliance']}%")
    print(f"  -> Fairness Std Dev:     {rec['fairness_std_dev']:.4f}")
    print(f"  -> Avg Delivery Time:    {rec['avg_delivery_time']:.2f} min")
    print("=" * 60)
    print(f"  Results saved to: {output_path}")


if __name__ == "__main__":
    main()
