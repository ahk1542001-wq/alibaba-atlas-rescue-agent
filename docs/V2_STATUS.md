# V2 Qwen-Agent Migration — Final Status

**Branch:** `v2/qwen-agent-migration`
**Date:** 2026-08-31
**Main intact at:** `c6e7a4e` (verified — zero drift)

---

## Phase Completion Summary

| Phase | Description | Commit | Status |
|-------|-------------|--------|--------|
| G0 | Baseline, Branch & Learnings Log | `e45668b` | ✅ COMPLETE |
| P1 | Provider Fallback + Feature Flag | `11f2c6b` | ✅ COMPLETE |
| P2 | Conversation Layer Swap | `1328d99` | ✅ COMPLETE |
| P3 | Skills Wave 1 (Flight, Visa, Rights, Safety, Concierge) | `ee4095a` | ✅ COMPLETE |
| P4 | Skills Wave 2 (All Remaining 11 Skills + Engines) | `106efd8` | ✅ COMPLETE |
| P5 | Integrity & Close | *(this commit)* | ✅ COMPLETE |

---

## Gate Evidence Table

### Full Test Suite (dual-flag)

| Flag | Tests | Duration | Result |
|------|-------|----------|--------|
| `TRAVELCARE_BRAIN=legacy` | 574 passed | 220s | ✅ GREEN |
| `TRAVELCARE_BRAIN=qwen_agent` | 574 passed | 361s | ✅ GREEN |

### Browser Canary (dual-flag)

| Flag | Checks | Result |
|------|--------|--------|
| `TRAVELCARE_BRAIN=legacy` | 14/14 | ✅ PASS |
| `TRAVELCARE_BRAIN=qwen_agent` | 14/14 | ✅ PASS |

### Security Gate

| Check | Result |
|-------|--------|
| Banned secret patterns (tracked tree) | ✅ Zero hits |
| Forbidden files (.env, profiles, screenshots) | ✅ Not tracked |
| Pre-commit hook installed + staged scan | ✅ Clean |
| XSS sink audit (all frontend JS) | ✅ Zero sinks |
| Pydantic boundary/privacy suite | ✅ 33/33 passed |
| pip-audit dependency scan | ✅ No vulnerabilities |

### Secrets Sweep

| Check | Result |
|-------|--------|
| `git grep -nE -f scripts/banned_secret_patterns.txt` | ✅ Zero hits |
| `.env` files tracked | ✅ None (only `.env.example` with placeholders) |
| Key values in `docs/V2_LEARNINGS.md` | ✅ None found |

### Honesty-Label Spot Check (3 calls under `qwen_agent` flag)

| Surface | Label Observed | Result |
|---------|---------------|--------|
| Flight search offers | `bookable: false`, `price_status: reference` | ✅ Sandbox-labeled |
| Disruption analysis | `allow_sim=true` simulated mode | ✅ Simulation-labeled |
| Concierge (deterministic fallback) | `NO_ACTIVE_SESSION` deterministic reply | ✅ Degraded-labeled |

### Static Freeze

| Check | Result |
|-------|--------|
| `git diff main -- static/` | ✅ Empty (byte-identical to main) |

---

## Provider State

- **ModelScope**: Free quota exhausted (HTTP 429 since 2026-08-31). `.ai`-region endpoint only.
- **OpenRouter**: Active fallback provider. Model: `qwen/qwen3-235b-a22b-2507`.
- **Fallback chain**: ModelScope → OpenRouter. Structured warning on failover, no key exposure.
- **Legacy `services/llm.py`**: Untouched, defaults to `.cn` endpoint. Functional under `TRAVELCARE_BRAIN=legacy`.

---

## Architecture Summary

The migration implements a **strangler-fig pattern**: both `legacy` and `qwen_agent` brains coexist behind the `TRAVELCARE_BRAIN` environment variable flag. All 17 Qwen-Agent tools wrap existing deterministic skills/engines without replacing them. The LLM never computes visa outcomes, rights amounts, safety verdicts, radar detections, or Atlas data — tool-wrap only.

### Tool Registry (17 tools total)

**Wave 0 (P2):** `GoalIntakeTool`, `ClarifyLoopTool`
**Wave 1 (P3):** `FlightSearchTool`, `VisaCheckTool`, `RightsCheckTool`, `SafetyCheckTool`
**Wave 2 (P4):** `LocationResolveTool`, `ItineraryTool`, `FlightBookTool`, `RecoveryPlanTool`, `DisruptionMonitorTool`, `GuardianPushTool`, `ProfileCaptureTool`, `ProfileEditTool`, `WebIntelTool`, `RadarScanTool`, `ResearchBriefTool`

---

## Remaining Risks & Open Questions

1. **ModelScope quota**: Currently exhausted. Owner may need to top up or confirm OpenRouter as the permanent provider.
2. **Live LLM quality**: All tests use mocked LLM responses. Real Qwen3 responses under `qwen_agent` flag have not been evaluated for conversation quality or tool-calling accuracy at scale.
3. **Concurrency under load**: `asyncio.to_thread` bridging for sync Qwen-Agent tools has not been load-tested.
4. **Merge readiness**: The v2 branch is ready for owner review but NOT merged. Owner should review the diff, run a manual walkthrough, and decide on merge timing.

---

## Safety Confirmations

- ✅ `main` untouched at `c6e7a4e`
- ✅ Nothing pushed to any remote
- ✅ Nothing merged
- ✅ No deployment performed
- ✅ No payments processed
- ✅ `examples/qwen_agent_demo/` intact and untracked
- ✅ `static/` byte-frozen (zero diff vs main)
- ✅ No secrets committed, logged, or echoed
- ✅ Ticketing still not activated — all Atlas interactions are Sandbox with `bookable: false`
