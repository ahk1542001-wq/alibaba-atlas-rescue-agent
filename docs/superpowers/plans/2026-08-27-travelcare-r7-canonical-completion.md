# TravelCare R7 Canonical Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the R6 test-shaped placeholders with the complete user-visible intake, planning, booking, itinerary, and disruption-recovery behavior required by the canonical product package.

**Architecture:** Keep the existing FastAPI, TripOrchestrator, TripGraphExecutor, and vanilla UI. Add durable pending-confirmation state to each in-process trip, serialize idempotent approval resolution by trip/approval/key, route both initial and recovery booking through complete immutable option snapshots, and derive itinerary validation and summaries from typed data rather than report claims.

**Tech Stack:** Python, FastAPI, Pydantic v2, asyncio, vanilla JavaScript/CSS, pytest, httpx ASGITransport, Playwright.

**Spec:** `docs/MASTER_BUILD_PACKAGE.md`

## Global Constraints

- Preserve the current `feature/trip-agent` history; use additive corrective commits only.
- No production booking, payment, real traveler data, push, deploy, or publication.
- Every booking is Atlas Sandbox or hermetic simulation and visibly labeled.
- Passport country is allowed; passport number, legal identity, and payment data remain forbidden.
- Initial and recovery approvals use distinct purpose-bound records and distinct idempotency keys.
- Existing v1 routes remain compatible while plural v2 routes gain their canonical behavior.
- Tests must exercise real route/orchestrator behavior; no conditional assertions and no injected fake confirmation state.

---

### Task 1: Honest plural intake and confirmation lifecycle

**Files:**
- Modify: `models/schemas.py`
- Modify: `services/trip_graph.py`
- Modify: `services/skills/goal_intake.py`
- Modify: `routers/v1/trip.py`
- Test: `tests/test_canonical_gaps.py`
- Test: `tests/test_skills_behavior.py`

**Interfaces:**
- Consumes: `TripGoal`, `ConfirmationChip`, `TripOrchestrator.answer_clarify`, `ProfileStore.set_field`.
- Produces: `Trip.confirmation_chips`, real `missing_fields`, pending chips from plural clarification, one-time confirm/reject/correct application, and refreshed trip state.

- [ ] **Step 1: Replace weak tests with failing behavior tests**

```python
assert start_body["missing_fields"] == ["origin_city", "passport_country", "home_city"]
assert clarification_body["confirmation_chips"]
assert profile_before["passport_country"] is None
assert confirm_body["status"] == "confirmed"
assert profile_after["passport_country"]["value"] == "MM"
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_canonical_gaps.py -q`

Expected: failures show empty missing fields, absent chips, or confirmation state not applied.

- [ ] **Step 3: Implement pending-confirmation state and goal/profile application**

```python
class Trip:
    self.confirmation_chips: Dict[str, ConfirmationChip] = {}

def pending_missing_fields(trip) -> list[str]:
    return [q["field"] for q in trip.context["clarify_loop"]["questions"]]
```

Plural clarification creates chips without changing the goal or profile. Confirmation validates trip ownership and allowed values, applies exactly once, synchronizes the intake seed, and returns the next pending fields/chips.

- [ ] **Step 4: Verify GREEN and preserve v1 compatibility**

Run: `pytest tests/test_canonical_gaps.py tests/test_e2e_trip_journey.py -q`

- [ ] **Step 5: Commit exact files**

```bash
git add models/schemas.py services/trip_graph.py services/skills/goal_intake.py routers/v1/trip.py tests/test_canonical_gaps.py tests/test_skills_behavior.py tests/test_e2e_trip_journey.py
git commit -m "fix(api): implement real trip confirmations"
```

### Task 2: Complete itinerary and replace-one-section behavior

**Files:**
- Modify: `models/schemas.py`
- Modify: `services/skills/itinerary.py`
- Modify: `routers/v1/trip.py`
- Test: `tests/test_canonical_gaps.py`
- Test: `tests/test_skills_behavior.py`

