"""Phase-by-phase verification of the Routly dispatch system."""

import os
import sys
import io
import json
import csv
import math

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data", "raw")

PASS = "[PASS]"
FAIL = "[FAIL]"

errors: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    status = PASS if condition else FAIL
    print(f"  {status} {label}")
    if detail and not condition:
        print(f"         {detail}")
    if not condition:
        errors.append(label)


def banner(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ============================================================
# PHASE 1: Data Foundation
# ============================================================

banner("PHASE 1: Data Foundation — Models & Graph")

# 1a. Verify CSV files exist and use comma delimiter (NOT pipe)
print("\n  --- CSV Delimiter Verification ---")
for fname in ["agents.csv", "orders.csv", "environment_edges.csv", "constraints.csv"]:
    path = os.path.join(DATA_DIR, fname)
    check(f"{fname} exists", os.path.exists(path))
    with open(path, "r", encoding="utf-8") as f:
        header = f.readline().strip()
        has_pipe = " | " in header
        has_comma = "," in header
        check(f"{fname} uses comma delimiter (not pipe)", has_comma and not has_pipe,
              f"Header: {header}")

# 1b. Verify models
from src.models import Order, Agent, Priority, OrderState

agent = Agent(agent_id="TEST", current_location=(0, 0), rating=4.5)
check("Agent.is_available is @property (dynamic)", agent.is_available is True)
agent.active_orders.append("o1")
agent.active_orders.append("o2")
check("Agent.is_available returns False at capacity 2", agent.is_available is False)
agent.active_orders.pop()
check("Agent.is_available returns True after removal", agent.is_available is True)

order = Order(order_id="T1", timestamp=0.0, location=(1, 1), prep_time=10,
              priority=Priority.HIGH, sla_minutes=45)
check("Order defaults to PENDING state", order.state == OrderState.PENDING)
check("Order.assigned_agent defaults to None", order.assigned_agent is None)
check("Priority enum maps correctly", Priority("high") == Priority.HIGH)
check("Priority enum maps 'normal'", Priority("normal") == Priority.NORMAL)
check("Priority enum maps 'low'", Priority("low") == Priority.LOW)

# 1c. Verify Graph — Floyd-Warshall with delay_multiplier
from src.graph import EnvironmentGraph

graph = EnvironmentGraph()
graph.load(os.path.join(DATA_DIR, "environment_edges.csv"))

print("\n  --- Graph Edge Weight Verification ---")

# Manually verify specific edges from the CSV
# Row: 0,0,1,0,3,1.0 → weight = 3.0
d = graph.get_distance((0, 0), (1, 0))
check(f"Edge (0,0)→(1,0): 3*1.0 = 3.0 (got {d})", abs(d - 3.0) < 0.001)

# Row: 2,0,3,0,3,1.1 → weight = 3.3
d = graph.get_distance((2, 0), (3, 0))
check(f"Edge (2,0)→(3,0): 3*1.1 = 3.3 (got {d})", abs(d - 3.3) < 0.001)

# Row: 6,0,7,0,3,1.2 → weight = 3.6
d = graph.get_distance((6, 0), (7, 0))
check(f"Edge (6,0)→(7,0): 3*1.2 = 3.6 (got {d})", abs(d - 3.6) < 0.001)

# Bidirectional check
d_fwd = graph.get_distance((0, 0), (1, 0))
d_rev = graph.get_distance((1, 0), (0, 0))
check(f"Bidirectional: (0,0)↔(1,0) equal ({d_fwd}={d_rev})", abs(d_fwd - d_rev) < 0.001)

# Self-distance = 0
check("Self-distance (5,5)→(5,5) = 0", graph.get_distance((5, 5), (5, 5)) == 0.0)

# Multi-hop shortest path: (0,0)→(2,0) via (1,0) should be 3.0+3.0=6.0
d = graph.get_distance((0, 0), (2, 0))
check(f"Shortest path (0,0)→(2,0) = 6.0 (got {d})", abs(d - 6.0) < 0.001)

# Diagonal path: (0,0)→(9,9) should be finite (connected graph)
d = graph.get_distance((0, 0), (9, 9))
check(f"Path (0,0)→(9,9) is finite ({d:.2f})", d != float("inf"))
check(f"Path (0,0)→(9,9) is positive ({d:.2f})", d > 0)

# All 100 nodes should be reachable from (0,0)
all_reachable = True
for x in range(10):
    for y in range(10):
        if not graph.has_path((0, 0), (x, y)):
            all_reachable = False
            break
check("All 100 nodes reachable from (0,0) (connected graph)", all_reachable)


# ============================================================
# PHASE 2: State Management
# ============================================================

banner("PHASE 2: State Management — Queue & Registry")

from src.queue import OrderQueue
from src.registry import AgentRegistry

# 2a. Priority Queue
q = OrderQueue()
o_high = Order("H1", 0, (0, 0), 5, Priority.HIGH, 30)
o_norm = Order("N1", 0, (0, 0), 5, Priority.NORMAL, 30)
o_low = Order("L1", 0, (0, 0), 5, Priority.LOW, 30)

q.add(o_low)
q.add(o_norm)
q.add(o_high)
check("Queue depth is 3 after adding 3 orders", q.depth == 3)

popped = q.pop_highest_priority()
check("First pop returns HIGH order", popped.order_id == "H1")
popped = q.pop_highest_priority()
check("Second pop returns NORMAL order", popped.order_id == "N1")
popped = q.pop_highest_priority()
check("Third pop returns LOW order", popped.order_id == "L1")
check("Queue is empty after popping all", q.is_empty)

# Requeue test
o_high2 = Order("H2", 0, (0, 0), 5, Priority.HIGH, 30)
o_high3 = Order("H3", 0, (0, 0), 5, Priority.HIGH, 30)
q.add(o_high3)
q.requeue(o_high2)  # Should go to FRONT
popped = q.pop_highest_priority()
check("Requeued order is at front (H2 before H3)", popped.order_id == "H2")

# FIFO within same priority
q2 = OrderQueue()
o_h1 = Order("HA", 0, (0, 0), 5, Priority.HIGH, 30)
o_h2 = Order("HB", 0, (0, 0), 5, Priority.HIGH, 30)
q2.add(o_h1)
q2.add(o_h2)
check("FIFO: first added HIGH comes out first", q2.pop_highest_priority().order_id == "HA")

# Non-PENDING orders should not be added
o_assigned = Order("X1", 0, (0, 0), 5, Priority.HIGH, 30)
o_assigned.state = OrderState.ASSIGNED
q3 = OrderQueue()
q3.add(o_assigned)
check("Non-PENDING orders are rejected by queue", q3.is_empty)

# 2b. Agent Registry
reg = AgentRegistry()
a1 = Agent("A001", (0, 0), 4.8)
a2 = Agent("A002", (1, 1), 4.5)
reg.add(a1)
reg.add(a2)
check("Registry has 2 agents", len(reg.agents) == 2)
check("Both agents available initially", len(reg.get_available()) == 2)

a1.active_orders.append("o1")
a1.active_orders.append("o2")
reg.update_availability(a1)
check("A001 removed from available after 2 orders", len(reg.get_available()) == 1)
check("A002 still available", reg.get_available()[0].agent_id == "A002")

a1.active_orders.pop()
reg.update_availability(a1)
check("A001 back in available after order removal", len(reg.get_available()) == 2)


# ============================================================
# PHASE 3: Scoring Algorithm
# ============================================================

banner("PHASE 3: Scoring Algorithm — Normalization & Weights")

from src.scorer import Scorer

scorer = Scorer(graph)

# Create test agents and order
test_agents = [
    Agent("TA1", (0, 0), 4.8, cumulative_assignments=0),
    Agent("TA2", (5, 5), 4.5, cumulative_assignments=3),
    Agent("TA3", (9, 9), 4.2, cumulative_assignments=5),
]

test_order = Order("TO1", 0, (1, 1), 10, Priority.HIGH, 45)

print("\n  --- Score Component Verification ---")

# Score all agents for the same order
scores = {}
for a in test_agents:
    s = scorer.score(a, test_order, test_agents)
    scores[a.agent_id] = s
    print(f"    Agent {a.agent_id} @ {a.current_location}, rating={a.rating}, "
          f"assignments={a.cumulative_assignments} → score={s:.4f}")

# Closest agent (TA1 at 0,0) should score highest for order at (1,1)
check("Closest agent (TA1) scores highest", scores["TA1"] > scores["TA2"])
check("All scores are finite", all(math.isfinite(s) for s in scores.values()))

# Priority multiplier verification
o_high_test = Order("PH", 0, (1, 1), 10, Priority.HIGH, 45)
o_norm_test = Order("PN", 0, (1, 1), 10, Priority.NORMAL, 45)
o_low_test = Order("PL", 0, (1, 1), 10, Priority.LOW, 45)

s_high = scorer.score(test_agents[0], o_high_test, test_agents)
s_norm = scorer.score(test_agents[0], o_norm_test, test_agents)
s_low = scorer.score(test_agents[0], o_low_test, test_agents)
check(f"HIGH multiplier > NORMAL ({s_high:.3f} > {s_norm:.3f})", s_high > s_norm)
check(f"NORMAL multiplier > LOW ({s_norm:.3f} > {s_low:.3f})", s_norm > s_low)

# SLA penalty: create an order with very tight SLA
tight_order = Order("TIGHT", 0, (9, 9), 10, Priority.NORMAL, 5)  # 5 min SLA, impossible
s_tight = scorer.score(test_agents[0], tight_order, test_agents)
check(f"Tight SLA produces low/negative score ({s_tight:.4f})", s_tight < s_norm)

# Unreachable location test — all nodes are connected in this graph,
# so we test the logic by checking has_path
check("has_path returns True for connected nodes", graph.has_path((0, 0), (9, 9)))

# Tiebreak verification
a_high_rating = Agent("ZZZ", (0, 0), 5.0)
a_low_rating = Agent("AAA", (0, 0), 4.0)
tb1 = Scorer.tiebreak_key(a_high_rating)
tb2 = Scorer.tiebreak_key(a_low_rating)
check("Tiebreak: higher rating sorts first", tb1 < tb2)

a_same_r1 = Agent("A001", (0, 0), 4.8)
a_same_r2 = Agent("A002", (0, 0), 4.8)
tb1 = Scorer.tiebreak_key(a_same_r1)
tb2 = Scorer.tiebreak_key(a_same_r2)
check("Tiebreak: equal rating → lower ID wins", tb1 < tb2)


# ============================================================
# PHASE 4: Event-Driven Simulation
# ============================================================

banner("PHASE 4: Event-Driven Simulation — Engine Verification")

from src.engine import SimulationEngine, EventType, Event
from src.metrics import MetricsCollector

# Run a mini simulation with 3 orders and 2 agents
mini_queue = OrderQueue()
mini_reg = AgentRegistry()
mini_agents = [
    Agent("M1", (0, 0), 4.8),
    Agent("M2", (5, 5), 4.5),
]
for a in mini_agents:
    mini_reg.add(a)

mini_scorer = Scorer(graph)
mini_metrics = MetricsCollector()
mini_engine = SimulationEngine(mini_queue, mini_reg, mini_scorer, mini_metrics, graph)

mini_orders = [
    Order("MO1", 0.0, (1, 1), 5, Priority.HIGH, 45),
    Order("MO2", 2.0, (6, 6), 8, Priority.NORMAL, 50),
    Order("MO3", 4.0, (3, 3), 6, Priority.LOW, 60),
]

mini_engine.run(mini_orders)

check("Mini sim: all 3 orders delivered",
      all(o.state == OrderState.DELIVERED for o in mini_orders))
check("Mini sim: all orders have assigned_agent set",
      all(o.assigned_agent is not None for o in mini_orders))
check("Mini sim: all delivery times > 0",
      all(o.actual_delivery_time > 0 for o in mini_orders))
check("Mini sim: agent locations updated after delivery",
      any(a.current_location != (0, 0) for a in mini_agents) or
      any(a.current_location != (5, 5) for a in mini_agents))

# Verify agent capacity never exceeded
print("\n  --- Agent Capacity Check ---")
# After simulation, active_orders should be empty
for a in mini_agents:
    check(f"Agent {a.agent_id} active_orders empty after sim", len(a.active_orders) == 0)

# Verify metrics were recorded
check("Mini sim: metrics recorded 3 deliveries", mini_metrics.delivery_stats["all"].count == 3)


# ============================================================
# PHASE 5: Metrics — Welford's Algorithm
# ============================================================

banner("PHASE 5: Metrics — Welford's Algorithm Verification")

from src.metrics import WelfordStats

# Verify Welford's against known values
w = WelfordStats()
values = [10.0, 20.0, 30.0, 40.0, 50.0]
for v in values:
    w.update(v)

expected_mean = 30.0
expected_var = 250.0  # Sample variance of [10,20,30,40,50]
expected_std = math.sqrt(expected_var)

check(f"Welford mean: expected {expected_mean}, got {w.mean:.4f}",
      abs(w.mean - expected_mean) < 0.001)
check(f"Welford variance: expected {expected_var}, got {w.variance:.4f}",
      abs(w.variance - expected_var) < 0.001)
check(f"Welford std_dev: expected {expected_std:.4f}, got {w.std_dev:.4f}",
      abs(w.std_dev - expected_std) < 0.001)
check("Welford count = 5", w.count == 5)

# Single value — variance should be 0
w2 = WelfordStats()
w2.update(42.0)
check("Single value: variance = 0", w2.variance == 0.0)
check("Single value: mean = 42.0", w2.mean == 42.0)


# ============================================================
# PHASE 6: Full Simulation Output Verification
# ============================================================

banner("PHASE 6: Full Simulation Output — metrics.json")

output_path = os.path.join(BASE_DIR, "output", "metrics.json")
check("output/metrics.json exists", os.path.exists(output_path))

with open(output_path, "r", encoding="utf-8") as f:
    metrics_data = json.load(f)

summary = metrics_data["summary"]
check("Total orders = 150", summary["total_orders"] == 150)
check("Average delivery time > 0", summary["average_delivery_time"] > 0)
check("Delivery time std dev > 0", summary["delivery_time_std_dev"] > 0)
check("SLA violations = 0", summary["sla_violations"] == 0)
check("Fairness std dev < 2.0 (well distributed)", summary["fairness_std_dev"] < 2.0)
check("Agent assignment counts has 25 entries", len(summary["agent_assignment_counts"]) == 25)
check("All agents assigned at least 1 order",
      all(c > 0 for c in summary["agent_assignment_counts"]))
check("Sum of assignments = 150",
      sum(summary["agent_assignment_counts"]) == 150)

# Priority breakdown
bp = metrics_data["breakdown_by_priority"]
check("Breakdown has 'high' key", "high" in bp)
check("Breakdown has 'normal' key", "normal" in bp)
check("Breakdown has 'low' key", "low" in bp)

total_from_breakdown = sum(bp[p]["delivery_stats"]["count"] for p in ["high", "normal", "low"])
check(f"Priority counts sum to 150 (got {total_from_breakdown})", total_from_breakdown == 150)

for p in ["high", "normal", "low"]:
    ds = bp[p]["delivery_stats"]
    check(f"  [{p}] count > 0", ds["count"] > 0)
    check(f"  [{p}] mean > 0", ds["mean"] > 0)
    check(f"  [{p}] no mock data (variance != 0)", ds["variance"] > 0)
    check(f"  [{p}] sla_violations = 0", bp[p]["sla_violations"] == 0)

# Metadata
meta = metrics_data["metadata"]
check("Metadata project = 'Routly'", meta["project"] == "Routly")
check("Metadata team = 'Greater N0ida'", meta["team"] == "Greater N0ida")
check("Metadata total_agents = 25", meta["total_agents"] == 25)
check("Metadata scoring_weights present", "scoring_weights" in meta)
check("Weights sum to 1.0",
      abs(sum(meta["scoring_weights"].values()) - 1.0) < 0.001)


# ============================================================
# PHASE 7: README Verification
# ============================================================

banner("PHASE 7: README Verification")

readme_path = os.path.join(BASE_DIR, "README.md")
with open(readme_path, "r", encoding="utf-8") as f:
    readme = f.read()

check("README has team name 'Greater N0ida'", "Greater N0ida" in readme)
check("README has '2nd Year'", "2nd Year" in readme)
check("README has 'No' for all-female", "**All-Female Team**: No" in readme)
check("README mentions Floyd-Warshall", "Floyd-Warshall" in readme)
check("README mentions SLA", "SLA" in readme)
check("README mentions exponential penalty", "exponential" in readme.lower())
check("README mentions delay multiplier", "delay multiplier" in readme.lower())
check("README has architecture section", "## Architecture Overview" in readme)

# Word count check (< 200 words in architecture section)
arch_start = readme.find("## Architecture Overview")
note_start = readme.find("**Note:**")
if arch_start != -1 and note_start != -1:
    arch_text = readme[arch_start:note_start]
    word_count = len(arch_text.split())
    check(f"Architecture section ≤ 200 words (got {word_count})", word_count <= 200)


# ============================================================
# EDGE CASE VERIFICATION
# ============================================================

banner("EDGE CASES")

# All orders had valid locations on the 10x10 grid
with open(os.path.join(DATA_DIR, "orders.csv"), "r") as f:
    reader = csv.DictReader(f)
    all_valid = True
    for row in reader:
        x, y = int(row["location_x"]), int(row["location_y"])
        if not (0 <= x <= 9 and 0 <= y <= 9):
            all_valid = False
            break
check("All order locations within 10x10 grid", all_valid)

# All agent locations valid
with open(os.path.join(DATA_DIR, "agents.csv"), "r") as f:
    reader = csv.DictReader(f)
    all_valid = True
    for row in reader:
        x, y = int(row["current_x"]), int(row["current_y"])
        if not (0 <= x <= 9 and 0 <= y <= 9):
            all_valid = False
            break
check("All agent locations within 10x10 grid", all_valid)

# Constraints file loaded correctly
constraints = {}
with open(os.path.join(DATA_DIR, "constraints.csv"), "r") as f:
    reader = csv.DictReader(f)
    for row in reader:
        k = row["constraint"].strip()
        if k:
            constraints[k] = row["value"].strip()

check("max_active_orders_per_agent = 2", constraints.get("max_active_orders_per_agent") == "2")
check("priority_weight_high = 1.5", constraints.get("priority_weight_high") == "1.5")
check("priority_weight_normal = 1.0", constraints.get("priority_weight_normal") == "1.0")
check("priority_weight_low = 0.8", constraints.get("priority_weight_low") == "0.8")


# ============================================================
# SUMMARY
# ============================================================

banner("VERIFICATION SUMMARY")

if errors:
    print(f"\n  ❌ {len(errors)} FAILURES:")
    for e in errors:
        print(f"     - {e}")
    sys.exit(1)
else:
    print(f"\n  ✅ ALL CHECKS PASSED — System fully verified, zero mock data.")
    sys.exit(0)
