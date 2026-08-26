# TravelCare AI v2 — Execution Plan (G0→G8)

Authoritative spec: `docs/MASTER_BUILD_PACKAGE.md` (package defines G0–G6;
this plan extends with G7 = §12 mock-data pass and G8 = §16.3
completion/smoke/stop). Rules of engagement from spec §0 apply to every gate.

## Gate Sequence

| Gate | Name | Scope | Entry condition |
|---|---|---|---|
| G0 | Plan Gate | `PLAN.md`, `DECISIONS.tsv` skeleton, `BLOCKERS.md` skeleton | branch `feature/trip-agent` checked out, clean tree |
| G1 | Contracts Gate | §5 pydantic contracts, skill scaffolding (§4.0), profile store contract, web-intel skeleton, KG seed, deps | G0 artifacts committed |
| G2 | Core Gate | TripGraph executor, ProfileStore behavior, ClarifyLoop, WebIntel skills pass unit tests | G1 contracts compile; collect clean |
| G3 | Integration Gate | generic journey runs locally without personal data (goal→flights→visa→options→approval→book→monitor) | G2 units green |
| G4 | UI Gate | Playwright headless suites across every screen (happy + edge paths); screenshots saved | G3 journey green |
| G5 | Security & Audit Gate | secrets scan, dependency audit, XSS/injection/input validation, profile privacy checks | G4 browser suites green |
| G6 | Cleanup & Report Gate | dead code removed, CI repaired to run the `tests/` suite, self-report written (spec §9.7) | G5 audit clean |
| G7 | Mock-Data Pass | load `data/mock_victor.json` once owner fills placeholders; re-run `[mockdata]`-tagged E2E + browser suites; graceful skip + honest limitation while owner absent | G6 green, fixture filled |
| G8 | Completion & Stop | §16.3 definition of done: evidence complete, F1–F12 table filled, `FINAL_REPORT.md` written, fresh boot passes smoke | G7 resolved (or honestly deferred) |

## Per-Gate Evidence Checklist

### G0 Plan Gate
- [x] `PLAN.md` committed with gate order and evidence checklist
- [x] `DECISIONS.tsv` seeded with AUTO- decisions (header: timestamp/area/decision/reason)
- [x] `BLOCKERS.md` skeleton present
- Evidence: `git log` shows gate commit; files exist on disk.

### G1 Contracts Gate
- [ ] §5 models appended to `models/schemas.py` without touching existing models
- [ ] `mask_passport` util proven by test vectors
- [ ] `services/profile_store.py` contract: atomic write, chmod 0o600, source tags, consent gating, masked display
- [ ] `services/skills/base.py` + boot-time manifest loader (closed capability vocabulary enforced)
- [ ] 11 skill pairs (`<name>.py` + `<name>.SKILL.md`), registry lists exactly 11
- [ ] `services/web_intel_client.py` skeleton + `services/kg_seed.json`
- [ ] deps installed; `.venv/bin/python -m pytest --collect-only -q` clean; full suite green
- Evidence: pytest output, `git diff --name-only` excludes frozen files.

### G2 Core Gate
- [x] TripGraph executor with NodeSpec/conditional edges/ApprovalGate pause-resume (`services/trip_graph.py`)
- [x] GraphNodeStateV2 appended on every node execution (POST_NODE_RECORD unconditional)
- [x] CONDITIONAL MOUNTING by `TripIntent.requested_services`; visa safety dep always mounted for international bookings; scope clarification = exactly 3 choices
- [x] GATE_PAUSE: per-trip lock, single winner on concurrent approvals, rejection terminates
- [x] ON_DISRUPTION_EVENT mounts frozen `DisruptionRecoveryDAG` (import-only) <2s
- [x] Deterministic replay proven via `mask_volatile(trace)`; cross-trip isolation proven
- [x] All 11 skill behaviors implemented + unit suites green (goal_intake 11 golden phrasings, clarify_loop, profile_capture silent-save-impossible, flight_search, flight_book idempotency+reverify+visa-block, visa_check baseline ≤50ms + freshness states, web_intel cache counted, itinerary provider chain with honesty chips, rights_check honest NONE, guardian_push skipped_not_failed + passport excluded, disruption_monitor)
- [x] Bounded `ResearchCoordinator` (owner correction C): domains from RequestedServices, provenance/freshness on every result, fares refreshed+reverified before booking
- [x] G1 DA-review defects fixed regression-test-first (see DECISIONS.tsv rows; this gate commit carries the fixes)
- Evidence: full-suite pytest output below; `git diff --name-only` excludes frozen files.

