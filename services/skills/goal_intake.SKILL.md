---
name: goal_intake
description: Parses free-text travel goals into a structured TripGoal. Use when the user submits a trip request in any phrasing.
allowed-tools: llm_call
---

# Procedure

1. Receive the user's free-text goal (any phrasing, incl. Burmese-flavored English).
2. Extract origin/destination/date window/passengers/budget/purpose via LLM.
3. Track passenger count explicitly vs defaulted (do not claim defaulted count came from user).
4. Preserve user budget amount and currency without relabeling.
5. Validate extracted facts into a TripGoal (models/schemas.py §5).
6. Privacy: never extract, store, or ask for passport number, legal identity, or payment credentials.
7. Persist the goal into the active trip session.

# Input-Output

- Input: GoalIntakeInput (services/skills/goal_intake.py) — wraps §5 TripGoal fields.
- Output: TripGoal (models/schemas.py, §5).

# Verification

- §8 golden-phrase unit suite: ≥10 phrasings parse without error; passenger tracking explicit; privacy boundary verified (F1).
