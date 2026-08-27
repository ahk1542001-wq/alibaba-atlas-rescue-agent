---
name: location_resolve
description: Resolves cities, venues, and ambiguous airport codes into candidate IATA codes. Emits confirmation requirements for multi-airport cities (e.g. Bangkok -> BKK/DMK).
allowed-tools: network_read, llm_call
---

# Procedure

1. Parse origin/destination text and optional venue from TripGoal or input payload.
2. Resolve known landmark/venue references (e.g. "Marina Bay Sands" -> Singapore / SIN).
3. Identify city airport candidates (e.g. "Bangkok" -> [BKK, DMK]; "Singapore" -> [SIN]; "Yangon" -> [RGN]).
4. If a city has multiple commercial airports (e.g. Bangkok), set confirmation_required = true and return all candidate codes.
5. If an exact 3-letter IATA code is provided, validate and pass through with confirmation_required = false.

# Input-Output

- Input: LocationResolveInput (origin_text, destination_text, venue)
- Output: LocationResolveResult (origin_candidates[], destination_candidates[], confirmation_required, venue)

# Verification

- §8 / §4 unit tests prove Bangkok returns both BKK and DMK without silent selection; Marina Bay Sands resolves to SIN.
