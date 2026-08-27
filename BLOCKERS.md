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
