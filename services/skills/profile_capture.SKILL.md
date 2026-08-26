---
name: profile_capture
description: Captures personal facts into the profile with source tags after confirmation. Use when clarification reveals personal facts or the user edits fields.
allowed-tools: profile_write
---

# Procedure

1. Conflict-check the incoming field/value against the existing Profile.
2. Emit a ConfirmationChip carrying proposed_value and message (state=pending).
3. On confirm: write via ProfileStore with source tag (user | ai_inferred).
4. On reject: discard; nothing is persisted. Silent save is impossible.

# Input-Output

- Input: ProfileCaptureInput (services/skills/profile_capture.py).
- Output: ConfirmationChip then Profile patch (models/schemas.py, §5).

# Verification

- §8 ProfileStore unit suite: silent-save impossible (exception path proven);
  source tags recorded; delete clears field not file (F5).
