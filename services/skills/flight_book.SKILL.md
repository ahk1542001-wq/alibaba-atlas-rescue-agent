---
name: flight_book
description: Books an approved flight option through the Atlas sandbox and returns a PNR. Use only after the ApprovalGate resolves approve.
allowed-tools: atlas_call, approval_required
---

# Procedure

1. Confirm the ApprovalGate decision is approve for the chosen option_id.
2. Call atlas_client book + pay sandbox flow with passenger refs.
3. Persist the BookingRecord (pnr, booked_at, monitor_armed=true).
4. Retry path is idempotent: same option_id returns the same PNR.

# Input-Output

- Input: FlightBookInput (services/skills/flight_book.py).
- Output: BookingRecord (models/schemas.py, §5).

# Verification

- §8 unit suite: idempotent retry safe; PNR persisted; booking gated by
  approval_required capability (F3, loop L2).
