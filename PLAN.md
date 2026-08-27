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
- [x] gitleaks pre-commit hook; banned-pattern grep over tracked tree returns zero
- [x] dependency advisory scan of new deps
- [x] XSS check (textContent/createElement only), pydantic boundary validation, profile chmod verified
- Evidence: `scripts/security_check.sh` output (G5 gate section below).

### G6 Cleanup & Report Gate
- [x] dead/experimental code deleted; `git status` shows intentional files only
- [x] CI workflow repaired to run the `tests/` suite
- Evidence: CI run log (deferred — branch is local-only by package rule;
  YAML validated, commands proven locally); clean status output;
  `FINAL_REPORT.md` (interim, finalized at G8).

### G7 Mock-Data Pass
- [x] `data/mock_victor.json` real values supplied by owner; `[mockdata]` suites re-run — OWNER ABSENT at gate time: fixture still placeholder; the `[mockdata]` suites (`tests/test_mockdata_victor.py`) skip gracefully with an honest reason, and their FULL run-path (API journey + browser flow) is proven against synthetic real-shaped fixtures (also injectable via `MOCKDATA_FIXTURE=` for the owner's dry run)
- [x] if owner absent: graceful skip recorded with honest limitation in `FINAL_REPORT.md`
- Evidence: G7 gate section below.

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
| G4.6 SafetyResearchSkill (read-only researcher, injected transport, per-source honest statuses) | `services/skills/safety_research.py`, `services/safety/adapters.py` | `tests/test_safety.py` adapter/skill sections | G4.6 gate commit pytest output |
| G4.6 SafetyPolicyEngine (pure, deterministic, closed vocabulary, applicability/conflict/freshness, never-"safe") | `services/safety/policy.py` | `tests/test_safety.py` engine section (18 hermetic scenarios) | G4.6 gate commit pytest output |
| G4.6 SafetyMonitorSkill (consent-gated, evidence-hash change events, propose-not-rebook) | `services/skills/safety_monitor.py` | `tests/test_safety.py` monitor section | G4.6 gate commit pytest output |
| G4.6 contracts w/o passport-number/legal-identity/location/payment | `models/schemas.py` (SafetyQuery/SafetyEvidence/SafetyAssessment/SafetyChangeEvent) | `tests/test_safety.py` contract cases | G4.6 gate commit pytest output |
| G4.6 booking wiring (DNT blocks booking+recovery; reconsider needs separate ack; unable_to_verify blocks safety-critical) | `services/skills/flight_book.py`, `routers/v1/trip.py` | `tests/test_safety.py` booking-gate section, `tests/test_ui_trip.py` G4.6 flows | G4.6 gate commit pytest output |
| G4.6 endpoints GET/POST /api/trip/{id}/safety[/recheck\|/acknowledge\|/monitor] | `routers/v1/trip.py` | `tests/test_safety.py` API section | G4.6 gate commit pytest output |
| G4.6 SKILL.md manifests (loader rules + zero capability drift) | `services/safety/safety_research.SKILL.md`, `services/safety/safety_monitor.SKILL.md` | `tests/test_safety.py::test_safety_manifests_pass_loader_rules_and_have_no_capability_drift` | G4.6 gate commit pytest output |
| G4.6 My-trip Safety card UI (beginner language, foreign-advice labeling, Check again, no numeric score) | `static/index.html`, `static/trip.js`, `static/styles.css` (append-only) | `tests/test_ui_trip.py` 6 G4.6 flows | G4.6 gate commit pytest output |
| G5 secret scan (banned patterns over tracked tree ZERO; pre-commit hook on staged content, gitleaks-delegating when installed) | `scripts/security_check.sh`, `scripts/pre-commit`, `scripts/banned_secret_patterns.txt` | hook live-fire proof (fake AWS-shaped key refused) + section 1/3 of the gate script | G5 gate commit security_check.sh output |
| G5 forbidden-file/ignore coverage (*.env*, data/profiles/, mock_victor, screenshots never tracked) | `.gitignore` (hardened: `*.env*` + `!.env.example`, `.qoder/`) | section 2 of the gate script (check-ignore probes) | G5 gate commit security_check.sh output |
| G5 XSS sink audit (usage-shape sinks; trip.js strict zero, frozen app.js informational) | `scripts/security_check.sh` section 4 | `tests/test_ui_trip.py` XSS-inert payload flow + gate script | G5 gate commit security_check.sh output |
| G5 pydantic boundary + privacy contracts (masking, consent, chmod 600, PII-free envelopes/logs, safety-contract field ban) | `tests/test_privacy.py` (35 tests) | the suite itself | G5 gate commit pytest output |
| G5 dependency advisory scan | `.venv` (pip-audit) | `pip-audit` over the installed venv | G5 gate commit security_check.sh output |
| G7 [mockdata] victor pass (graceful skip while owner absent; run-path proven synthetic; API + browser) | `tests/test_mockdata_victor.py`, `pytest.ini` (marker) | the 5 `[mockdata]` tests incl. injected-fixture proof run | G7 gate commit pytest output |

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
against its own uvicorn on 127.0.0.1:8050 — rerun completed under
G4-DA-fix-2 below (port freed; 18/18 passed twice).

### G4-DA-fix-2 — trip.js syntax regression + JS syntax gate

Root cause: remediation commit eb0b2b7 dropped the else-branch of the
carrier-label ternary in `renderOptions` (static/trip.js ~line 601):
`carrierName + (CARRIER_NAMES[o.carrier] ? ' (' + o.carrier + ')');` →
SyntaxError at parse time → the entire trip.js module died on every page
load (no init, native GET form reload, whole trip UI dead; the "suite
hang" was 18 tests burning expect-timeouts). Independent debugger
verified with live probes.

Fixes:

1. One-line restore: `var carrierLabel = carrierName +
   (CARRIER_NAMES[o.carrier] ? ' (' + o.carrier + ')' : '');`
2. Durable guard: NEW `tests/test_static_js_syntax.py` runs
   `node --check` over every `static/*.js` (parametrized per file);
   `pytest.skipif(shutil.which("node") is None, ...)` skips with a note
   when node is absent. 2 tests (app.js, trip.js) — node v26.7.0 present
   on this host.
3. Debugger secondary observation: `chipByField` dropped the
   CSS.escape-inside-quoted-attribute-selector branch (wrong escaping
   context — a value containing a double quote still terminates the
   string) and keeps only the attribute-scan fallback.
4. Collateral UI-suite repairs surfaced while re-verifying (same commit):
   confirmChip restarts the watcher when a chip answer resumes a terminal
   (failed) trip (`Trip.terminal` had stopped polling); f1/f4 wait on the
   scope-choice block before asserting passport/failed states; f10 waits
   for the new trip's goal echo in chat before asserting stale-panel
   clearing; f3 rewritten as a deterministic phase-machine (hold first
   /state poll → fail second with 500 → hold all further polls until the
   test releases one real response) so the banner-clear window can no
   longer race the poll/SSE cadence.

Gate evidence (TZ=UTC, port 8050 free):

```
node --check static/trip.js:                     exit 0
node --check static/app.js:                      exit 0
UI suite  (tests/test_ui_trip.py, run 1):        18 passed in 41.94s
UI suite  (tests/test_ui_trip.py, run 2):        18 passed in 46.27s
non-UI    (tests/ --ignore=test_ui_trip.py):     203 passed in 32.67s
                                                 (201 prior + 2 syntax gate)
```

## G4.5 — ATLAS JOURNEY beginner-friendly trip UX redesign

Spec: `docs/superpowers/specs/2026-08-27-atlas-journey-trip-ux-redesign.md`
(decision-complete). Files touched: `static/trip.js` (rework),
`static/index.html` (additive AJ sections, dual-testid per spec D5),
`static/styles.css` (append-only AJ token block), `tests/test_ui_trip.py`
(B1–B6 intent kept + 13 AJ regressions), `routers/v1/trip.py` (smallest
backend additions the spec demands). Frozen files untouched (verified
below).

### Shipped per spec section

1. **IA (spec D7)** — 3 destinations Plan a trip / My trip / Help rendered
   INSIDE `#view-trip` (`aj-nav-*`); frozen sidebar/bottom-nav intact;
   profile drawer from the AJ top bar; no engineering dashboard.
2. **5-step guided flow** — Tell us what you need → Choose → Review →
   Confirm → Track; only current step expanded, completed steps compact
   summaries with Edit, future steps collapsed + `aria-disabled`. Maps to
   start / clarify-answers / approvals / state / simulate-disruption.
3. **Start screen** — headline + one-sentence explanation + goal composer
   + 3 starter choices initializing RequestedServices (editable chips);
   custom goals infer services; confirm only ambiguous scope; nothing
   auto-added.
4. **Clarification** — one focused question card at a time (question,
   why-needed, direct choices, Back + Save/Confirm) + confirmed-facts
   compact editable summary; wired via POST `/api/trip/{id}/clarify-answers`.
5. **Beginner language** — full translations table (Booking reference, How
   this plan was made, Check entry requirements, Sources, Last checked,
   Booking status, What happens next); result-stating buttons; one primary
   action per screen; max 3 ranked flight options + Show more with ranking
   reasons; itinerary day-grouped 6 items + Show more (D4); advanced
   filters / raw citations / provider diagnostics / Agent Trace in
   collapsed disclosures.
6. **Recovery surface** (audit gap closed) — disruption shows original
   trip preserved, replacement options separately with suitability
   reasons, SEPARATE recovery approval, only when needed; backend
   suitability reasons added in `routers/v1/trip.py` only (spec demanded).
7. **Living Journey Line** — SVG/CSS only, 7 spec states incl. one
   restrained confirmation pulse, disruption branch (muted-coral original
   + recovery path), `prefers-reduced-motion` fully static (AJ12).
8. **ATLAS JOURNEY tokens** — Canvas Ivory / Atlas Ink / Deep Teal /
   Seafoam / Sunline Amber / Signal Coral (disruption/destructive only) /
   Border Mist / White cards; monospace only for codes/times/prices/refs;
   body ≥15px; 12px radius; ≥44px touch targets; no glassmorphism or
   perpetual animation.
9. **9-state matrix (AJ10)** — empty/loading/success/degraded/validation
   error/provider failure/expired approval/uncertain booking/offline all
   mapped to real API envelopes incl. live 422 `invalid_goal`
   plain-language handling (D2); ARIA live regions; keyboard-only
   completion (AJ11); focus trap + restore in dialogs; 360px no overflow.
10. **Profile surface (AJ09)** — safe-fields presentation, Edit/Delete per
    field, consent control, explicit statement that passport
    number/payment details/legal identity are not stored unmasked.

### Review-loop findings + fixes log

Viewports probed: 1440x900, 768x1024, 360x800 (own instance on :8051 when
8050 was suite-occupied). Each reproducible finding got a fix + regression.

| # | Finding (skeptical-beginner pass) | Fix |
|---|---|---|
| 1 | State boxes (validation/expired/degraded) invisible once rail advanced past step 1 — `aj-state-slot` lived inside collapsed step-1 body | moved slot to pane level (top of `#aj-dest-plan`); AJ06/b2 assertions green |
| 2 | Show-more expanded list collapsed back to 3 on poll re-render | `Trip.preserveOptionCap` — forced re-renders keep the expanded cap; only NEW option sets reset to top-3 (AJ04) |
| 3 | Starter-choice service chips vanished after goal submitted | `pendingProvServices` carry-through: submitGoal restores starter services AFTER `resetTripSurfaces()` (AJ02) |
| 4 | All-'unknown' server snapshot hid provisional service chips | renderServices fallback to `Trip.provServices` when snapshot yields none |
| 5 | Keyboard users couldn't submit goal (Enter in textarea = newline) | AJ11 Tabs to `trip-goal-submit` then Enter — documented keyboard path |
| 6 | f8 crafted itinerary wiped by background 1s `/state` poll | test stubs `/state` via a permanently-installed fetch wrapper with a `__f8Off` mode flag (see fetch(null) artifact below) |
| 7 | After booking, My trip auto-switch hid goal composer for trip B | f10 takes the beginner path: `aj-nav-plan` → Edit step 1 |
| 8 | At 360px legacy top nav icons hidden | probes/suite use `mnav-trip` bottom nav; top bar flex-wrap keeps 360px overflow-free |
| 9 | Deterministic live-422 trigger needed | impossible-date goal "Fly on February 30 2026" → 422 `invalid_goal` → plain-language validation box (AJ10/D2) |

**Chromium fetch(null) artifact (cross-cutting test-infra discovery):**
re-assigning `window.fetch` BACK to a captured reference (e.g.
`window.fetch = window.__origFetch`) makes Chromium/Playwright emit a
`fetch(null)` probe → `GET /null` 404 console error. Proven reproducible
via CDP initiator probe on a minimal stub page. Rule now codified: tests
never re-assign `window.fetch` back — install one permanent wrapper and
toggle a mode flag (`__f8Off`).

### G4.5 completeness sweep (32 tests — `tests/test_ui_trip.py`)

| Group | Tests | Intent |
|---|---|---|
| B1–B6 preserved | b1 goal/chat/chips, b2+b3 options/approval/PNR, b4 DAG growth, b5 profile+masking, b6 two-run greeting | original G4 intents intact |
| G4 legacy | scope 3-choice+flight-only, degraded+stale visa, XSS inert payload, 375px + 360px no-overflow, testid completeness sweep | honesty/a11y/canary contracts |
| G4-DA fixes | f1–f4, f6, f8–f10 | prior remediation regressions stay green |
| AJ01–AJ13 (13 new) | IA destinations, starter services, one-question cards, max-3+Show more, vocabulary, honesty-never-hidden, journey-line states, recovery separate approval, profile drawer privacy, 9-state matrix, keyboard a11y, reduced motion, legacy canary | spec §10 exit criteria |

### G4.5 gate evidence (TZ=UTC, fresh runs)

```
node --check static/trip.js:                     exit 0
UI suite  (tests/test_ui_trip.py, run 1):        32 passed in 71.0s
UI suite  (tests/test_ui_trip.py, run 2):        32 passed in 71.5s
non-UI    (tests/ --ignore=test_ui_trip.py):     203 passed in 46.9s
canary    (tests/e2e_full_journey.py, booted):   14/14 PASS
```

Frozen-file confirmation: `static/app.js` sha256 pin
`2d1db42d79914bf5b807faccaff1cc25ce979a2c939abac5109ba96b000cb1ae5`
verified by AJ13; `services/rights_engine.py`, `visa_guard.py`,
`state_graph.py`, `guardian.py`, `atlas_client.py`, pre-existing tests, AGENTS.md,
README demo-flow, `.env` untouched (`git diff --stat` limited to the five
owned files + docs).

### Screenshots (gitignored `screenshots/`)

- Viewports/probes: `aj_probe_01_start_desktop.png`,
  `aj_probe_12_tablet768.png`, `aj_probe_13_mobile360.png`,
  `aj_probe_11_validation.png` (+`_desktop`, `_mobile360`),
  `aj_probe_14_rescue_canary.png`
- Screens: `aj_probe_02..05` clarification+options,
  `aj_probe_06_approval_modal(_desktop).png`,
  `aj_probe_07_mytrip(_desktop).png`,
  `aj_probe_08_recovery(_desktop).png`, `aj_probe_08b_recovery_outcome.png`,
  `aj_probe_09_help(_desktop).png`, `aj_probe_10_drawer(_desktop).png`
- Suite evidence: `g45_aj07_journey_line.png`, `g45_aj08_recovery.png`,
  `g45_aj09_drawer.png`, `g45_aj10_states.png`, `g45_mobile_360_trip.png`

## G4.6 — Safety intelligence pipeline (research, policy engine, monitor)

PRIME RULE: an LLM NEVER decides whether a country is safe. Assessment is
produced only by the deterministic `SafetyPolicyEngine` from verified
official-source evidence; no absolute "safe" wording anywhere.

### Components shipped

| Component | Files | Notes |
|---|---|---|
| SafetyResearchSkill | `services/skills/safety_research.py`, `services/safety/adapters.py`, `services/safety/__init__.py` | read-only researcher; injected `fetch` transport; per-source honest statuses `ok\|unavailable\|rejected\|no_coverage`; redirect/SSRF-style host validation (`url_ok_for_source`); tolerant parsing preserves native wording |
| SafetyPolicyEngine | `services/safety/policy.py` | pure + deterministic; closed vocabulary `normal_precautions\|increased_caution\|reconsider_travel\|do_not_travel\|unable_to_verify`; applicability (government advice scoped to its own citizens), conflict (worst verified wins), freshness rules; `contains_absolute_safe` regex guard; never "safe" |
| SafetyMonitorSkill | `services/skills/safety_monitor.py` | consent-gated (no consent → no check, no events); evidence-hash change detection; material changes only; `proposed_action="review"` — propose, never auto-rebook; bounded recheck interval |
| Contracts | `models/schemas.py` (append-only) | SafetyQuery/SafetyEvidence/SafetyAssessment/SafetyChangeEvent — NO passport number, legal identity, location, or payment fields |
| Booking wiring | `services/skills/flight_book.py`, `routers/v1/trip.py` | `do_not_travel` blocks booking AND recovery (no override, approval does not remove risk); `reconsider_travel` requires a separate explicit risk acknowledgement; `unable_to_verify` blocks safety-critical booking until fresh verification |
| API | `routers/v1/trip.py` | GET/POST `/api/trip/{id}/safety`, `.../safety/recheck`, `.../safety/acknowledge`, `.../safety/monitor` (consent toggle) |
| UI | `static/index.html`, `static/trip.js`, `static/styles.css` (append-only) | My-trip Safety card: beginner language, foreign-advisory labeling ("Advice issued for X citizens…"), Check again, monitor consent toggle, no numeric score; renders only when `safety_enabled` + goal_intake complete (zero-console-error contract) |
| Manifests | `services/safety/safety_research.SKILL.md`, `services/safety/safety_monitor.SKILL.md` | live OUTSIDE `services/skills/` to keep the frozen loader-glob registry pinned at 11; documented exemption; loader rules + capability drift verified by dedicated test |

### Test map (`tests/test_safety.py` — 69 tests; + 6 UI flows in `tests/test_ui_trip.py`)

- Adapters: host validation, redirect rejection, fetch-failure honesty,
  tolerant parsing, native-wording preservation, nationality scoping.
- Engine: the 18 hermetic scenarios (closed vocabulary, never-"safe",
  applicability, conflict resolution, freshness/staleness, degrade to
  `unable_to_verify`).
- Skills: research capability is `network_read` only; offline degrade;
  monitor consent/baseline/material-change/non-material/bounded-interval/
  revocation.
- Manifests: registry stays at 11; safety manifests pass the same loader
  rules with zero capability drift.
- Booking gate: DNT blocks with zero Atlas calls; reconsider blocks until
  separate acknowledgement; unable_to_verify blocks until retried
  verification; wording never contains absolute "safe".
- UI: card renders with sources (normal status), DNT blocks booking,
  reconsider requires acknowledgement, recheck + monitor consent, card
  hidden when pipeline disabled, 360px no overflow.

### Source-availability honesty

All tests are hermetic: evidence comes from injected transports
(`fetch=` parameter), never from fabricated advisories. Live official
sources are not guaranteed reachable from the build environment; the
skill reports per-source status honestly (`unavailable` degrades the
assessment toward `unable_to_verify`, never toward a false lower risk).
No unavailable source is ever marked as passed.

### G4.6 gate evidence (TZ=UTC, fresh runs)

```
node --check static/*.js:                        exit 0 (all files)
non-UI    (tests/ --ignore=test_ui_trip.py):     272 passed in 47.72s
UI suite  (tests/test_ui_trip.py, run 1):        38 passed in 89.45s
UI suite  (tests/test_ui_trip.py, run 2):        38 passed in 89.63s
canary    (tests/e2e_full_journey.py, booted):   14/14 PASS
```

Frozen-file confirmation: `git diff --name-only` limited to
`models/schemas.py`, `routers/v1/trip.py`, `services/skills/flight_book.py`,
`static/index.html`, `static/styles.css`, `static/trip.js`,
`tests/test_ui_trip.py` (+ new untracked `services/safety/`,
`services/skills/safety_{research,monitor}.py`, `tests/test_safety.py`);
`rights_engine.py`, `visa_guard.py`, `state_graph.py`, `guardian.py`,
`atlas_client.py`, `static/app.js`, pre-existing tests, AGENTS.md,
README demo-flow, `.env` all untouched.

### G4.6 Devil's Advocate Remediation (against gate commit dc7efc6)

An independent review of the gate commit found 1 critical fail-open plus
five further fail-open/crash paths. All six were reproduced with red
regression tests FIRST, then fixed at the root (same TDD process as the
G2/G3/G4 remediations). Decisions logged in `DECISIONS.tsv` under prefix
`G4.6-DA-fix` (+ one `AUTO-` evidence-scope row).

| # | Finding | Repro | Fix | Regression evidence |
|---|---|---|---|---|
| F1 | CRITICAL — booking proceeds after a FAILED unable_to_verify retry: `_ensure_safety(force=True)` set `verification_retried=True` regardless of the retry OUTCOME; the precheck had no utv raise; the flight_book gate honored the flag | red: precheck with every source dead → gate ctx (utv + retried=True) → FlightBookSkill returned a PNR | the skill gate blocks utv UNCONDITIONALLY; the orchestrator sets the flag only when a forced run VERIFIES (non-utv outcome); the precheck raises `safety_unverified` (422, recoverable) when the bounded retry fails | `test_da_f1_booking_refused_after_failed_unable_to_verify_retry` + rewritten `test_unable_to_verify_blocks_until_fresh_verification`, `test_unable_to_verify_gets_one_bounded_fresh_retry` (both previously PINNED the fail-open) |
| F2 | HIGH — recovery swallowed safety-check exceptions and proceeded with ZERO assessment and zero warning | red: research.run made to throw → `_build_recovery` produced options/note without any safety signal | honest degrade: `safety_unverified` flag + visible warning note + FAILED trace record; a cached DNT assessment still blocks | `test_da_f2_recovery_degrades_honestly_when_safety_check_throws`, `test_da_f2_cached_do_not_travel_still_blocks_when_recheck_throws` |
| F3 | HIGH — cached assessment gated booking decisions indefinitely (no TTL) | red: ttl=0 + advisory flip after the cached check → precheck trusted the stale normal | `TripOrchestrator.safety_ttl_seconds` (default 86400): the precheck forces a fresh verification when the cache is older | `test_da_f3_stale_assessment_forces_fresh_verification_at_booking` + control `test_da_f3_default_ttl_reuses_fresh_cache` |
| F4 | MED — safety enabled but nothing assessable (no destination) → null status injected, every gate passed | red: trip without dest_city → precheck returned silently | missing evidence raises `safety_unverified` (recoverable) — policy-engine rule extended to the wiring | `test_da_f4_booking_refused_when_no_assessment_possible` |
| F5 | MED — monitor-check exception discarded the already-computed fresh assessment (bare 500 on the recheck path) | red: monitor.check made to throw after consent | honest degrade: assessment survives, `monitor_status="check_failed"`, FAILED trace record; consent endpoint degrades too | `test_da_f5_recheck_keeps_assessment_when_monitor_check_throws` |
| F6 | MED — hostile evidence text crashed the engine: an authority or canonical URL containing the absolute word raised the never-"safe" AssertionError → 500 on the whole safety API | red: `_ev(authority="Ministry of Safe Travel")` and a URL path containing the word | authority is `_desafe`-stripped (per-source + disagreement entries); canonical URLs — locators, preserved verbatim — are excluded from the claim scan via `_without_urls` | `test_da_f6_hostile_authority_with_absolute_safe_is_stripped_not_fatal`, `test_da_f6_url_with_safe_substring_preserved_and_engine_intact` |

Scope isolation: fixes live in `routers/v1/trip.py`,
`services/skills/flight_book.py`, `services/safety/policy.py`,
`tests/test_safety.py` only. Frozen files (`rights_engine.py`,
`visa_guard.py`, `state_graph.py`, `guardian.py`, `atlas_client.py`,
`static/app.js`, pre-existing tests, AGENTS.md, README demo-flow, `.env`)
untouched. No pre-existing test weakened: the two rewritten tests had
PINNED the F1 fail-open semantics at gate time — their fail-closed
replacements are the contract the gate docstring always claimed
("unable_to_verify blocks until fresh verification").

Evidence-scope note: the untracked `tests/test_privacy.py` (interrupted
G5 work-in-progress) was excluded from these runs; its single failing
case is a stale route-shape expectation (the app refuses every aliasing
probe — verified by probe: `..`→404, `a%20b`→400, `a/b`→405,
`..%2Fevil`→405 GET / 400 PUT). Owned by the G5 gate.

Remediation evidence (TZ=UTC, fresh runs):

```
red phase (11 new/rewritten regressions): 9 failed / 2 controls passed
                                          (the 2 passing controls pin
                                          behavior the fixes must keep)
after fixes, targeted:                     14 passed in 0.37s
non-UI suite:                              281 passed in 47.89s
                                           (272 gate + 9 new regressions)
UI suite (tests/test_ui_trip.py):          38 passed in 94.04s
node --check static/trip.js / app.js:      exit 0
```

## G5 Security & Audit Gate

Scope: secrets scan, dependency audit, XSS/injection/input validation, and
profile privacy checks. Delivered as a single reproducible evidence
producer, `scripts/security_check.sh`, plus a version-controlled pre-commit
hook. Frozen files and pre-existing tests untouched.

Delivered:

- `scripts/security_check.sh` — six-section gate evidence producer
  (`--install-hook` copies the hook into `.git/hooks/`). Exits non-zero on
  any FAIL so it can guard CI at G6.
- `scripts/pre-commit` + `scripts/banned_secret_patterns.txt` — the
  version-controlled hook: refuses staged content matching a banned secret
  pattern (AWS key id, private-key block, GitHub/Slack/OpenAI tokens,
  URL-embedded credentials) and ADDITIONALLY delegates to gitleaks when the
  binary is installed. Fails closed if the pattern file is missing.
- `.gitignore` hardened: `*.env*` with `!.env.example` negation (covers
  `.env.local`/`.env.backup` variants the old single `.env` line missed)
  and `.qoder/` local tool state.
- `tests/test_privacy.py` — 35 hermetic privacy/boundary tests committed
  (was an untracked G5 leftover): mask_passport vectors, consent-gated
  persistence, chmod 600, masked-only API/disk bytes, PII-free error
  envelopes + app logs, cross-user aliasing refusal, safety-contract field
  ban, official-URL hardening, inert hostile content.

Honesty notes:

- gitleaks binary is NOT installed on this host. The gate is the built-in
  banned-pattern scan (identical pattern set in hook + tree scan); the hook
  auto-delegates to gitleaks the moment it is installed. Recorded honestly
  in the gate output NOTE and in DECISIONS.tsv.
- Dependency audit: `pip-audit` over the venv reports the runtime deps
  clean; the only findings were two advisories against `pip` itself
  (26.1.1), resolved by upgrading the venv's pip to 26.2.1.
- XSS audit targets USAGE-shape sinks (`.innerHTML =`,
  `insertAdjacentHTML(`, `document.write(`, `eval(`) so comment text that
  merely mentions a sink is not a false positive. `static/trip.js` (owned)
  carries ZERO sinks; frozen legacy `static/app.js` reports its sink lines
  informationally (canary-covered, sha256-pinned by AJ13).
- Hook live-fire proof: staging a file whose line carries a fake
  AWS-shaped key (the `AKIA` prefix + 16 uppercase-alphanumerics shape;
  literal redacted here so the live hook never refuses this doc) is
  REFUSED by the hook and the commit does not land; the probe was then
  removed.

Gate evidence (TZ=UTC, fresh runs):

```
scripts/security_check.sh:                 ALL SECTIONS PASS
  1/6 secret scan (tracked tree):          zero banned-pattern hits
  2/6 forbidden files / ignore coverage:   all PASS
  3/6 precommit hook + staged scan:        installed, clean
  4/6 XSS sink audit:                      trip.js zero sinks
  5/6 privacy/boundary suite:              35 passed
  6/6 pip-audit:                           No known vulnerabilities found
hook live-fire:                            fake AWS key refused (exit 1)
non-UI suite (incl. privacy):              316 passed in 47.78s
UI suite (tests/test_ui_trip.py):          38 passed in 85.95s
```

## G6 Cleanup & Report Gate

Scope: dead/experimental code removed, CI repaired to run the `tests/`
suite, and the §9.7 self-report written. Frozen files and pre-existing
tests untouched.

Delivered:

- Cleanup sweep over the full `git ls-files` inventory: NO dead code,
  dead routes, or stale scaffolding found. Every router is registered in
  `main.py`; every skill pair is manifest-governed; the only docs are the
  live build package plus historical specs. Untracked scratch
  (`screenshots/`, `e2e_screenshots/`, `__pycache__/`, `.qoder/`,
  `.pytest_cache/`) is gitignored and never committed. Honest result, not
  a forced deletion (spec rule 5: subtract — but subtract only what is
  actually dead).
- `.github/workflows/ci.yml` REPAIRED: the prior workflow targeted a
  nonexistent `test_rescue_agent.py` with an incomplete dep set. It now
  runs the real `tests/` suite in two jobs — `core` (security gate +
  non-UI suite under TZ=UTC) and `ui` (Playwright chromium on port 8050).
  YAML validated; each command proven locally. The first REAL CI run is
  deferred to push time (branch is local-only by package rule) — recorded
  honestly in FINAL_REPORT.md.
- `scripts/security_check.sh` made CI-capable: resolves the Python
  interpreter and pip-audit from the venv OR the ambient PATH, so it runs
  both in the dev venv and on a fresh runner.
- `FINAL_REPORT.md` written (interim): stages G0..G6 with evidence
  pointers, F1..F12 acceptance table, test counts, security findings +
  resolutions, top-10 decisions, cleanup list, limitations, and honest
  remaining risks. Finalized at G8 with the G7 outcome + fresh-boot smoke.

Gate evidence (TZ=UTC, fresh runs):

```
scripts/security_check.sh (CI-capable):    ALL SECTIONS PASS
non-UI suite (incl. privacy):              316 passed
UI suite (tests/test_ui_trip.py):          38 passed
ci.yml YAML:                               valid; jobs = core, ui
git status after sweep:                    intentional files only
```

## G7 Mock-Data Pass (victor fixture — owner absent, graceful skip)

Spec §12: after all gates are green on generic fixtures, load
`data/mock_victor.json` and re-run `[mockdata]`-tagged E2E + browser
suites. At gate time the owner has NOT filled the fixture (placeholders
intact), so the gate executes its other contracted branch: graceful skip
+ honest limitation — with the run-path fully proven, not assumed.

Delivered:

- `tests/test_mockdata_victor.py` — 5 `[mockdata]` tests:
  loader contract (real/placeholder/invalid-JSON honesty), API journey
  run-path (synthetic), browser journey run-path (synthetic), victor API
  journey, victor browser flow. The two victor cases SKIP with an honest
  reason while the fixture carries placeholders; all five RUN the day
  real values land (no code change needed).
- `pytest.ini` — registers the `mockdata` marker (clean collection
  output).
- The API journey seeds consent + identity via the §6 profile API,
  proves masked-only display before AND after booking, answers clarify
  questions through `POST /api/trip/{id}/clarify-answers` (G4-DA-fix F4
  resume semantics), and completes to a sandbox PNR. The browser flow
  boots the real app on 8050, drives goal → clarify cards → scope choice
  → approval banner, and keeps the zero-console-error contract.
- `MOCKDATA_FIXTURE=<path>` env override lets the owner (or a dry run)
  point the victor cases at any fixture file — used at gate time to prove
  the complete owner path end-to-end with a synthetic real-shaped fixture
  (values clearly synthetic; nothing personal committed).

Honesty notes:

- No personal data is committed: `data/mock_victor.json` stays gitignored
  with placeholders; the synthetic proof fixture lives only in tmp during
  test runs.
- The victor cases have never executed against REAL owner values — that
  is the owner's one remaining action; the suite needs zero changes.

Gate evidence (TZ=UTC, fresh runs):

```
owner-absent mode:                         3 passed, 2 skipped (honest)
injected-fixture mode (owner path proof):  5 passed in 9.20s
full non-UI suite:                         319 passed, 2 skipped in 52.10s
UI suite (clean rerun):                    38 passed in 89.20s
  (one load-induced flake in the reconsider-ack flow failed once during
   a concurrent run — green in isolation and on the clean rerun; logged
   in BLOCKERS.md, no code or assertion changed)
screenshot:                                screenshots/g7_mockdata_browser.png
```
