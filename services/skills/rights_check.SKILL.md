---
name: rights_check
description: Determines the compensation regime for an airport pair with an honest NONE fallback. Use when a disruption is confirmed or the user asks about entitlements.
allowed-tools:
---

# Procedure

1. Resolve jurisdiction server-side from the airport pair via haversine.
2. Consult the frozen rights_engine regime tables — never invent amounts.
3. Emit regime + amount_range + legal_citation from those tables only.
4. No-regime case returns honest NONE rather than a guess.

# Input-Output

- Input: RightsCheckInput (services/skills/rights_check.py).
- Output: RightsOpinion (regime, amount_range, legal_citation).

# Verification

- §8 unit suite: haversine threshold matches regime table; no-regime case
  returns honest NONE (F6).
