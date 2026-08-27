---
name: recovery_plan
description: Prepares recovery flight alternatives and creates an immutable approval request following a confirmed flight disruption. Never books without explicit approval.
allowed-tools: atlas_call, llm_call, approval_required
---

# Procedure

1. Receive confirmed DisruptionEvent, current booking, and trip context.
2. Query Atlas sandbox (or RescueEngine) for replacement flights on the affected route.
3. Rank alternative rescue packages (Fastest, Cheapest, Same-Airline) and assess rights/visa impacts.
4. Construct an ApprovalRequest with immutable option snapshot, price snapshot, and expiration timestamp.
5. Suspend execution at the recovery approval gate; NEVER execute a booking API call before explicit user approval.

# Input-Output

- Input: RecoveryPlanInput (trip_id, booking, disruption_event)
- Output: RecoveryPlanResult (recovery_options[], approval_request, rights_opinion)

# Verification

- §8 / §4 unit tests verify that recovery alternatives are generated with an ApprovalRequest and no booking call occurs prior to approval.
