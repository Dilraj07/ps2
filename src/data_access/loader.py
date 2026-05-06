import csv
import logging
import os
from datetime import datetime
from typing import Optional

from src.models.datatypes import Order, Agent, Priority

logger = logging.getLogger("routly.loader")

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
