# TravelCare AI v2 — Durable Proof Index

This document maps the canonical product requirements in
`docs/MASTER_BUILD_PACKAGE.md` to runtime code and executable proof. Live test
results, branch positions, timings, and host-specific paths are intentionally
reported in the execution handoff instead of being frozen here.

## Product and Safety Boundaries

- Flight search, booking, and disruption scenarios use Atlas Sandbox or
  explicitly labeled deterministic fixtures.
- Unknown flight-status lookups return `UNKNOWN` without route, cancellation,
  or compensation facts. Claims cannot use client-supplied airport hints as
  provider truth.
- Booking and recovery actions require their matching approval and
  idempotency boundaries.
- Guardian delivery requires the token, destination chat, and explicit live
  test flag; otherwise it produces a redacted simulated preview. Live delivery
  uses plain text, does not block the event loop, and exposes only generic
  rejection codes.
- Traveler profiles exclude passport numbers and use allowlisted fields.
- Provider failures return generic API errors and type/code-only logs; custom
  provider URLs and raw response messages are not exposed as telemetry labels.
- No repository workflow authorizes push, deployment, publication, a live
  booking, or use of real traveler data.
- Hermetic test runs never edit `BLOCKERS.md`; transient Atlas Sandbox
  unavailability is reported in test output while the documented curated
  fallback remains explicitly labeled.

## F1–F20 Proof Map

| ID | Requirement | Runtime implementation | Executable proof |
|---|---|---|---|
| F1 | Conversational goal intake | `services/skills/goal_intake.py`, `routers/v1/trip.py` | `tests/test_skills_behavior.py`, `tests/test_e2e_trip_journey.py` |
| F2 | Clarification loop | `services/skills/clarify_loop.py`, `services/skills/profile_capture.py` | `tests/test_skills_behavior.py`, `tests/test_canonical_gaps.py` |
| F3 | Flight search and booking | `services/skills/flight_search.py`, `services/skills/flight_book.py`, `services/atlas_client.py` | `tests/test_skills_behavior.py`, `tests/test_e2e_trip_journey.py` |
| F4 | Hybrid visa checks | `services/skills/visa_check.py`, `services/visa_guard.py`, `services/web_intel_client.py` | `tests/test_skills_behavior.py`, `tests/test_web_intel.py` |
| F5 | Profile store and editing | `services/profile_store.py`, `routers/v1/profile.py`, `services/skills/profile_edit.py` | `tests/test_profile_store.py`, `tests/test_privacy.py` |
| F6 | Passenger-rights and claims | `services/rights_engine.py`, `services/skills/rights_check.py`, `routers/v1/claims.py` | `tests/test_rights_and_visa.py`, `tests/test_claims_provider_truth.py` |
| F7 | Recovery graph | `services/state_graph.py`, `services/skills/recovery_plan.py`, `routers/v1/trip.py` | `tests/test_canonical_gaps.py`, `tests/test_e2e_trip_journey.py` |
| F8 | Guardian notifications | `services/guardian.py`, `services/skills/guardian_push.py` | `tests/test_rights_and_visa.py`, `tests/test_privacy.py` |
| F9 | Live journey graph | `static/trip.js`, `static/index.html` | `tests/test_ui_trip.py` |
| F10 | Cross-run memory | `services/profile_store.py`, `routers/v1/trip.py` | `tests/test_e2e_trip_journey.py`, `tests/test_ui_trip.py` |
| F11 | Provenance and honesty labels | `services/skills/itinerary.py`, `static/trip.js`, `static/app.js` | `tests/test_canonical_gaps.py`, `tests/test_ui_trip.py` |
| F12 | Runtime skill registry | `services/skills/__init__.py`, `routers/v1/skills.py` | `tests/test_skills_manifest.py` |
| F13 | Location resolution | `services/skills/location_resolve.py` | `tests/test_skills_behavior.py`, `tests/test_ui_trip.py` |
| F14 | Idempotent booking | `routers/v1/trip.py`, `routers/v1/bookings.py` | `tests/test_canonical_gaps.py`, `tests/test_legacy_booking_safety.py` |
| F15 | Recovery approval | `services/skills/recovery_plan.py`, `routers/v1/trip.py` | `tests/test_canonical_gaps.py` |
| F16 | Full itinerary | `services/skills/itinerary.py`, `routers/v1/trip.py` | `tests/test_canonical_gaps.py` |
| F17 | Privacy | `models/schemas.py`, `services/profile_store.py`, `services/skills/guardian_push.py` | `tests/test_privacy.py`, `tests/test_provider_log_redaction.py` |
| F18 | Honest degraded operation | `services/llm.py`, `services/web_intel_client.py`, `services/atlas_client.py`, `services/rescue_engine.py` | `tests/test_e2e_trip_journey.py`, `tests/test_skills_behavior.py`, `tests/test_claims_provider_truth.py`, `tests/test_api_error_sanitization.py` |
| F19 | Accessibility | `static/styles.css`, `static/index.html`, `static/trip.js` | `tests/test_ui_trip.py` |
| F20 | Evidence integrity | `FINAL_REPORT.md`, `PLAN.md`, `DECISIONS.tsv`, `BLOCKERS.md` | `tests/test_docs_integrity.py` and the live verification commands below |

