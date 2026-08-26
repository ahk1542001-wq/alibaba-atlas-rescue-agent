---
name: visa_check
description: Checks entry/transit requirements for a passport against a route with dated citations. Use when an itinerary crosses borders or the user asks visa questions.
allowed-tools: network_read
---

# Procedure

1. Look up the KG seed (kg_seed.json) for a static baseline answer (<50ms).
2. Enrich via web_intel citations when freshness is needed (source_url + retrieved_date).
3. Emit VisaRequirement[] with risk_level and as_of dates.
4. Network failure degrades silently to baseline-only, visibly labeled.

# Input-Output

- Input: VisaCheckInput (services/skills/visa_check.py).
- Output: VisaRequirement[] (models/schemas.py, §5).

# Verification

- §8 unit suite: MM+FRA case returns Schengen ATV flag with citation;
  offline mode returns baseline-only marker (F4, §7 rules).
