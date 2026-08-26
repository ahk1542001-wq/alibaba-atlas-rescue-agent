---
name: disruption_monitor
description: Watches an active PNR for disruption events and triggers the recovery subgraph. Use while an active booking exists.
allowed-tools: network_read
---

# Procedure

1. Poll the radar/SSE feed for the monitored flight_ids (services.radar).
2. On disruption detected, emit a DisruptionEvent to the orchestrator.
3. Orchestrator mounts the RecoveryDAG subgraph; trace appended to graph state.
4. Return control to the Options node after recovery completes (loop L3).

# Input-Output

- Input: DisruptionMonitorInput (services/skills/disruption_monitor.py).
- Output: DisruptionEvent? (models/schemas.py, §5).

# Verification

- §8 integration: simulated disruption hook triggers the subgraph within 2s
  and appends trace (F7, loop L3).
