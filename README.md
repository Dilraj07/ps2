# Smart Delivery Dispatch System

## Team Information
- **Team Name**: Greater N0ida
- **Year**: 2nd Year
- **All-Female Team**: No

## Architecture Overview

#### Routly — Event-Driven Multi-Factor Dispatch Engine

**Routly** is a robust, highly modular event-driven dispatch system. It is designed to maximize Service Level Agreement (SLA) compliance and system throughput through traffic-aware routing, continuous state evaluation, and optimal batch-assignments. The architecture strictly adheres to clear separation of concerns (SoC), organizing components into localized models, core execution logic, and isolated state registries.

### 1. Data Flow & Execution Pipeline
The core data flow of the application operates on a discrete-event simulation timeline:
1. **Bootstrapping:** Graph environments (10x10 grid), constraints, orders, and agents are ingested. Distance heuristics are pre-computed ($O(1)$ lookup guarantees).
2. **Event Scheduling:** Orders are mapped into `ORDER_ARRIVES` events and placed on a `heapq`-backed Min-Heap. This guarantees chronological event processing with $O(\log n)$ insertion and $O(1)$ retrieval.
3. **Event Loop:** The `SimulationEngine` perpetually pops the next event from the heap. State mutations cascade based on the `EventType`:
    *   **Arrival:** Adds order to `OrderQueue` and triggers the dispatch algorithm.
    *   **Prep Done:** Transitions order to `IN_TRANSIT` and schedules delivery event based on buffered travel times.
    *   **Delivery Done:** Updates agent capacity (freed up), updates agent location, records KPIs, and invokes immediate queue re-evaluation.
4. **Adaptive Feedback Loop:** The `AdaptiveWeightEngine` evaluates the outcome of each delivery, self-tuning heuristic weights if queue depth or SLA violations spike.
5. **Metrics Export:** Runtime KPIs are aggregated using Welford's algorithm and serialized into JSON payloads.

### 2. Algorithmic Optimizations
Our system abandons naïve first-come-first-serve for mathematical optimization and predictive heuristics:
*   **Hungarian Algorithm (Bipartite Matching):** The dispatch layer uses `scipy.optimize.linear_sum_assignment` to construct an $N \times M$ cost matrix of queued orders versus available agents. The Hungarian solver finds the global optimum that minimizes total system cost (or maximizes score), eliminating local-minima traps present in greedy assignment.
*   **Delay Buffer & Pathfinding:** Integrates a `DelayBuffer` that estimates traffic variations on the graph. The system uses Floyd-Warshall shortest paths computed at initialization, dynamically weighted by live delay factors to accurately predict travel times.
*   **Exponential Penalty Function:** When estimating agent SLA margins, the `Scorer` applies an exponential decay penalty ($0.5 \cdot e^{\text{margin}/5}$) to assignments risking SLA breaches, violently steering the algorithm away from late deliveries.

### 3. Priority-Aware Multi-Factor Scoring
The global cost matrix evaluates candidates using a dynamic, multi-factor normalized scoring matrix. The `Scorer` balances four metrics:
1. **SLA Compliance (Adaptive ~40%):** Enforces hard deadline constraints using the aforementioned exponential penalty.
2. **Traffic-Aware Travel (Adaptive ~30%):** Penalizes long routes and avoids graph edges marked with high-risk traffic delays.
3. **Workload Fairness (Adaptive ~20%):** Evaluates agent cumulative assignments to prevent uneven workforce utilization.
4. **Agent Rating (Adaptive ~10%):** Prioritizes high-performing agents.

High-priority orders apply a **1.5x base multiplier** across their row in the cost matrix, ensuring the Hungarian solver organically routes top resources to premium requests without breaking batch efficiency.


**Note:** Please do not change the format or spelling of anything in this README. The fields are extracted using a script, so any changes to the structure or formatting may break the extraction process.
