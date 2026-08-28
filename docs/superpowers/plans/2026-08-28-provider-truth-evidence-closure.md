# Provider Truth and Evidence Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make unknown flight status fail closed without inventing a route or disruption, and keep the durable proof index aligned with runtime skill metadata and preserved review evidence.

**Architecture:** The Atlas sandbox status catalog remains the only source of demo disruption facts. An unknown flight returns an explicit unavailable result with no route fields, so monitoring stays non-disruptive and claims cannot derive rights from invented airports. The final report becomes a durable proof index; live command results belong in the execution handoff.

**Tech Stack:** Python, FastAPI, pytest, Playwright, JavaScript syntax checks, shell security gate.

**Spec:** `docs/MASTER_BUILD_PACKAGE.md`

## Global Constraints

- Preserve sandbox/mock labeling and never present a fixture as live provider data.
- Keep client-supplied airport hints non-authoritative for claim assessment.
- Do not push, deploy, publish, contact live providers, send Telegram, or use real traveler data.
- Do not modify `AGENTS.md`, `.env` contents, rights tables, or visa baseline tables.
- Keep tracked documentation durable; live counts and host-local paths stay in the handoff, not the repository.
- Hermetic verification must not mutate tracked evidence when a live provider is unavailable.

## Pre-Change Context Packet

1. **Objective:** prevent unknown status lookups from fabricating BKK to RGN cancellations and correct stale or unsupported evidence claims.
2. **Files in scope:** Atlas status, rescue, profile-store, Guardian, legacy API
   routers, their focused tests, `FINAL_REPORT.md`, `PLAN.md`, and
   `DECISIONS.tsv`.
3. **Entry points touched:** status lookup, claim/disruption/search/concierge
   APIs, profile deletion, Guardian delivery, and provider logging.
4. **Upstream callers:** claim assessment, rescue radar scans, disruption
   recovery, profile edit, Guardian skill, and public legacy routes.
5. **Downstream callees:** jurisdiction detection, distance calculation,
   recovery search, alert classification, profile compatibility views, and
   configured external providers.
6. **Settings impact:** `USE_MOCK_FALLBACK` continues to govern search fallback; no setting is added.
7. **Persisted-state impact:** none.
8. **Boundary check:** local sandbox code, tests, and docs only; no external approval-gated action is required.
9. **Verification plan:** focused regression, claims suite, radar-safe behavior, full pytest, browser suite, legacy canary, JavaScript syntax, security gate, dependency check, boot smoke, and git hygiene.
10. **Rollback plan:** revert the local closure commit; no remote or external state is changed.
11. **Open assumptions:** fixture flight numbers in the curated status catalog are valid sandbox scenarios; any other number is unavailable, not cancelled.

## Required Search Record

- Definition/callers/importers: status lookup is defined in `services/atlas_client.py` and consumed by claims, radar, and rescue-engine paths.
- API surface: `POST /api/claims/assess` is the affected public route; disruption analysis consumes the same service internally.
- Existing tests: provider spoofing, missing-route, and sanitized-error tests exist in `tests/test_claims_provider_truth.py`; no unknown real-client regression existed.
- Settings: the client reads `USE_MOCK_FALLBACK`; the status catalog itself has no live-provider branch.
- Documentation: the report and remediation plan call the claims route provider-derived truth.
- Nearby markers: no TODO or FIXME marker governs the fallback.

---

### Task 1: Fail Closed for Unknown Flight Status

**Files:**
- Modify: `tests/test_claims_provider_truth.py`
- Modify: `services/atlas_client.py`

**Interfaces:**
- Consumes: `AtlasClient.get_flight_status(flight_number: str, date: str) -> dict`.
- Produces: known fixture status dictionaries unchanged; unknown flights return `status="UNKNOWN"`, an unavailable reason, and no `origin` or `destination`.

- [x] **Step 1: Write the failing service regression**

Add a test using the real `AtlasClient` that requests `ZZ999` and asserts `status == "UNKNOWN"`, `origin` and `destination` are absent, and no compensation value is present.

