---
name: profile_edit
module: services.skills.profile_edit
class: ProfileEditSkill
description: when user edits profile facts via UI or chat
input_model: dict
output_model: dict
allowed-tools:
  - profile_read
  - profile_write
---

# Procedure

1. Accept only an explicit user-authored edit for one safe profile field.
2. Apply the ProfileStore allowlist and consent-gated persistence rules.
3. When `delete=true`, clear only the selected field and preserve the profile.

# Input-Output

- Input: `user_id`, `field`, `value`, `source=user`, and optional `delete=true`.
- Output: operation result plus the export-safe updated Profile.

# Verification

- S3 behavior tests cover update, delete-one-field, source enforcement, and
  ProfileStore allowlist failures.