**Interfaces:**
- Consumes: confirmed booking, goal date window, profile budget, provider items.
- Produces: itinerary items with stable ids, timezone, schedule validation, budget ranges by category and total, and typed replacement results.

- [ ] **Step 1: Add failing tests for timezone, budget, overlap, and preservation**

```python
assert result["timezone"] == "Asia/Singapore"
assert result["budget"]["total_range_sgd"] == [120, 180]
assert result["validation"]["overlaps"] == []
assert replaced["items"][0] == original[0]
assert replaced["items"][2] == original[2]
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_canonical_gaps.py -q`

- [ ] **Step 3: Implement deterministic summary and typed replacement**

Parse ISO timestamps before overlap comparison, preserve the target item id, reject booked flight replacement, keep unrelated objects semantically unchanged, recompute validation and budget, and return provenance for the replacement.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_canonical_gaps.py tests/test_skills_behavior.py -q`

- [ ] **Step 5: Commit exact files**

```bash
git add models/schemas.py services/skills/itinerary.py routers/v1/trip.py tests/test_canonical_gaps.py tests/test_skills_behavior.py
git commit -m "feat(itinerary): add complete replaceable trip summary"
```

### Task 3: Atomic booking idempotency and immutable initial approval

**Files:**
- Modify: `services/trip_graph.py`
- Modify: `services/skills/flight_book.py`
- Modify: `routers/v1/trip.py`
- Modify: `static/trip.js`
- Test: `tests/test_canonical_gaps.py`
- Test: `tests/test_e2e_trip_journey.py`

**Interfaces:**
- Consumes: approval id, selected option id, canonical request payload, Idempotency-Key.
- Produces: one stored receipt per key/payload, identical replay, HTTP 409 conflict for changed payload, and no duplicate provider call under concurrency.

- [ ] **Step 1: Write failing tests for the real `approve_booking` gate**

```python
assert missing_key.status_code == 422
first, replay = await asyncio.gather(resolve(key), resolve(key))
assert first == replay
assert atlas.create_count == 1
assert changed_payload.status_code == 409
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_canonical_gaps.py -q`

- [ ] **Step 3: Add purpose-bound approval metadata and serialized ledger resolution**

Initial graph approvals carry `purpose="initial_booking"`, an expiry, and immutable option snapshots. `TripOrchestrator.resolve` acquires an asyncio lock keyed by trip, approval, and idempotency key before ledger lookup, provider execution, and receipt storage.

- [ ] **Step 4: Keep the same browser key across retry attempts**

Store one generated key per approval id in the UI state; do not generate a new key after a timeout or recoverable error.

- [ ] **Step 5: Verify GREEN and mutation cases**

Run: `pytest tests/test_canonical_gaps.py tests/test_e2e_trip_journey.py tests/test_ui_trip.py -q`

- [ ] **Step 6: Commit exact files**

```bash
git add services/trip_graph.py services/skills/flight_book.py routers/v1/trip.py static/trip.js tests/test_canonical_gaps.py tests/test_e2e_trip_journey.py tests/test_ui_trip.py
git commit -m "fix(booking): make approvals retry safe"
```

### Task 4: Complete recovery booking, receipts, safety, rights, and itinerary update

**Files:**
- Modify: `services/skills/recovery_plan.py`
- Modify: `routers/v1/trip.py`
- Modify: `static/trip.js`
- Test: `tests/test_canonical_gaps.py`
- Test: `tests/test_e2e_trip_journey.py`
- Test: `tests/test_ui_trip.py`

**Interfaces:**
- Consumes: original BookingRecord, disruption event, verified recovery option, recovery approval key.
- Produces: purpose-bound recovery approval, complete replacement BookingRecord, preserved original receipt, updated itinerary, monitor state, and rights opinion.

- [ ] **Step 1: Write a failing full recovery journey**

```python
assert recovery_approval["purpose"] == "recovery_booking"
assert recovery_approval["immutable_option"]
assert replacement["booking"]["option"]["id"] == selected_recovery_id
assert original_receipt["pnr"] != replacement["pnr"]
assert state["outputs"]["rights"]["regime"] == "NONE"
assert atlas.recovery_create_count == 1
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_canonical_gaps.py -q`

- [ ] **Step 3: Implement recovery through the same governed skills**

Run the booking safety precheck again, pass the complete selected option to FlightBookSkill, preserve both receipts, update only the affected flight section, arm monitoring for the replacement, and run RightsCheckSkill from actual airport facts.

- [ ] **Step 4: Surface both receipts and rights in state/UI**

Render original and replacement Sandbox references separately and keep the original itinerary entry visibly cancelled/replaced.

- [ ] **Step 5: Verify GREEN**

Run: `pytest tests/test_canonical_gaps.py tests/test_e2e_trip_journey.py tests/test_ui_trip.py -q`

- [ ] **Step 6: Commit exact files**

```bash
git add services/skills/recovery_plan.py routers/v1/trip.py static/trip.js tests/test_canonical_gaps.py tests/test_e2e_trip_journey.py tests/test_ui_trip.py
git commit -m "feat(recovery): preserve complete replacement evidence"
```

### Task 5: Beginner-friendly replacement UI and rendered verification

**Files:**
- Modify: `static/trip.js`
- Modify: `static/styles.css`
- Test: `tests/test_ui_trip.py`

**Interfaces:**
- Consumes: itinerary items and the replace-section route.
- Produces: an inline Replace control for non-booked sections, Save/Cancel actions, live feedback, updated budget/timezone summary, and no replace control on booked flights.

- [ ] **Step 1: Write failing Playwright interaction tests**

The target flow is: confirmed itinerary → choose a non-booked section → open inline replacement editor → save → updated section and summary render without console errors.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_ui_trip.py -q`