## Public Runtime Skills

The manifest loader in `services/skills/__init__.py` is the source of truth.
`clarify_loop` is validated as an internal orchestration helper and is not
advertised by `GET /api/skills`.

| ID | Skill | Declared capabilities |
|---|---|---|
| S1 | `goal_intake` | `llm_call` |
| S2 | `profile_capture` | `profile_write` |
| S3 | `profile_edit` | `profile_read`, `profile_write` |
| S4 | `flight_search` | `atlas_call`, `network_read` |
| S5 | `flight_book` | `atlas_call`, `approval_required` |
| S6 | `visa_check` | `network_read` |
| S7 | `web_intel` | `network_read` |
| S8 | `itinerary` | `llm_call` |
| S9 | `rights_check` | none; local rights tables only |
| S10 | `guardian_push` | `telegram_send` |
| S11 | `disruption_monitor` | `network_read` |
| S12 | `location_resolve` | `network_read`, `llm_call` |
| S13 | `recovery_plan` | `atlas_call`, `llm_call`, `approval_required` |

## Review Evidence Integrity

The preserved Antigravity transcript contains explicit no-defect outcomes for
the completeness reviewer and the correctness/security reviewer. It records
that the user-impact/evidence reviewer was still pending, but does not preserve
that reviewer's raw verdict. Later summaries are not substituted for the
missing primary evidence, so this repository makes no three-reviewer-clean
claim.

## Live Verification Commands

Run these commands from the repository root and report their fresh exit codes
and outputs in the handoff:

```bash
python -m pip check
TZ=UTC python -m pytest -p no:cacheprovider --collect-only -q
TZ=UTC python -m pytest -p no:cacheprovider -q
TZ=UTC python -m pytest -p no:cacheprovider tests/test_ui_trip.py -q
python -m pytest -p no:cacheprovider tests/test_legacy_booking_safety.py tests/test_claims_provider_truth.py tests/test_skills_manifest.py tests/test_privacy.py tests/test_canonical_gaps.py -q
TZ=UTC python tests/e2e_full_journey.py
node --check static/app.js
node --check static/trip.js
bash scripts/security_check.sh
git diff --check
```

Boot smoke uses `uvicorn main:app --host 127.0.0.1 --port 8050`, followed by
read-only health and skill-registry requests. Start and stop only the process
created for that smoke.

## Honest Limitations

- Live airline status, booking, LLM, web-research, and Telegram credentials are
  optional and are not proven by hermetic tests.
- Trip state and active watches are in-process; multi-instance persistence is
  outside the local single-user architecture.
- Authentication and multi-tenancy are not part of this local product.
- Optional scanners may be absent; `scripts/security_check.sh` reports the
  tools it actually runs and never relabels unavailable checks as passed.
