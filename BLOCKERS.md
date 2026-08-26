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
  the 8 new Playwright regressions collect cleanly (18 UI flows total) and
  await the rerun; leader schedules it once the validation session ends.
- Status: OPEN