- [x] **Step 2: Write the failing route regression**

Post `ZZ999` with spoofed client airport hints and assert HTTP 422 with no client airport reflected in the response.

- [x] **Step 3: Verify RED**

Run: `python -m pytest -p no:cacheprovider tests/test_claims_provider_truth.py -q`

Expected: the new assertions fail because the existing fallback invents a cancelled BKK to RGN itinerary.

- [x] **Step 4: Implement the minimal status fallback**

Replace the fabricated default dictionary with a minimal unavailable dictionary containing only the normalized flight number, airline code, `status="UNKNOWN"`, and an honest unavailable reason.

- [x] **Step 5: Verify GREEN**

Run: `python -m pytest -p no:cacheprovider tests/test_claims_provider_truth.py -q`

Expected: all focused claim tests pass.

### Task 2: Reconcile Durable Evidence

**Files:**
- Modify: `FINAL_REPORT.md`
- Modify: `PLAN.md`
- Modify: `DECISIONS.tsv`

**Interfaces:**
- Consumes: runtime manifest registry, actual status behavior, committed review transcript evidence, and current repository topology.
- Produces: a durable F1-F20/S1-S13 proof index and an explicit decision that unknown status is unavailable.

- [x] **Step 1: Correct the skills matrix**

Read `load_skill_registry()` output and copy the exact declared tools: flight search includes `atlas_call` plus `network_read`; visa check includes only `network_read`; itinerary includes only `llm_call`.

- [x] **Step 2: Remove unsupported reviewer claims**

State only the reviewer verdicts preserved in raw handoff evidence. Do not infer a missing verdict from a later summary.

- [x] **Step 3: Remove stale integration and machine-local evidence**

Describe the architecture and commands durably. Do not freeze branch readiness, host-local virtual-environment paths, timings, or test counts in tracked documentation.

- [x] **Step 4: Record the design decision**

Append a `DECISIONS.tsv` row establishing that unknown flight statuses expose no route, disruption, or compensation facts.

- [x] **Step 5: Reconcile the plan authority**

Append the correction and supersede the false three-reviewer and unknown-route completion claims.

### Task 2A: Close Downstream Truth and Error-Leak Paths

**Files:**
- Modify: `services/rescue_engine.py`, `services/profile_store.py`,
  `services/guardian.py`, `services/llm.py`, `services/radar.py`
- Modify: `routers/v1/flights.py`, `routers/v1/concierge.py`,
  `routers/v1/disruptions.py`
- Test: `tests/test_skills_behavior.py`, `tests/test_rights_and_visa.py`,
  `tests/test_api_error_sanitization.py`, `tests/test_provider_log_redaction.py`,
  `tests/test_e2e_trip_journey.py`

**Interfaces:**
- Consumes: unavailable status dictionaries, safe profile-field names,
  Guardian payloads, provider exceptions, and public API requests.
- Produces: no recovery plan for an unknown flight, complete deletion across
  profile compatibility views, non-blocking plain-text Guardian delivery, and
  generic API/log errors without raw provider content.

- [x] **Step 1: Reproduce each defect with an observable behavior test**
- [x] **Step 2: Verify every new test fails for the intended reason**
- [x] **Step 3: Apply the smallest source fix at the data-origin boundary**
- [x] **Step 4: Rerun each focused test to verify GREEN**
- [x] **Step 5: Include every path in the complete verification sequence**

### Task 3: Fresh Verification and Local Checkpoint

**Files:**
- Verify all modified files and the complete repository.

**Interfaces:**
- Consumes: final local tree.
- Produces: owner-facing live evidence; no remote side effect.

- [x] **Step 1: Run focused and full Python suites**
- [x] **Step 2: Run browser UI and legacy canary**
- [x] **Step 3: Run JavaScript, dependency, security, and boot gates**
- [x] **Step 4: Inspect diff, status, and changed-file scope**
- [x] **Step 5: Commit exact local paths only after every required gate passes**
