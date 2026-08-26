---
name: itinerary
description: Builds the trip itinerary after booking, tagging flights real and suggestions honestly. Use once a BookingRecord is confirmed.
allowed-tools: llm_call
---

# Procedure

1. Start from the confirmed BookingRecord — flights stay source=atlas_real.
2. Enrich hotels/activities via the §15.2 provider chain (researched-mock default).
3. Tag every LLM-generated item source=llm_suggestion with a "💡 suggestion only" chip.
4. Respect budget_hint and profile prefs when ordering items.

# Input-Output

- Input: ItineraryInput (services/skills/itinerary.py) — BookingRecord + budget.
- Output: ItineraryItem[] (each tagged source=llm_suggestion|atlas_real).

# Verification

- §8 unit suite: every llm item carries the suggestion chip flag; researched
  mock entries carry as_of chip (F11, §15.2 labeling).
