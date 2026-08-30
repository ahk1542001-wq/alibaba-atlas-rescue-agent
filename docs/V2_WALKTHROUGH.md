# V2 Walkthrough — TravelCare Qwen-Agent Brain (`v2/qwen-agent-migration`)

Derived from the §14 final handoff report of the V2 migration and refreshed
during the audit fix round (2026-08-31). This document walks a reviewer
through what V2 is, how to run it, what the evidence trail shows, and the
disclosed deviations.

---

## 1. What V2 is

V2 grafts a **Qwen-Agent brain** onto TravelCare using the strangler-fig
pattern: both brains coexist behind the `TRAVELCARE_BRAIN` flag
(`legacy` default, `qwen_agent` experimental). At any commit on this
branch, `TRAVELCARE_BRAIN=legacy` reproduces the submitted product exactly
(except the ONE disclosed UX string — §5b). The LLM never computes
deterministic facts: visa outcomes, rights amounts, safety verdicts, radar
detections, and Atlas data always come from the same deterministic engines
as legacy — V2 only adds tool wrappers (§4.4 of the migration package).

Key seams:

| Seam | File | Role |
|------|------|------|
| Brain flag | `services/brain.py`, `config.py` | `active_brain()` / `is_qwen_brain()`; env re-read is intentional (audit #14) |
| Provider layer | `services/llm_providers.py` | ModelScope → OpenRouter fallback; 5-min health TTL; consistent unhealthy classification; honest `active_provider()` |
| Agent factory | `services/qwen_brain/agent.py` | `build_travelcare_agent()`; runs off the FastAPI event loop (audit #7) |
| Conversation | `services/qwen_brain/conversation.py` | §13.3 contracts: `goal_intake(text) → {status, trip_goal, missing_fields}`; `clarify_loop({trip_goal, profile}) → {status, clarify:{questions:[ONE]}}` |
| Tools | `services/qwen_brain/tools/` | 17 registered tools wrapping the legacy skills/engines |

## 2. Run it

```bash
.venv/bin/pip install -r requirements.txt -r requirements-v2.txt   # V2 dep set
cp .env.example .env                                               # TRAVELCARE_BRAIN=legacy by default
# enable the qwen brain + at least one provider key, then:
TRAVELCARE_BRAIN=qwen_agent .venv/bin/python main.py
```

If `TRAVELCARE_BRAIN=qwen_agent` but the qwen-agent package is absent, the
app serves a **labeled legacy fallback** (`brain_fallback: legacy_fallback`
in concierge responses; `brain: legacy_fallback` in the goal_intake trace
record) — never a raw 500 (audit #9).

## 3. Verification gates (deterministic, hermetic)

| Gate | File | Proves |
|------|------|--------|
| §13.3 contracts | `tests/test_v2_contracts.py` | param/return shapes; single next question |
| §8.4 parity matrix | `tests/test_v2_conversation_parity.py` | 12 scripted goals: identical TripGoal fields, missing_fields, ONE next question, PII-forbidden-field compliance vs legacy; malformed-LLM → labeled fallback |
| §9.4 wave-1 gates | `tests/test_v2_tools_wave1.py` | 5 inputs × 4 tools: `tool.call(...)` EQUAL to legacy skill/engine on deterministic fields; 20 mocked-Assistant selection phrasings; do_not_travel propagation |
| §10.2 wave-2 gates | `tests/test_v2_tools_wave2.py` | server-side approval authority (approved + rejected paths); radar_scan EQUAL to direct `RescueRadar.scan`; registry derived programmatically from skill manifests |
| Event loop | `tests/test_v2_event_loop.py` | agent build + tool calls execute off the request loop thread |
| Provider health | `tests/test_v2_llm_providers.py` | TTL expiry/re-probe; 429/401/5xx/timeout classification on both paths |
| Deferred import | `tests/test_v2_deferred_import.py` | absent package → labeled legacy fallback, not 500 |
| Dual-brain flag | `tests/test_v2_brain_flag.py` | flag semantics + `.env.example` declarations |

## 4. Live evidence (bounded model calls; keys redacted)

Full redacted transcripts: `docs/V2_LEARNINGS.md` ("Audit fix round:
re-run live-smoke excerpts (P1–P4)"). Highlights:

- **P1** provider resolution served by OpenRouter (`served_by=openrouter`)
  while ModelScope probes 429 (free quota exhausted — account quota, not
  transient).
- **P2** live `goal_intake` round honoring the §13.3 contract shape.
- **P3** model-driven `flight_search` + `visa_check`; sandbox provenance
  labels (`atlas_sandbox`, "sandbox, not bookable") surfaced verbatim.
- **P4** `radar_scan` surfacing the real watchlist rows (this gate also
  caught and fixed the `results→flights` key bug).
- **P5 spot check re-run** (`docs/V2_STATUS.md`): sandbox-labeled flight,
  simulated guardian preview ("Simulated: …"), degraded-provider flow with
  both keys unset (`resolve → None`, `active_provider → none`, labeled
  fallback). No fabrication anywhere.

## 5. Disclosed deviations & baseline honesty

The audit found that G0 commit `e45668b` smuggled three changes. History
was repaired FORWARD (no rewrites) with labeled commits:

a. **Stale app.js pin repair** — `62c7a59 fix(tests): repair stale app.js
   pin (main baseline was red)`. The pin on `main` targeted an app.js that
   last changed in `c21ec1e`; the main baseline was red without repair.
b. **Legacy concierge UX string** — `aad5247` (forward revert) then
   `9c65bf3 fix(ux): friendly destination city names (owner-visible legacy
   drift, disclosed)`. This string is LOAD-BEARING for the green baseline:
   `test_AJ03c` expects "Singapore" but the legacy engine replies "SIN".
   Legacy byte-parity with the submitted state is intentionally relaxed
   ONLY by this disclosed UX string.
c. **Canary assertions** — `16a64fd fix(tests): restore strict fail-closed
   canary assertions`. The actual BKK-RGN `allow_sim` outcome was
   determined by running the flow (200 with `best=null` and the
   no-mandatory-regime verdict); both outcomes are explicit test cases and
   the 422 fail-closed provider-route assertion stays strict.

**Corrected baseline claim**: at `c6e7a4e` with the pin repair ONLY, the
suite is `1 failed, 534 passed`. The previously stated "535 passed at
c6e7a4e" required BOTH disclosed repairs (pin + UX string).

### Prior doc-commit scope deviations (transparency note, audit #13/#15)

During the original migration, some phase commits carried docs outside
their strict code scope: `1328d99 (P2)` also touched
`docs/V2_UX_ENHANCEMENTS.md` and `config.py` documentation surfaces, and
phase commits P2–P4 bundled `docs/V2_LEARNINGS.md` entries with code
(expected per §14 item 4, but worth stating). The migration was 6 commits
(G0 + P1–P5), a count corrected in `docs/V2_LEARNINGS.md` after an earlier
"5 commits" miscount.

## 6. Confirmation statements (per §14)

- `main` untouched at `c6e7a4e`; nothing pushed; nothing merged.
- No deployment; no payments; no real bookings — Atlas stays Sandbox via
  the authenticated CLI bridge.
- `examples/qwen_agent_demo/` intact; `static/` byte-frozen vs main.
- No secrets committed; `.env` untracked; `.env.example` placeholders only.
- Ticketing capability remains not activated.

---

*See also: `docs/V2_STATUS.md` (fix-round table finding → fix → evidence),
`docs/V2_LEARNINGS.md` (chronological evidence),
`docs/V2_QWEN_AGENT_MIGRATION_PACKAGE.md` (the §1–§15 spec).*
