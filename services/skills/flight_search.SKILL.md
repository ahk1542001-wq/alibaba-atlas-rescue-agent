---
name: flight_search
description: Searches the Atlas sandbox for flights and returns ranked option cards. Use when the TripGoal carries route and dates.
allowed-tools: atlas_call, network_read
---

# Procedure

1. Call atlas_client.search() with origin/destination/date window/passengers.
2. Normalize responses into FlightOption objects (sandbox_provenance=true).
3. Rank options by duration/price pareto for the OptionsCard.
4. Never serve canned arrays — results must carry live-sandbox provenance.

# Input-Output

- Input: FlightSearchInput (services/skills/flight_search.py).
- Output: FlightOption[] (models/schemas.py, §5).

# Verification

- §8 integration suite hits the live sandbox; response provenance flagged
  sandbox; UI copy says "Atlas Sandbox data" (F3).