```
$ .venv/bin/python -m pytest tests/ -q
........................................................................ [ 49%]
........................................................................ [ 99%]
.                                                                        [100%]
145 passed in 0.49s
```

Suite composition: pre-existing 31 (docs integrity, rights/visa, legacy E2E
canary) + G1 contracts 31 + G2 new 83 (trip_graph, skills behavior, web-intel,
and G1-defect regression vectors folded into test_profile_store /
test_skills_manifest).

### G3 Integration Gate
- [x] generic journey runs over the §6 HTTP API: start→clarify(stub LLM)→search(live sandbox)→visa(baseline+fresh citations)→approve→book→monitor arm (`tests/test_e2e_trip_journey.py::test_happy_full_trip_no_personal_data_live_sandbox`)
- [x] E2E happy path + visa-block reroute + disruption path + stale-visa refusal + ambiguous-scope 3-choice pause + flight-only scoping
- [x] trip/profile/skills routers registered in `main.py` under the shared §6 error contract `{error:{code,message,recoverable,hint}}`
- [x] adversarial mappings: unknown trip/approval → 404, already_resolved → 409, approval_expired → 410 recoverable; concurrent approvals → single winner; provider failures degrade, never fabricate
- [x] `data/mock_hotels_sg.json` verified (valid JSON, 22 hotels + 12 activities, sourced entries) and committed with the gate
- Evidence: G3 gate commit pytest output below; PNR-shaped object provenance-flagged sandbox; live Atlas CLI offers asserted non-canned.

### G4 UI Gate
- [x] Playwright flows B1–B6 green; `data-testid` on interactive elements
- [x] screenshots saved to `screenshots/` (gitignored)
- [x] UI completeness sweep: every interactive element asserted or listed out-of-demo-scope
- Evidence: PNGs + browser console capture with zero errors.

### G5 Security & Audit Gate
- [ ] gitleaks pre-commit hook; banned-pattern grep over tracked tree returns zero
- [ ] dependency advisory scan of new deps
- [ ] XSS check (textContent/createElement only), pydantic boundary validation, profile chmod verified
- Evidence: `scripts/security_check.sh` output.

### G6 Cleanup & Report Gate
- [ ] dead/experimental code deleted; `git status` shows intentional files only
- [ ] CI workflow repaired to run the `tests/` suite
- Evidence: CI run log; clean status output.

### G7 Mock-Data Pass
- [ ] `data/mock_victor.json` real values supplied by owner; `[mockdata]` suites re-run
- [ ] if owner absent: graceful skip recorded with honest limitation in `FINAL_REPORT.md`
- Evidence: tagged suite results attached to report.

### G8 Completion & Stop
- [ ] §16.3 done: F1–F12 table filled, `FINAL_REPORT.md` written, fresh-boot smoke green
- Evidence: smoke output + 15-line summary; then STOP per §16.3.

## Decision Log

Single source of truth: `DECISIONS.tsv` (tab-separated:
`timestamp  area  decision  reason`). One row per non-trivial decision;
unattended decisions carry the `AUTO-` prefix per spec §16. Review the file
before each gate entry.

## Resume From Last Green Gate

Every gate ends with a local commit on `feature/trip-agent` using message
`gate(G#): <summary>` (spec §0 rule 0). An interrupted run resumes as follows:

1. Run `git log --oneline` and locate the most recent `gate(G#)` commit.
2. Confirm `git status` is clean of uncommitted gate work; if work-in-progress
   exists, run that gate's evidence checklist to decide pass/fail before moving on.
3. Run `.venv/bin/python -m pytest tests/ -q` to re-prove the suite for the
   last green gate.
4. Continue with the next gate in the sequence table above. Never re-run a
   green gate from scratch; never rewrite history.

