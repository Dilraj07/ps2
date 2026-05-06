# Issues: Smart Delivery Dispatch System

## Issue 1: Load and Validate Order Data
**Labels**: `data-processing`

Load orders from CSV with attributes: order_id, timestamp, location, prep_time, priority. Validate all required fields are present and values are within valid ranges. Handle missing files and malformed data gracefully with descriptive error messages.

---

## Issue 2: Load and Validate Agent Data
**Labels**: `data-processing`

Load agents from CSV with attributes: agent_id, current_location, rating, availability. Initialize each agent with empty active_orders list and cumulative_assignments counter. Validate location references exist in environment graph.

---

## Issue 3: Load Environment Graph Data
**Labels**: `data-processing`

Load environment edges from CSV representing locations and travel times. Build a graph structure supporting distance queries between any two locations. Implement shortest path calculation (Floyd-Warshall for small graphs, Dijkstra for larger ones).

---

## Issue 4: Implement Priority Order Queue
**Labels**: `state-management`

Create a priority queue that processes orders by priority level (high > normal > low) and timestamp (FIFO within same priority). Support state transitions: PENDING → ASSIGNED → IN_TRANSIT → DELIVERED. Track orders by state for efficient queries.

---

## Issue 5: Implement Agent Registry
**Labels**: `state-management`

Maintain agent state including current_location, availability, active_orders (max 2), cumulative_assignments, and rating. Automatically update availability when active_orders changes. Support fast lookups by agent_id and availability status.

---

## Issue 6: Generate Assignment Candidates
**Labels**: `core-logic`

For each order, identify available agents (active_orders < 2) that can reach the order location. Filter out agents with no valid path to order location. Return list of feasible (agent, order) pairs for scoring.

---

## Issue 7: Implement Assignment Scoring Logic
**Labels**: `core-logic`, `optimization`

Score each candidate based on: delivery time (travel + prep), SLA risk (time until deadline), workload fairness (cumulative assignments), priority boost, and agent rating. Use configurable weights to balance objectives. Select best-scoring assignment.

---

## Issue 8: Balance Competing Objectives
**Labels**: `optimization`

Implement configurable weights for delivery time, SLA compliance, workload fairness, and priority handling. Allow tuning via config file. Document trade-offs between objectives and provide example configurations for different priorities.

---

## Issue 9: Apply Assignment Decisions
**Labels**: `state-management`

Update order state (PENDING → ASSIGNED), agent state (add to active_orders, update availability), and queue state. Validate assignment before applying (agent capacity, order state). Ensure atomic updates to maintain consistency.

---

## Issue 10: Simulate Delivery Completion
**Labels**: `state-management`

Transition orders through IN_TRANSIT → DELIVERED states. Update agent location to delivery destination. Remove order from active_orders and update agent availability. Check SLA deadline and record violations.

---

## Issue 11: Handle Order Queueing
**Labels**: `core-logic`, `error-handling`

When no agents are available, keep orders in PENDING state. When an agent completes a delivery, automatically attempt to assign highest-priority pending order. Track queue depth and log warnings for extended wait times.

---

## Issue 12: Calculate Delivery Time Metrics
**Labels**: `metrics`

Track average delivery time overall and by priority level (high, normal, low). Use Welford's algorithm for running mean and variance calculation. Update metrics incrementally as orders complete.

---

## Issue 13: Calculate SLA Compliance Metrics
**Labels**: `metrics`

Track SLA violations (delivery_time > sla_deadline) and calculate violation rate as percentage. Compute SLA compliance rate and average margin (deadline - delivery_time). Report separately by priority level.

---

## Issue 14: Calculate Workload Fairness Metrics
**Labels**: `metrics`

Calculate load variance and standard deviation across agents based on cumulative_assignments. Track min/max assignments and assignment range. Report fairness metrics to evaluate workload distribution.

---

## Issue 15: Output Metrics in Structured Format
**Labels**: `metrics`, `documentation`

Export all metrics (delivery time, SLA compliance, fairness, priority stats) in JSON format. Include summary statistics, breakdowns by priority, and metadata (timestamp, dataset). Provide human-readable summary alongside structured output.

---

## Issue 16: Handle Missing and Invalid Data
**Labels**: `error-handling`

Detect and handle missing CSV files, malformed rows, missing required fields, invalid values, and referential integrity violations. Log descriptive error messages with context (record ID, field, value). Skip invalid records and continue processing valid data.

---

## Issue 17: Handle Edge Cases
**Labels**: `error-handling`

Handle scenarios: no available agents (queue order), SLA deadline already passed (assign anyway with warning), empty candidate list, tie scores (use tiebreaker), disconnected graph locations. Log appropriate warnings for each case.

---

## Issue 18: Optimize Decision Latency
**Labels**: `performance`

Ensure assignment decisions complete within 500ms. Optimize candidate generation (< 100ms), travel time calculation (< 1ms per query), and scoring (< 300ms). Precompute shortest paths for small graphs. Cache expensive calculations. Log warnings when latency exceeds target.

---

## Issue 19: Ensure Real-Time Throughput
**Labels**: `performance`

Process at least 100 orders per minute. Handle continuous order arrivals without blocking. Update agent availability immediately after assignments and deliveries. Track throughput and log warnings if it drops below target.

---

## Issue 20: Document Architecture and Approach
**Labels**: `documentation`

Write README.md with team info (name, year, all-female indicator) and architecture description (200 words max). Explain decision logic approach, trade-offs between objectives, and justification for chosen strategy. Document any dataset augmentation used.