- [ ] **Step 3: Implement safe-DOM replacement controls**

Use only `createElement`, `textContent`, and typed JSON requests. Keep the inline editor compact, keyboard reachable, and labeled; never use `prompt`, HTML injection, or a fake success path.

- [ ] **Step 4: Verify GREEN at desktop and mobile**

Run the focused UI test, then the whole UI suite. Capture temporary screenshots outside the repository for review.

- [ ] **Step 5: Commit exact files**

```bash
git add static/trip.js static/styles.css tests/test_ui_trip.py
git commit -m "feat(ui): make itinerary sections safely replaceable"
```

### Task 6: Evidence correction and final gate

**Files:**
- Modify: `FINAL_REPORT.md`
- Modify: `PLAN.md`

**Interfaces:**
- Consumes: fresh verification outputs from the final committed tree.
- Produces: durable requirement mappings without false claims, stale counts, or machine-local proof paths.

- [ ] **Step 1: Remove contradictory or unsupported R6 claims**

Correct the F1, F14, F15, and F16 mappings; remove the stale split between previous and current suite totals; do not claim screenshots or browser files that do not exist.

- [ ] **Step 2: Run the complete fresh verification runbook**

Run dependency check, full non-live suite, legacy canary, v2 API/browser recovery journey, security script, JavaScript syntax check, and whitespace check. Boot locally and probe health and skills.

- [ ] **Step 3: Inspect every requirement against runtime evidence**

Confirm F1–F20 and S1–S13 individually. Any remaining unsupported row is marked as a limitation instead of PASS.

- [ ] **Step 4: Commit exact evidence files**

```bash
git add FINAL_REPORT.md PLAN.md
git commit -m "docs(report): reconcile R7 verification evidence"
```

- [ ] **Step 5: Fast-forward the owner branch without push**

After the isolated branch is clean and verified, fast-forward `feature/trip-agent` to the R7 head. Do not push or deploy.
