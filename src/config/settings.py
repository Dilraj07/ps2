import os
from src.models.datatypes import Agent
from src.core.scorer import Scorer
from src.data_access.loader import _safe_read_csv

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
