---
name: flight_search
description: Searches the Atlas Sandbox for flights and returns ranked option cards. Use when the TripGoal carries route and dates.
allowed-tools: atlas_call, network_read
---

# Procedure

1. Call atlas_client.search() with origin/destination/date window/passengers.
2. Preserve opaque identifiers (search_id, offer_id) exactly as returned by provider.
3. Preserve provider currency and compute complete passenger totals for comparison.
4. Distinguish reference prices from verified offer prices (price status).
5. For flexible dates, execute each bounded date search completely without silent sampling.
6. Rank options honestly without relabeling currencies.

# Input-Output

- Input: FlightSearchInput (services/skills/flight_search.py).
- Output: FlightOption[] (models/schemas.py, §5).

# Verification

- §8 integration suite hits the live sandbox; opaque IDs preserved; complete passenger totals used; response provenance flagged sandbox; UI copy says "Atlas Sandbox data".
