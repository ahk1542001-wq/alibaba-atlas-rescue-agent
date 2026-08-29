---
name: flight_book
description: Books an approved flight option through the Atlas Sandbox if ticketing is available. Use only after the ApprovalGate resolves approve.
allowed-tools: atlas_call, approval_required
---

# Procedure

1. Confirm the ApprovalGate decision is approve for the chosen option_id.
2. Verify fare immediately before order creation; if price increased, pause and request price reapproval.
3. Preserve opaque identifiers (offer_id, order_id, booking_id) without normalization or alteration.
4. Call atlas_client create_booking_order with passenger refs; branch on normalized provider status/code.
5. If ticketing is unavailable (e.g. TICKETING_ACTIVATION_REQUIRED), preserve the trip plan without fabricating a PNR or ticket.
6. If ticketing succeeds, persist the BookingRecord (pnr, booked_at, monitor_armed=true).
7. Never automatically retry order creation, payment, or side-effect operations.
8. Privacy: never collect or log real payment credentials or passport numbers.

# Input-Output

- Input: FlightBookInput (services/skills/flight_book.py).
- Output: BookingRecord (models/schemas.py, §5).

# Verification

- §8 unit suite: idempotent retry safe; provider-code branching verified; price reapproval on fare increase; no PNR or ticket fabricated when ticketing is unavailable; booking gated by approval_required capability.
