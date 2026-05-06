# Smart Delivery Dispatch System

## Team Information
- **Team Name**: Greater N0ida
- **Year**: 2nd Year
- **All-Female Team**: No

## Architecture Overview

#### Routly — Event-Driven Multi-Factor Dispatch Engine

    - Our dispatch strategy uses an event-driven simulation engine processing orders through a priority-aware scoring matrix. For each incoming order, we score all available agents (max 2 active orders, valid path required) and select the highest-scoring match.
    - Agent scoring balances four normalized metrics: SLA compliance margin (40% weight, with exponential penalties for violations), estimated delivery time (30%), workload fairness (20%), and agent rating (10%). High-priority orders receive a 1.5x final multiplier.
    - SLA deadlines are enforced via an exponential penalty function — assignments risking deadline breaches receive deeply negative scores, ensuring the system avoids late deliveries as a last resort. Agent capacity is tracked dynamically: availability is a computed property checking active order count against the max of 2.
    - Pipeline: (1) Load environment graph and run Floyd-Warshall once on the 10x10 grid, accounting for edge delay multipliers, guaranteeing O(1) distance queries. (2) Schedule all orders as arrival events on a min-heap timeline. (3) Process events sequentially — assign, prep, deliver. (4) On delivery completion, update agent location and immediately re-evaluate pending orders. (5) Collect running statistics via Welford's algorithm and export structured JSON metrics.


**Note:** Please do not change the format or spelling of anything in this README. The fields are extracted using a script, so any changes to the structure or formatting may break the extraction process.
