# Build Self-Report

Interim report written at G6 (Cleanup & Report Gate), updated at G7
(mock-data pass — owner absent, graceful skip). G8 (completion/smoke)
finalizes this file; see status flags per section.

## Stages completed: G0..G7

| Gate | Commit | Scope (evidence: `git show <hash>`) |
|---|---|---|
| G0 Plan | (see `git log` G0 row) | PLAN.md, DECISIONS.tsv, BLOCKERS.md skeletons |
| G1 Contracts | 5b5ebf1 | §5 contracts, skill scaffolding, profile store |
| G2 Core | 2a3715a + 462fab1 (DA) | executor, coordinator, 11 skills + DA fixes |
| G3 Integration | a8bb94a + 1fed80d (DA) | trip/profile/skills APIs + live-sandbox E2E |
| G4 UI | 286bc15 + eb0b2b7/bc54833 (DA) | trip UI + Playwright B1–B6 + DA/browser fixes |
| G4.5 UX | dbeea07 + 6e27506 | ATLAS JOURNEY redesign spec + beginner UI |
| G4.6 Safety | dc7efc6 + fca3d26 (DA) | safety pipeline + fail-closed DA remediation |
| G5 Security | 56a12f8 | secret scan + hook + privacy suite + dep audit |
| G6 Cleanup | (this commit) | CI repair, cleanup sweep, this report |
| G7 Mock-Data | (this commit) | `[mockdata]` victor suite; owner absent → graceful skip, run-path proven synthetic |

## Features vs acceptance criteria (F1..F12)

| # | Feature | Status | Proof pointer |
|---|---|---|---|
| F1 | Conversational goal intake | PASS | `tests/test_skills_behavior.py` (11 golden phrasings), `tests/test_e2e_trip_journey.py` happy path |
| F2 | ClarifyLoop | PASS | `tests/test_skills_behavior.py` clarify cases (zero redundant questions, chip-confirm before save), UI flow B1 |
| F3 | Flight search/book | PASS | live-sandbox E2E happy path (provenance asserted non-canned; PNR-shaped object), idempotency + reverify in `tests/test_trip_graph.py` |
| F4 | VisaCheck hybrid | PASS | baseline ≤50ms cases + fresh/stale citation states + network-fail degrade in `tests/test_skills_behavior.py` |
| F5 | ProfileStore | PASS | `tests/test_profile_store.py` (atomic write, 0o600, source tags, consent, masking) + `tests/test_privacy.py` |
| F6 | RightsEngine integration | PASS | pre-existing rights tests (frozen) + canary EU261 positive case (CDG-BKK → EUR600 + cited appeal letter) |
| F7 | RecoveryDAG subgraph | PASS | disruption E2E path, DAG trace in state outputs, UI recovery surface (G4.5) |
| F8 | Telegram Guardian push | PASS | sent-with-token / `skipped_not_failed` without — `tests/test_skills_behavior.py` guardian cases |
| F9 | Live DAG panel | PASS | `test_b4_dag_panel_node_growth_within_1s` (UI suite) |
| F10 | Two-run memory | PASS | `test_b6_two_run_memory_greeting` (remembered home_city) |
| F11 | Honesty labeling | PASS | suggestion-only chips, sandbox provenance chips, honesty-label fallback (G2/G4 + G4.5 vocabulary tests) |
| F12 | Skills manifest | PASS | `/api/skills` listing + loader governance (`tests/test_skills_manifest.py`: count, add/remove, malformed, drift) |

## Test results

```
non-UI suite (unit + integration + E2E):   316 passed in 47.78s (TZ=UTC)
UI suite (Playwright headless chromium):    38 passed in 85.95s
legacy canary (tests/e2e_full_journey.py):  14/14 PASS (booted app)
JS syntax gate (node --check):              static/app.js + static/trip.js exit 0
security gate (scripts/security_check.sh):  ALL SECTIONS PASS
```

Key screenshots: `screenshots/` (gitignored) — G4 B1–B6 probes and G4.5
AJ07–AJ10 suite evidence (`g45_*.png`).

## Security/audit findings + resolutions

