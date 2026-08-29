---
name: clarify_loop
description: Asks only the missing questions and surfaces confirmation chips for inferred facts. Use after goal intake while TripGoal fields stay incomplete.
allowed-tools: llm_call
visibility: internal
---

# Procedure

1. Diff TripGoal against the user Profile — skip anything already known or confirmed (F2).
2. Ask only genuinely missing facts, one conversational turn at a time.
3. If scope is ambiguous, present exactly three scope choices (flights only, flights + booking, complete trip).
4. Ask for passport country only when required for international travel, explaining: "Needed to check entry and transit requirements."
5. Never ask for passport number, legal identity, or payment details.
6. For every inferred fact emit a ConfirmationChip (pending) and wait.
7. Save confirmed facts to profile only with user consent; never silently persist.

# Input-Output

- Input: ClarifyLoopInput (services/skills/clarify_loop.py) — TripGoal + user_id.
- Output: pending questions + ConfirmationChip[] (models/schemas.py, §5).

# Verification

- §8 ClarifyLoop unit suite: zero redundant questions when profile complete; one question asked at a time; scope clarification handled; no silent persistence; inferred facts require chip confirmation before save (F2, loop L1).
