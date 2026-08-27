---
name: safety_monitor
description: Consent-gated safety monitor. After the traveler enables monitoring, runs bounded rechecks and emits a SafetyChangeEvent ONLY on a material change (severity, affected region, validity period, recommended action), proposing — never executing — a partial replan through approval.
allowed-tools: network_read
---

# Procedure

1. Require explicit user consent before any recheck (consent_required
   otherwise; revoking consent clears stored state).
2. Bound the recheck cadence (minimum interval enforced; too-soon checks
   return recheck_too_soon, never hammer sources).
3. Re-run SafetyResearchSkill, hash the normalized APPLICABLE evidence and
   compare with the stored hash.
4. On a MATERIAL change only, emit a SafetyChangeEvent retaining old + new
   evidence and the identified differences (proposed_action="review",
   approval_required=true). Non-material drift never emits.
5. Alerts surface in trip state; push delivery (only with consent) goes
   through the existing guardian_push skill path — never here, and a change
   may only PROPOSE a partial replan via approval, never modify or rebook.

# Manifest placement note (honest record)

This manifest intentionally lives in services/safety/ instead of
services/skills/: the frozen manifest suite pins the services/skills/
loader-glob registry at exactly 11 entries (tests/test_skills_manifest.py),
and pre-existing tests are untouchable. The paired module is
services/skills/safety_monitor.py. Recorded in DECISIONS.tsv + PLAN.md.

# Input-Output

- Input: trip_id + SafetyQuery + research skill instance (check) OR
  {"trip_id", "enabled": bool} consent update (run).
- Output: {"status", "events": [SafetyChangeEvent...], ...}.

# Verification

- tests/test_safety.py: consent gate, bounded cadence, material vs
  non-material change, old/new evidence retained, approval_required=true.