## Doc Hygiene

Tracked docs carry durable facts only: no machine-specific absolute paths and
no volatile counts (conventions enforced by the docs-integrity tripwires).
Verify live state instead of freezing numbers here.

## Traceability (requirement → implementation → test → evidence)

Fresh evidence is captured per gate commit; pointers below stay durable.

| Requirement | Implementation | Automated test | Evidence |
|---|---|---|---|
| §5 v2 data contracts | `models/schemas.py` (append-only block) | `tests/test_profile_store.py` (schema contract cases) | gate commit pytest output |
| §5 mask_passport util | `models/schemas.py` | `tests/test_profile_store.py` mask vectors (std/short/empty) | gate commit pytest output |
| §5/F5 profile store (atomic write, 0o600, source tags, consent, delete-clears-field) | `services/profile_store.py` | `tests/test_profile_store.py` | gate commit pytest output |
| §4.0 SkillBase + closed capability vocabulary | `services/skills/base.py` | `tests/test_skills_manifest.py` vocabulary cases | gate commit pytest output |
| §4.0/F12 boot-time manifest loader | `services/skills/__init__.py` | `tests/test_skills_manifest.py` (count, add/remove, malformed frontmatter, unknown flags, reload) | gate commit pytest output |
| §4 11 skill pairs | `services/skills/<name>.py` + `<name>.SKILL.md` | `tests/test_skills_manifest.py` registry cases | gate commit pytest output |
| §4 S7 / §14.4 web-intel skeleton | `services/web_intel_client.py` | `tests/test_web_intel.py` (cache counted, TTL expiry, offline degrade, tolerant parse) | G2 gate commit pytest output |
| §5/§7 KG seed | `services/kg_seed.json` | `tests/test_skills_behavior.py` visa baseline cases | G2 gate commit pytest output |
| §3.1/§14.2 generic TripGraph executor | `services/trip_graph.py` | `tests/test_trip_graph.py` | G2 gate commit pytest output |
| §4 S1–S11 skill behaviors (owner corrections A/B/C) | `services/skills/*.py` | `tests/test_skills_behavior.py` | G2 gate commit pytest output |
| §15.2 itinerary provider chain + honesty chips | `services/skills/itinerary.py` | `tests/test_skills_behavior.py` S8 cases | G2 gate commit pytest output |
| Owner correction (C) bounded research | `services/research_coordinator.py` | `tests/test_skills_behavior.py` coordinator cases | G2 gate commit pytest output |
| G1 DA-review defect regressions (masking bypass, short-passport leak, loader pairing, dup names, user_id traversal, capability drift, YAML list tools) | `services/profile_store.py`, `models/schemas.py`, `services/skills/__init__.py` | `tests/test_profile_store.py`, `tests/test_skills_manifest.py` | G2 gate commit pytest output |
| G2 DA-review remediation (per-trip idempotency after gates, citation date honesty, run() status guards, fail-closed capabilities, unknown-passport + BLOCKED_RISK booking refusal, list-aware sanitization, per-trip disruption watches, internal-error FAILED records, real-timestamp freshness, approval expiry, §3.1 blocked-route replan edge) | `services/skills/flight_book.py`, `services/web_intel_client.py`, `services/trip_graph.py`, `services/skills/visa_check.py`, `services/skills/guardian_push.py`, `services/skills/disruption_monitor.py`, `models/schemas.py` (ApprovalRequest only) | `tests/test_trip_graph.py`, `tests/test_skills_behavior.py`, `tests/test_web_intel.py` G2-DA sections | G2-DA remediation pytest output below |
| §12 demo fixture placeholder | `data/mock_victor.json` (gitignored) | `[mockdata]`-tagged suites at G7; graceful skip while owner absent | G7 report section |
| §6 trip API (start/state/stream/approvals/simulate-disruption) + orchestration glue | `routers/v1/trip.py` | `tests/test_e2e_trip_journey.py` (happy, flight-only, scope pause, visa-block reroute, stale-visa refusal, disruption, adversarial ids, concurrency, provider failure) | G3 gate commit pytest output |
| §6 profile API (masked GET, source-enforced PUT, DELETE, consent) | `routers/v1/profile.py` | `tests/test_e2e_trip_journey.py::test_profile_api_contract_masks_and_enforces_source` | G3 gate commit pytest output |
| §6/F12 skills manifest API | `routers/v1/skills.py` | `tests/test_e2e_trip_journey.py::test_skills_manifest_listing` | G3 gate commit pytest output |
| §6 shared error contract handlers (TripApiError / GraphError) | `main.py` (registration + 2 handlers only) | `tests/test_e2e_trip_journey.py` error-shape assertions | G3 gate commit pytest output |
| §15.1 researched Singapore hotels/activities dataset | `data/mock_hotels_sg.json` | `tests/test_skills_behavior.py` S8 itinerary cases + G3 verification (valid JSON, 22 hotels + 12 activities, sourced entries) | G3 gate commit |
| §5 trip UI (goal chat, clarify chips, 3-choice scope, sandbox option cards, approval modal, PNR screen, honesty itinerary, live DAG, profile editor, two-run greeting) | `static/index.html` (#view-trip, additive), `static/trip.js` (new; strict createElement/textContent), `static/styles.css` (append-only) | `tests/test_ui_trip.py` B1–B6 + scope/flight-only/degraded+stale/XSS/mobile 375px/console-error-zero suites | G4 gate commit pytest output + `screenshots/*.png` |
| §9.2 data-testid on every interactive element | `static/index.html` backfill (existing ids/classes untouched) | `tests/test_ui_trip.py::test_ui_completeness_sweep_testids` + per-flow clicks | G4 sweep table below |
| Legacy rescue UI unbroken by the additive trip view | frozen `static/app.js` untouched | canary `tests/e2e_full_journey.py` against booted app: 14/14 PASS | G4 canary run log |
| §0/§9.7 gate process artifacts | `PLAN.md`, `DECISIONS.tsv`, `BLOCKERS.md` | `tests/test_docs_integrity.py` conventions (durable-docs hygiene) | gate commit pytest output |

## G2 Devil's Advocate Remediation (against gate commit 2a3715a)

All 10 DA findings were reproduced first with probe scripts, then fixed
TDD-style: failing regression test added per finding, root cause fixed,
test green. Leader addendum (BLOCKED_RISK routes refuse booking with no
override + §3.1 replan edge) implemented alongside. Decisions logged in
`DECISIONS.tsv` under prefix `G2-DA-fix` (+ two `AUTO-` collateral rows).

Remediation evidence (`.venv/bin/python -m pytest tests/ -q`):

```
before (gate commit 2a3715a):  145 passed in 0.49s
red phase (27 new regressions): 27 failed, 75 passed  (in the 3 touched files)
after fixes:                    173 passed in 0.43s
```

## G3 Integration Gate (trip/profile/skills APIs)

Scope (per leader directive): routers/, main.py registration,
`tests/test_e2e_trip_journey.py`, and committing `data/mock_hotels_sg.json`.
Frozen/G2 services are imported, never edited; the orchestrator is built
against the post-remediation executor contract (462fab1).

Delivered:

- `routers/v1/trip.py` — §6 trip endpoints + orchestration glue
  (stage-1 goal_intake/clarify_loop run skill-direct and recorded into the
  trace; the stripped `plan_trip` node list mounts as the graph; ambiguous
  scope pauses with exactly three choices before any irreversible work;
  defensive GraphError mapping by `code`; `_run_guarded` degrades provider
  failures into recorded recoverable FAILED states).
- `routers/v1/profile.py` — masked GET, PUT with `source` ENFORCED to "user"
  server-side, DELETE field, consent gate.
- `routers/v1/skills.py` — live manifest listing from the boot registry.
- `main.py` — registers the three routers and the shared §6 error contract
  handlers (`TripApiError`, `GraphError`); existing routes/lifespan untouched.
- `data/mock_hotels_sg.json` — verified valid JSON: 22 hotels + 12
  activities, every item carries name/type/price_range_sgd/source_url/
  researched_as_of/researched:true (7 activities carry explicit
  `price_range_sgd: null` — the sources gave no price; omitted honestly per
  §15.1, see BLOCKERS.md).
- `tests/test_e2e_trip_journey.py` — 15 E2E tests: happy full trip on the
  LIVE Atlas sandbox (provenance asserted non-canned; unreachable-sandbox
  fallback records BLOCKERS.md honestly instead of faking), flight-only
  scoping, ambiguous 3-choice pause, visa-block reroute (block surfaced,
  reroute visible, booking structurally impossible — no override),
  stale/offline visa refusal (recoverable), disruption simulation
  (?allow_sim=1, trip_id validated), visa baseline ≤50ms, adversarial
  ids (404/409/410-recoverable), concurrent single-winner approvals,
  provider-failure degrade, profile privacy contract, skills manifest.

Gate evidence (`.venv/bin/python -m pytest tests/ -q`):

```
before (remediation commit 462fab1): 173 passed in 0.47s
new E2E suite alone:                 15 passed in 31.21s
after (full suite):                  188 passed in 31.71s
```

Live-sandbox note: the atlas-flight CLI probe returned real offers for
BKK→SIN at gate time; happy-path option ids were asserted disjoint from the
curated fallback set.

## G3 Devil's Advocate Remediation (against gate commit a8bb94a)

All 7 DA findings were reproduced first (probe scripts + red regression
tests), then fixed TDD-style: failing regression test added per finding in
`tests/test_e2e_trip_journey.py`, root cause fixed, test green. Scope
isolation held: `static/`, `tests/test_ui_trip.py` and every `services/`
module untouched; fixes live in `routers/v1/profile.py`, `routers/v1/trip.py`
and `main.py` only (no schema change needed — `TripStartRequest` already
lives in `routers/v1/trip.py`). Decisions logged in `DECISIONS.tsv` under
prefix `G3-DA-fix` (+ `AUTO-` rows).

Per-finding status:

1. HIGH profile PUT validation bypass — REPRODUCED (cabin=123 and
   expiry='not-a-date' persisted 200; a fresh `ProfileStore` then failed
   `model_validate_json`) → FIXED: validate-before-assignment via model
   reconstruction (prefs + identity, with normalization) → 400
   `invalid_profile_request`. Deviation vs the claim: the reload failure was
   already trapped by the `ValueError` catch (ValidationError subclasses
   ValueError), so it surfaced as a mislabeled `invalid_user_id` with raw
   pydantic detail rather than a bare 500; `_guard_user_id` now catches
   `ValidationError` explicitly → 400 `profile_unreadable` recoverable.
2. HIGH passport_no non-string — REPRODUCED (TypeError in `mask_passport` →
   bare 500) → FIXED: boundary type guard on all identity-shaped fields →
   400 envelope.
3. MED blanket ValueError in trip_start — REPRODUCED ('fly BKK to Singapore
   Sep 31' → code `invalid_user_id` with errors.pydantic.dev URLs) → FIXED:
   explicit user_id regex check first; goal-construction `ValidationError` →
   422 `invalid_goal`, sanitized.
4. MED malformed bodies — REPRODUCED (FastAPI `{"detail":[...]}`) → FIXED:
   `RequestValidationError` handler in `main.py` scoped by path prefix
   (/api/trip, /api/profile, /api/skills) → `invalid_request` envelope;
   legacy routes keep the default shape (pinned by regression).
5. MED manifest governance dead in production — REPRODUCED (executor built
   with allow_unmanifested_skills=True; stage-1 ran skill-direct bypassing
   enforcement) → FIXED fail-closed: adapters registered as explicit
   capability-empty exemption entries (real *.SKILL.md manifests impossible
   without paired .py modules, which scope isolation forbids — see
   DECISIONS.tsv), boot assertion refuses unmanifested write-capable skills,
   stage-1 direct runs pass `_enforce_stage1_capabilities`.
6. LOW unbounded goal_text — REPRODUCED (5MB accepted) → FIXED:
   `max_length=4000` (+ user_id 128) → `invalid_request` envelope.
7. LOW endless SSE polling — REPRODUCED (stream still open >4s on a
   never-resolved approval, bounded probe killed) → FIXED: idle (90s) +
   lifetime (600s) caps emit a final `status` event (reason
   `stream_timeout`) and close; the trip stays paused.

Remediation evidence (`.venv/bin/python -m pytest tests/ -q`, TZ=UTC — the
pre-existing `test_s6_yesterday_date_only…` test is clock-dependent in
non-UTC locales because it compares local dates against a conservative UTC
start-of-day; under TZ=UTC it is deterministic):

```
before (gate commit a8bb94a):  188 passed in 31.01s (TZ=UTC)
red phase (9 new regressions): 8 failed instantly + 1 (SSE) hangs pre-fix,
                               confirmed via bounded 4s stream probe
after fixes:                   197 passed in 31.62s (incl. concurrent
                               agent's test_ui_trip.py: 207 passed in 51.78s)
```

No pre-existing test was weakened or deleted; frozen services and the
README demo flow untouched (`git diff --name-only` in the remediation commit
lists only routers/v1/profile.py, routers/v1/trip.py, main.py,
tests/test_e2e_trip_journey.py, DECISIONS.tsv, PLAN.md).

## G4 UI Gate (trip view with Playwright evidence)

Scope (per leader directive): additive `static/index.html` changes,
NEW `static/trip.js`, append-only `static/styles.css`,
`tests/test_ui_trip.py`. Frozen: `static/app.js`, `services/*`,
pre-existing tests, AGENTS.md, README demo-flow, .env — all untouched.

Delivered:

- `static/index.html` — fifth view `#view-trip` + nav entries (desktop
  sidebar + mobile bottom nav, existing patterns); goal chat, clarify-chip
  area, 3-choice scope block, visa panel, approval banner + modal, option
  cards with "Atlas Sandbox data" chip, PNR screen, honesty itinerary, live
  DAG rail, profile editor with consent toggle; `data-testid` backfilled on
  EVERY interactive element without changing any pre-existing id/class.
- `static/trip.js` — all trip-view logic; strict createElement/textContent
  (zero innerHTML with data); 1s `setInterval` polling of
  `GET /api/trip/{id}/state` + SSE `/api/trip/{id}/stream` (node/approval
  events trigger immediate polls; ES closed on terminal status); approve/
  reject flows; profile editor via `/api/profile/*` (source enforced user);
  provenance/freshness chips + visible degraded/stale warnings; empty,
  loading, and error states on every async surface.
- `static/styles.css` — append-only within Warm Travel tokens (chips,
  cards, modal, DAG timeline, profile rows, responsive 980px/768px/375px).
- `tests/test_ui_trip.py` — 10 headless-chromium flows on 127.0.0.1:8050
  (session uvicorn thread; per-test fresh ProfileStore + TripOrchestrator
  per the G3 harness pattern; every flow captures console and fails on ANY
  console error/pageerror, filtering only third-party Google Fonts resource
  failures from the pre-existing frozen `<link>` tags).

Flow results (all PASS, fresh run at gate time):

| Flow | Test | Result | Screenshot |
|---|---|---|---|
| B1 goal chat → clarify chips → confirm | `test_b1_goal_chat_clarify_chips_confirm` | PASS | `screenshots/g4_b1_clarify_chips.png` |
| B2 sandbox option cards (carrier text, SGD/THB, provenance) | `test_b2_b3_sandbox_options_approval_pnr` | PASS | `screenshots/g4_b2_option_cards.png` |
| B3 approval modal → confirm → PNR screen | same test (single trip lifecycle) | PASS | `screenshots/g4_b3_pnr_screen.png` |
| B4 DAG node growth within 1s cadence | `test_b4_dag_panel_node_growth_within_1s` | PASS | `screenshots/g4_b4_dag_panel.png` |
| B5 profile editor + masked passport `MD*****67` | `test_b5_profile_editor_and_masked_passport` | PASS | `screenshots/g4_b5_profile_editor.png` |
| B6 two-run memory greeting (remembered home_city) | `test_b6_two_run_memory_greeting` | PASS | `screenshots/g4_b6_remembered_greeting.png` |
| Scope 3-choice + flight-only (no hotel/activities) | `test_scope_three_choice_flow_and_flight_only` | PASS | `screenshots/g4_scope_flight_only.png` |
| Degraded + stale visa warnings visible | `test_degraded_and_stale_visa_warnings` | PASS | `screenshots/g4_visa_degraded.png`, `screenshots/g4_visa_stale.png` |
| XSS goal payload renders inert | `test_xss_goal_payload_renders_inert` | PASS | — |
| Mobile 375px, no horizontal overflow | `test_mobile_375_trip_view_no_overflow` | PASS | `screenshots/g4_mobile_375_trip.png` |
| Completeness sweep (every interactive element carries a testid) | `test_ui_completeness_sweep_testids` | PASS | — |

B2+B3 share one test function on purpose: the UI tracks only trips started
in its own page session (trip_id is JS state, lost on reload), and each
test installs a fresh store/orchestrator.

Canary (legacy rescue UI unbroken): `python main.py` booted on :8050,
`tests/e2e_full_journey.py` run against it — **14/14 PASS**, including
live-Qwen concierge, radar scan, EU261 positive case, mobile sanity.

Gate evidence (`TZ=UTC .venv/bin/python -m pytest tests/ -q`, run fresh
against remediation commit 1fed80d):

```
before (G3 gate a8bb94a):          188 passed
after G3-DA remediation (1fed80d): 197 passed (+9 regressions)
after G4 UI suites (full suite):   207 passed in 48.30s (+10 UI flows)
UI suite alone:                    10 passed in 17.19s
```

Honesty notes:

- The suite must run under `TZ=UTC`: `test_s6_yesterday_date_only_citation
  _is_stale_under_24h_policy` (pre-existing, frozen) computes "yesterday"
  from LOCAL `date.today()` but ages against UTC midnight — after local
  midnight in UTC+ zones the two disagree and the test flakes. Not a G4
  regression; reported to the leader.
- UI flows use FakeAtlas (deterministic sandbox stand-in, same pattern as
  the G3 unit suites); live-sandbox behavior is covered by the G3 E2E
  suite. Provenance labels ("Atlas Sandbox data") are asserted in both.

### G4 UI completeness sweep (§8)

Static inventory: 70 interactive elements carry a `data-testid`; the sweep
enumerates `button, input, select, textarea, a[href], summary, .nav-icon,
.bottom-nav-item` and fails if any lacks one.

| Area | Elements (data-testid) | Covered by |
|---|---|---|
| Trip view (new) | trip-goal-input/submit/form/loading, trip-chat, trip-clarify-chips, trip-scope-choices, trip-visa-panel, trip-approval-banner/overlay/options/note, approval-approve/reject, trip-options(-empty), sandbox-provenance, trip-pnr-screen, trip-itinerary(-empty), trip-dag-panel/list/live/empty, trip-status-strip/pill, trip-latency, trip-error, trip-greeting, trip-profile-editor/rows/empty, profile-consent | B1–B6 + edge-flow assertions in `tests/test_ui_trip.py` (chip inputs/confirms, scope choices, approval buttons, profile edit/save/delete rows are dynamic and carry testids at render time) |
| Navigation | nav-rescue/search/concierge/radar/trip, mnav-rescue/search/concierge/radar/trip | `goto_trip`/`mnav-trip` clicks in UI suite + canary view switches |
| Rescue (legacy) | btn-add-flight, btn-af-cancel/add, input-flight-number/date/passenger-name/nationality/currency, btn-simulate, btn-payout, btn-appeal, btn-done, claim-letter-summary, appeal-summary, chip-vegetarian/gate/baggage/claim | canary `tests/e2e_full_journey.py` (clicks + expects, 14/14) |
| Concierge (legacy) | chat-input, btn-send | canary live-Qwen reply flow |
| Search (legacy) | search-origin/destination/date/passengers/currency, btn-search | canary flight-search flow |
| Radar (legacy) | btn-radar-scan | canary radar flow |
| Out-of-demo-scope (reason) | `.btn-rebook`, `.btn-radar-accept` — created at runtime by FROZEN `static/app.js`; data-testid cannot be added without editing it | covered behaviorally by canary clicks in `tests/e2e_full_journey.py` |


### G4 Devil's Advocate + live-browser remediation

Merged Devil's Advocate review + independent browser-validator findings
against the G4 gate (286bc15); remediated per finding with failing
regressions FIRST (TDD), then root-cause fixes. Scope isolation held:
static/app.js, services/* (incl. atlas_client.py, trip_graph.py),
pre-existing tests, AGENTS.md, README, .env untouched; the live
validation server on :8050 (PID 40933) never killed or restarted.

| # | Finding | Repro | Fix | Regression evidence |
|---|---|---|---|---|
| F1 | 1s polling never stops after terminal status / leaving trip view | reproduced (code: interval only cleared at startWatching start) | terminal stop after final renderState + MutationObserver on #view-trip class (app.js frozen) | `test_f1_polling_stops_on_terminal_and_view_exit` |
| F2 | stale in-flight /state response can resurrect resolved scope / regress DAG | reproduced (no seq guard; equality re-render) | epoch + monotonic seq/appliedSeq + AbortController; invalidatePolls before every trip-mutating POST; monotonic DAG signature | `test_f2_stale_poll_cannot_resurrect_resolved_scope` |
| F3 | error banner never clears on recovery | reproduced (hideError only in submitGoal) | hideError() at top of every successful renderState | `test_f3_error_banner_clears_on_recovery` |
| F4 | non-profile clarify chips silent no-op; rerun fails missing_route | reproduced (confirm rendered "✓ noted", nothing persisted) | POST /api/trip/{id}/clarify-answers persists into goal (seed + context), strips the question, resumes failed missing_route/missing_dates trips with the SAME scope | `test_clarify_answer_feeds_trip_goal_and_resumes`, `test_clarify_answer_date_window_parses_and_rejects_garbage`, `test_f4_origin_city_chip_persists_and_trip_resumes` |
| F5 | sandbox options ignored requested date window | PARTIAL — glue verified intact (input_map forwards date_window.start); CLI probe `atlas-flight search --depart 2026-09-29` honors the date; root cause: F4 no-op dropping the window + sandbox clamp for same-day/past dates | requested_date + honest date_note on flight_search output; UI warning chip; honest limitation logged (DECISIONS.tsv) — atlas_client.py untouched | `test_date_window_is_forwarded_to_atlas_search`, `test_date_window_substitution_is_labeled_not_silent` |
| F6 | S$ price paired with ฿ conversion (wrong currency math) | reproduced in live browser | native fare currency + labeled indicative SGD estimate; ฿ pairing removed | `test_f6_option_currency_rendered_honestly` + updated B2 assertion |
| F7 | appended mobile rules restyle legacy #bottom-nav | reproduced (lines 1899–1900 inside @media 768px) | AUTO- decision row logged; rules kept (append-only CSS; mobile 375px contract depends on them) | — (logged, DECISIONS.tsv AUTO-) |
| F8 | unknown itinerary sources fall to "💡 suggestion only" | reproduced (else branch ignores honesty_label) | honesty_label fallback before the blanket chip | `test_f8_unknown_itinerary_source_falls_back_to_honesty_label` |
| F9 | querySelector from server field name throws on quotes | reproduced (line 285 raw interpolation) | CSS.escape + attribute-scan fallback | `test_f9_hostile_field_name_does_not_throw` |
| (e) | stale option cards leak across trips | reproduced by independent browser validator | resetTripSurfaces() on every new trip + null sentinel on renderedOptionIds | `test_f10_new_trip_clears_stale_panels` |

Gate evidence (`TZ=UTC .venv/bin/python -m pytest tests/ -q --ignore=tests/test_ui_trip.py`):

```
before remediation (286bc15): 197 passed in 32.19s
after  remediation (non-UI):  201 passed in 32.38s (+4 e2e regressions)
```

UI suite (`tests/test_ui_trip.py`, +8 regressions, 18 flows total): runs
against its own uvicorn on 127.0.0.1:8050 — RERUN PENDING: the live
validation session kept the port for the full 15-minute retry window
(never killed per scope isolation); the rerun is recorded in BLOCKERS.md
and scheduled by the leader once the validation session ends.
