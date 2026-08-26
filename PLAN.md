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
- [ ] generic journey script (httpx): start→clarify(stub LLM)→search(live sandbox)→visa(baseline)→approve→book→monitor arm
- [ ] E2E happy path + visa-block reroute + disruption path
- Evidence: journey script output; PNR-shaped object provenance-flagged sandbox.

### G4 UI Gate
- [ ] Playwright flows B1–B6 green; `data-testid` on interactive elements
- [ ] screenshots saved to `screenshots/` (gitignored)
- [ ] UI completeness sweep: every interactive element asserted or listed out-of-demo-scope
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
| §12 demo fixture placeholder | `data/mock_victor.json` (gitignored) | `[mockdata]`-tagged suites at G7; graceful skip while owner absent | G7 report section |
| §0/§9.7 gate process artifacts | `PLAN.md`, `DECISIONS.tsv`, `BLOCKERS.md` | `tests/test_docs_integrity.py` conventions (durable-docs hygiene) | gate commit pytest output |
