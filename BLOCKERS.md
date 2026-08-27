# BLOCKERS

Record any issue that resists resolution after 3 attempts (spec §0 rule 7).
Each entry must carry: repro steps + hypothesis, then choose the nearest
working alternative and continue. Never block the build silently.

Entry template:

```
## <date> — <short title>
- Repro: <exact command/steps>
- Attempts: <what was tried, up to 3+>
- Hypothesis: <most likely root cause>
- Alternative chosen: <nearest working path>
- Status: OPEN | WORKAROUND | RESOLVED
```

## Entries

## 2026-08-26 — mock_hotels_sg.json activities missing price_range_sgd key
- Repro: structural validation of `data/mock_hotels_sg.json` required every
  item to carry `name/type/price_range_sgd/source_url/researched_as_of/
  researched`; 7 of 12 activities lacked the `price_range_sgd` key.
- Attempts: re-checked each source page referenced by the entries; none
  listed a price for those attractions.
- Hypothesis: the research pass recorded only facts the sources actually
  published; the key was omitted instead of represented.
- Alternative chosen: added explicit `"price_range_sgd": null` to the 7
  activities (structural fix only — no values invented, per §15.1
  omit-rather-than-invent); each item keeps its `price_notes` explaining the
  omission. ItinerarySkill loads all 34 entries with degraded=False.
- Status: RESOLVED (committed with the G3 gate)
## 2026-08-27 — G4 remediation UI suite rerun pending on port 8050
- Repro: `TZ=UTC .venv/bin/python -m pytest tests/test_ui_trip.py -q` — the
  `app_server` fixture fails fast when 127.0.0.1:8050 is occupied; the live
  browser-validation session owns the port (PID 40933).
- Attempts: probed the port every 10s for the full 15-minute retry window
  after all other remediation work completed; the validation server never
  released it. Scope isolation forbids killing/restarting PID 40933.
- Hypothesis: the independent validation session keeps its server alive
  until its own workflow finishes.
- Alternative chosen: all non-UI evidence captured (201 passed, TZ=UTC);
  the 8 new Playwright regressions collect cleanly (18 UI flows total)
  and await the rerun.
- Resolution (2026-08-27, G4-DA-fix-2): the validation session ended and
  the port freed; the stale occupant was killed and the full UI suite ran
  twice green — `18 passed in 41.94s` and `18 passed in 46.27s` (TZ=UTC).
- Status: RESOLVED

## 2026-08-27 — G4.6 safety intelligence pipeline
- No honest blockers. One intermittent UI-suite flake appeared during the
  verification loop; root cause was an invalid Playwright API call
  (`locator.wait_for(state="focused")` — "focused" is not a valid state)
  that raised instead of waiting. Fixed at the root with
  `expect(...).to_be_focused(timeout=10000)` in both affected flows; no
  assertion was weakened or skipped.
- Source-availability note (honesty, not a blocker): live official
  advisory endpoints are not guaranteed reachable from the build
  environment; every safety test is hermetic via injected transports and
  unavailable sources are reported as `unavailable`, never as passed.
- Status: NONE OPEN

## 2026-08-27 — G7 regression: one-off UI flake (reconsider-ack flow)
- Repro: during the G7 full-UI regression (run concurrently with other
  foreground commands), `test_ui_safety_reconsider_requires_acknowledgement`
  failed once (1 failed, 37 passed in 100.16s).
- Attempts: reran the single test in isolation (PASS in 3.87s), then a
  clean full-suite rerun (38 passed in 89.20s).
- Hypothesis: timing/polling flake under host load — the flow is
  poll/SSE-driven and the run overlapped other work; no code changed
  between the green G5 run and this run.
- Alternative chosen: accepted the clean rerun as evidence; no assertion
  weakened, no code changed.
- Status: RESOLVED (flake; green on rerun)

## 2026-08-27 — Canonical spec reconciliation (reviewer rejection)
- Repro: reviewer rejected "Full Product Complete" — repo held a STALE
  422-line MASTER_BUILD_PACKAGE (sha256 f63d6d2b…) while the authoritative
  canonical package is 946 lines (sha256 6283789fb1ce1f8f23289a65804d776e
  3e37dd29f7fd03d440f18363ad5e36fc). Build had executed F1–F12 instead of
  the canonical F1–F20 / S1–S13.
- Attempts: n/a — this is a spec-authority correction, not a test failure.
- Hypothesis: the repo package copy drifted from the canonical source; all
  gate evidence was internally consistent but built against the stale copy.
- Alternative chosen: replaced docs/MASTER_BUILD_PACKAGE.md with the
  SHA-verified canonical 946-line package; opened corrective units R1–R5
  (passport-number removal; legacy XSS; My-Trip default + consolidation;
  canonical feature gaps incl. F13 LocationResolve; FINAL_REPORT rebuild
  + full fresh-venv runbook + DA review).
- Status: RESOLVED by R0–R7 through dbbe2d7

## 2026-08-27 — Atlas sandbox unreachable
- Repro: live CLI probe returned no offers for BKK->SIN at test time.
- Attempts: ran the E2E on the documented curated fallback (provenance 'sandbox').
- Hypothesis: Sandbox provider availability is limited/intermittent.
- Alternative chosen: used hermetic fallback options. This is a structured provider-availability limitation, not a product bug.
- Status: WORKAROUND
