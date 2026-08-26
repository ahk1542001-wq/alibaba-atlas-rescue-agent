---
name: clarify_loop
description: Asks only the missing questions and surfaces confirmation chips for inferred facts. Use after goal intake while TripGoal fields stay incomplete.
allowed-tools: llm_call
---

# Procedure

1. Diff TripGoal against the user Profile — skip anything already known (F2).
2. Ask only the missing facts, one conversational turn at a time.
3. For every inferred fact emit a ConfirmationChip (pending) and wait.
4. Save confirmed facts via profile_capture; rejected chips discard the value.

# Input-Output

- Input: ClarifyLoopInput (services/skills/clarify_loop.py) — TripGoal + user_id.
- Output: pending questions + ConfirmationChip[] (models/schemas.py, §5).

# Verification

- §8 ClarifyLoop unit suite: zero redundant questions when profile complete;
  every inferred fact requires chip confirmation before save (F2, loop L1).