G5 gate (56a12f8): banned-pattern scan over the tracked tree ZERO;
pre-commit hook installed and live-fire proven (fake AWS-shaped key
refused); XSS usage-shape sink audit zero on owned `static/trip.js`
(frozen legacy `static/app.js` reported informationally); 35 privacy/
boundary tests green (masking, consent, chmod 600, PII-free envelopes
and app logs, aliasing refusal, safety-contract field ban); pip-audit
clean after upgrading the venv pip 26.1.1 → 26.2.1 (the only
advisories were against pip itself). Honesty note: gitleaks binary is
not installed on this host — the built-in scanner is the gate and the
hook delegates to gitleaks automatically once installed.

G4.6 Devil's Advocate (fca3d26): 6 fail-open/crash findings fixed
TDD-style — critical booking-after-failed-verification-retry,
recovery exception swallow, stale-assessment gating (24h TTL),
missing-evidence pass-through, monitor-crash data loss, hostile-text
engine crash. Full table in PLAN.md § "G4.6 Devil's Advocate
Remediation".

## Decisions log summary (DECISIONS.tsv top 10)

1. Scope clarification pauses with exactly 3 choices before any irreversible work (G2).
2. Idempotency lookup sits AFTER every safety/visa gate; keys scoped per trip (G2-DA).
3. Manifest governance fail-closed: adapters/safety skills are explicit documented exemptions; registry pinned at 11 (G3-DA, G4.6).
4. `do_not_travel` blocks booking AND recovery with no override; approval never removes risk (G4.6).
5. LLM NEVER decides safety: deterministic SafetyPolicyEngine only; closed 5-level vocabulary; never the word "safe" (G4.6).
6. All safety tests hermetic via injected transports; unavailable sources degrade toward unable_to_verify, never "passed" (G4.6).
7. `unable_to_verify` blocks booking UNCONDITIONALLY — a failed retry is not a clearance (G4.6-DA-fix F1).
8. Stale cached safety assessments never gate booking (`safety_ttl_seconds`, default 24h) (G4.6-DA-fix F3).
9. Suite runs under TZ=UTC (one pre-existing frozen test is clock-dependent in non-UTC locales) (G3-DA).
10. Secret gate = built-in banned-pattern scan shared by hook + tree scan; gitleaks auto-delegation when present (G5).

## Deleted/unused removed list

G6 sweep over `git ls-files` (full inventory reviewed): no dead code,
dead routes, or stale scaffolding found — every router is registered in
`main.py`, every skill pair is manifest-governed, docs are historical
specs or the live build package. Untracked scratch (screenshots/,
__pycache__/, .qoder/, e2e_screenshots/) is gitignored, never committed.
The G5 hook live-fire probe file was created, proven refused, and
removed. CI repair replaced the broken workflow (which targeted a
nonexistent `test_rescue_agent.py`) — nothing else removed.

## Known limitations + suggested next steps

- Live official advisory endpoints are not guaranteed reachable from the
  build environment; safety tests are hermetic via injected transports
  and per-source availability is reported honestly. Next: run a
  live-source smoke when network policy allows.
- `data/mock_victor.json` still carries placeholders (owner fills real
  values; file gitignored) — G7 executed its contracted owner-absent
  branch: the `[mockdata]` suite (`tests/test_mockdata_victor.py`,
  5 tests) skips gracefully with honest reasons, and its full run-path
  (API journey + browser flow) is proven against synthetic fixtures,
  injectable via `MOCKDATA_FIXTURE=<path>`. Owner's only remaining
  action: fill the fixture and rerun `pytest -m mockdata`.
- gitleaks binary absent on the build host (built-in scanner gates
  instead; hook upgrades transparently).
- CI repaired but the branch is local-only by package rule — the first
  real CI run happens at push time.
- The pre-existing `test_s6_yesterday_date_only_citation_is_stale_...`
  test requires TZ=UTC (clock-shape, not a regression).

## Remaining risks (honest)

- Frozen legacy `static/app.js` renders some server strings through
  injection sinks; it is sha256-pinned and canary-covered, but a future
  unfreeze should port it to createElement/textContent.
- The canary and live-sandbox E2E paths depend on `.env` credentials and
  external sandbox/Qwen availability; they degrade honestly (never
  fabricate) but are environment-sensitive.
- The safety pipeline blocks bookings it cannot verify — an availability
  trade-off chosen deliberately (fail-closed over fail-open).
