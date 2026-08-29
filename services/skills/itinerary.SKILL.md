---
name: itinerary
description: Builds the trip itinerary for pre-booking preview and post-booking confirmation, tagging flights honestly and suggestions with provenance.
allowed-tools: llm_call
---

# Procedure

1. In pre-booking preview, accepts a planned flight option (source=atlas_sandbox, booked=false, no PNR).
2. In post-booking confirmation, accepts confirmed BookingRecord (source=atlas_real, booked=true, with PNR).
3. Enrich hotels/activities via the §15.2 provider chain (researched-mock default).
4. Tag every LLM-generated item source=llm_suggestion with a "💡 suggestion only" chip.
5. Respect budget_hint and profile prefs when ordering items.

# Input-Output

- Input: ItineraryInput (services/skills/itinerary.py) — BookingRecord or planned flight option + budget.
- Output: ItineraryItem[] (each tagged source=llm_suggestion|atlas_real|atlas_sandbox|researched_mock).

# Verification

- §8 unit suite: every llm item carries the suggestion chip flag; researched
  mock entries carry as_of chip (F11, §15.2 labeling).
