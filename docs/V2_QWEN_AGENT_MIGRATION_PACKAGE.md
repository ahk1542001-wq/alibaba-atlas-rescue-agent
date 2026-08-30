# V2 Qwen-Agent Migration Package — TravelCare AI Brain Swap (One-Shot Execution)

> **Paste this entire document into one Antigravity agent session as the single authoritative execution command.**
> Target repo: `/Users/mac/Projects/code/alibaba-atlas-rescue-agent` (start from branch `main` @ `c6e7a4e`)
> Working branch: `v2/qwen-agent-migration` (you create it; NEVER merge it back without owner approval)
> The owner is AWAY while you execute. This document is fully self-contained: if something is not written here, it is out of scope. Do not guess, do not improvise, do not wait for a human except at the explicit STOP points in §2.

---

## 0. HOW TO EXECUTE THIS MIGRATION (READ FIRST)

You are performing one autonomous, phased migration. Follow sections in order: G0 (baseline + branch) → P1 → P2 → P3 → P4 → P5. Each phase has RED→GREEN gates; a phase is done only when its gate evidence exists. Never proceed to the next phase on a red gate.

Rules of engagement:
1. **Strangler-fig, flag-gated.** The legacy orchestration brain stays fully functional behind `TRAVELCARE_BRAIN=legacy` at all times. The new Qwen-Agent brain grows beside it behind `TRAVELCARE_BRAIN=qwen_agent`. Nothing is deleted until P5, and even then only when both brains are green.
2. **CREDIT-SAFETY COMMITS:** immediately after EACH phase gate passes, commit the reviewed working state on `v2/qwen-agent-migration` with message `v2(P#): <summary>`. Use exact-path `git add <paths>` only; NEVER `git add -A` or `git add .`; NEVER stage `.env`, `examples/`, screenshots, or anything untracked that is not listed in the phase's file scope.
3. **TDD:** write the failing test first for every behavior; run tests after every small unit.
4. **Never weaken a test to pass a gate.** No deletions, no skips, no loosened assertions, no `xfail` escapes. If a legacy test fails, your change is wrong — fix the change.
5. **Fail-closed everywhere.** Any provider error yields an honest, labeled degraded response — never fabricated data.
6. **Secrets:** never commit, print, log, or embed key values. Env var NAMES only, everywhere.
7. On any gate failure follow the self-learning loop in §12 exactly (max 3 correction cycles, then STOP + blocker note).
8. This document does not bypass any permission control. Repository-scoped reads/edits, local Python/Playwright commands, and localhost:8050 only.

---

## 1. CONTEXT — WHAT THIS PRODUCT IS AND WHY V2

**Product.** TravelCare AI is an autonomous flight-disruption recovery agent: it plans trips, watches flights, ranks rescue packages, rebooks through the Atlas Sandbox, and drafts air-passenger-rights claims. It is a FastAPI app with a single-page static UI ("one brain, five views").

**Current state.** The hackathon submission is DONE and the public repo is under active judging. The submitted state on `main` @ `c6e7a4e` must remain intact: 535 hermetic pytest tests green, browser E2E canary 14/14, security gate green. The v2 work exists ONLY on the separate branch you create.

**Why v2.** The v1 "brain" is hand-rolled orchestration: `services/conversation_controller.py` (deterministic turn projection), `services/trip_graph.py` (task DAG), `services/research_coordinator.py`. It works but is rigid. v2 replaces the conversation/intent/tool-selection layer with the **Qwen-Agent framework** (Qwen3-235B-driven `Assistant` with tool calling) for flexibility, while every deterministic honesty engine stays deterministic and is merely wrapped as a tool.

**Owner-verified decisions (constraints, not suggestions):**
1. Incremental strangler-fig migration behind runtime flag `TRAVELCARE_BRAIN=legacy|qwen_agent`; one phase at a time, each verified before the next; end state covers ALL 13 skills.
2. Branch `v2/qwen-agent-migration` from `main` @ `c6e7a4e`; never touch/merge/push main without owner approval; no push at all; public submitted state stays intact.
3. Provider strategy: ModelScope primary (model `Qwen/Qwen3-235B-A22B-Instruct-2507`, endpoint `https://api-inference.modelscope.ai/v1`, env `ALIBABA_MODEL_API_KEY`) with automatic OpenRouter fallback (model `qwen/qwen3-235b-a22b-2507`, env `OPENROUTER_API_KEY`). Provider attribution must stay visible in responses/telemetry. **ModelScope free quota was exhausted on 2026-08-31 (HTTP 429) — the fallback is not optional; expect it to be the active provider.**
4. Hybrid rule: Qwen-Agent owns conversation/intent/tool-selection ONLY. `visa_guard.py`, `rights_engine.py`, `radar.py`, the safety adapters, and Atlas provider-truth logic are NEVER delegated to LLM judgment — they are wrapped as Qwen-Agent tools only.
5. Architectural honesty is non-negotiable: explicit simulation labeling, every number from live tooling, fail-closed on provider error, ticketing remains not-activated (`TICKETING_ACTIVATION_REQUIRED`), no real booking/payment.
6. No secrets committed/printed; Python `.venv` (3.14.7) already has `qwen-agent` 0.0.34 + deps; repo imports are namespace packages resolved from repo root.

**Definition of Done (whole migration, single sentence):** the hand-rolled orchestration brain is swappable for Qwen-Agent behind `TRAVELCARE_BRAIN`, while every existing test, canary, security gate, and honesty invariant stays green under BOTH flag values.

---

## 2. OWNER-ABSENT PROTOCOL

The owner is away. You are authorized to work autonomously ONLY inside the boundaries below.

**You MAY do without approval:**
- Create branch `v2/qwen-agent-migration` from `main` @ `c6e7a4e` and commit on it (exact-path adds only).
- Create/edit files inside the per-phase file scope (§7.7 and each phase section).
- Run the app locally on port 8050, run the full pytest suite, run the Playwright browser canary, run `scripts/security_check.sh`, run the qwen-agent demo script.
- Make the LLM/API calls needed for gates and parity/e2e proof, using keys already present in the local `.env`: ModelScope if its quota recovers, otherwise OpenRouter with the existing key. **Reasonable-usage guardrail:** keep model-driven verification BOUNDED — a handful of calls per gate (rule of thumb: ≤5 per live smoke); never bulk/looped mass calls; prefer deterministic/mocked tests everywhere possible and reserve real model calls for parity proof and end-to-end smoke only.
- Call the Atlas Sandbox ONLY through the authenticated `atlas-flight` CLI bridge (same as the product does).
- Create and maintain `docs/V2_LEARNINGS.md` and `docs/V2_STATUS.md`.

**You MUST STOP and wait for owner approval, even if everything is green:**
- Merging `v2/qwen-agent-migration` into `main` (any direction, any method).
- Any `git push`, remote operation, branch publication, or history rewrite.
- Any deployment, release, or publication of any kind.
- Paying for anything, topping up any quota, or signing up for any service/account.
- Changing public repo settings or any published repo metadata.
- Any external side effect beyond the local runs and bounded API calls listed above (no emails, no Telegram sends to new targets, no webhooks).

**When stopped:** write the complete current state to `docs/V2_STATUS.md` (phase reached, gate evidence, what is blocked, exact question for the owner, remaining plan), commit it on the v2 branch, and end the session cleanly. Never guess the owner's answer. Never convert a STOP item into a "small exception".

---

## 3. ENVIRONMENT (verified facts — do not re-litigate)

- **Python:** `.venv` at repo root, Python 3.14.7. Always use `.venv/bin/python`.
- **qwen-agent:** 0.0.34 already installed in `.venv` with its undeclared import deps present (numpy, soundfile, tqdm, jieba, python-dateutil). Do NOT add qwen-agent to `requirements.txt` (the submitted dependency manifest must not change); the qwen brain module imports lazily behind the flag.
- **atlas-flight CLI:** installed at `/Users/mac/.local/bin/atlas-flight`; `atlas-flight auth status` → "Authorization active". This is the ONLY source of Atlas flight truth.
- **App:** FastAPI on port 8050 (`PORT` env), started with `.venv/bin/python main.py`.
- **ModelScope quota caveat:** as of 2026-08-31 the ModelScope free quota returns HTTP 429. Your provider layer MUST automatically fall back to OpenRouter on any ModelScope HTTP error and MUST record which provider actually served the call. If both providers fail, the product degrades honestly (deterministic fallbacks, labeled); it never fabricates. Do NOT attempt to buy quota or create new accounts — that is a STOP item (§2).
- **Tests:** 535 pytest tests collected at baseline (`--collect-only`). Fully hermetic — no network in the suite; qwen-agent-brain unit tests must mock the LLM/provider boundary. Real model calls happen only in the bounded live-smoke gates (§2 guardrail).
- **ModelScope endpoint region gotcha:** only `api-inference.modelscope.ai` works with this key; `.cn` returns 401. The legacy product default in `services/llm.py` is the `.cn` URL — do not "fix" legacy behavior; the new provider layer uses `.ai`.

---

## 4. ARCHITECTURE & FILE MAP

### 4.1 Repo layout
```
main.py                    # FastAPI app factory; mounts static/, registers routers/v1/*
config.py                  # pydantic Settings, env-only (THIS IS WHERE THE FLAG GOES)
models/schemas.py          # all pydantic contracts
services/
  llm.py                   # legacy raw LLM client (OpenAI-compatible httpx)
  conversation_controller.py  # v1 deterministic turn projection (P2 swap target)
  trip_graph.py            # v1 task DAG orchestrator
  research_coordinator.py  # v1 research pipeline
  rescue_engine.py         # rescue ranking + concierge answering (uses llm.py)
  atlas_client.py          # Atlas Sandbox bridge via atlas-flight CLI (provider truth)
  visa_guard.py            # DETERMINISTIC visa rules (never LLM)
  rights_engine.py         # DETERMINISTIC entitlement math (never LLM)
  radar.py                 # DETERMINISTIC background watch loop (never LLM)
  guardian.py              # Telegram push (token-gated; demo mode when unset)
  readiness.py, state_graph.py, profile_store.py, web_intel_client.py
  safety/                  # adapters.py + policy.py — DETERMINISTIC safety adapters
  skills/                  # 13 public skills + 1 internal, each <name>.py + <name>.SKILL.md
routers/v1/                # trip.py (orchestrator router), concierge.py, flights.py,
                           # disruptions.py, bookings.py, claims.py, radar.py, hotels.py,
                           # profile.py, skills.py, telemetry.py
static/                    # UI: index.html (5 views), trip.js, app.js, styles.css — FROZEN
tests/                     # 535 hermetic tests; e2e_full_journey.py = 14-step browser canary
scripts/security_check.sh  # 6-section security gate
examples/qwen_agent_demo/  # proven Qwen-Agent demo (UNTRACKED — keep intact, never commit)
docs/                      # MASTER_BUILD_PACKAGE.md (style ref); V2 docs land here
```

### 4.2 The 5 UI views (FROZEN — `static/` must stay byte-identical through all phases)
Trip (`view-trip`) · Search (`view-search`) · Concierge (`view-concierge`) · Radar (`view-radar`) · Rescue (`view-rescue`). The canary `tests/e2e_full_journey.py` pins their selectors; the UI must work unchanged with either brain because the API response contracts do not change.

### 4.3 The 13 public skills (`services/skills/`, each has `<name>.py` + `<name>.SKILL.md`)
| # | Skill | Wave |
|---|---|---|
| 1 | `goal_intake` | P2 (conversation layer) |
| 2 | `flight_search` | P3 |
| 3 | `visa_check` | P3 |
| 4 | `rights_check` | P3 |
| 5 | `location_resolve` | P4 |
| 6 | `itinerary` | P4 |
| 7 | `flight_book` | P4 |
| 8 | `recovery_plan` | P4 |
| 9 | `disruption_monitor` | P4 |
| 10 | `guardian_push` | P4 |
| 11 | `profile_capture` | P4 |
| 12 | `profile_edit` | P4 |
| 13 | `web_intel` | P4 |

Internal (validated but not public): `clarify_loop` — migrated in P2 with the conversation layer. Safety manifests `services/safety/safety_monitor.SKILL.md` / `safety_research.SKILL.md` belong to the deterministic safety adapters, wrapped in P3 as one `safety_check` tool. Non-skill deterministic engines wrapped as tools in P4: `radar` (`services/radar.py`) and research (`services/research_coordinator.py`).

### 4.4 Deterministic engines — NEVER delegated to LLM judgment (tool-wrap only)
`services/visa_guard.py` · `services/rights_engine.py` · `services/radar.py` · `services/safety/*` · `services/atlas_client.py` (Atlas provider truth) · ticketing boundary (remains not-activated).

### 4.5 Env var NAMES used by this migration (values live only in untracked `.env`; never print them)
| Name | Role |
|---|---|
| `TRAVELCARE_BRAIN` | `legacy` (default) or `qwen_agent` — the strangler-fig switch |
| `ALIBABA_MODEL_API_KEY` | ModelScope primary key (existing) |
| `OPENROUTER_API_KEY` | OpenRouter fallback key (new; already used by the demo) |
| `LLM_BASE_URL` | Optional endpoint override (existing) |
| `DEFAULT_MODEL` | Legacy-path model name (existing; do not change default) |
| `PORT`, `HOST` | App bind (existing) |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_LIVE_TEST` | Guardian gating (existing; unchanged) |

---

## 5. RUNBOOK (exact commands, from repo root `/Users/mac/Projects/code/alibaba-atlas-rescue-agent`)

```bash
cd /Users/mac/Projects/code/alibaba-atlas-rescue-agent

# Sanity: interpreter + qwen-agent + Atlas auth
.venv/bin/python --version                       # expect Python 3.14.7
.venv/bin/python -c "import qwen_agent"           # expect no output (0.0.34 installed)
atlas-flight auth status                          # expect: Authorization active

# Boot the app (foreground; or background it for canary runs)
.venv/bin/python main.py                          # → http://localhost:8050

# Full hermetic test suite (expect 535 passed at baseline)
TZ=UTC .venv/bin/python -m pytest -q

# Test collection count only
.venv/bin/python -m pytest --collect-only -q | tail -1

# Browser E2E canary (app must be running on :8050 first; expect 14/14 PASS)
.venv/bin/python tests/e2e_full_journey.py

# Security gate (secret scan, tracked-file rules, hook, XSS sinks, privacy suite, deps)
bash scripts/security_check.sh

# Proven Qwen-Agent demo (read-only use of product code; prints provider/model, NEVER the key)
.venv/bin/python examples/qwen_agent_demo/demo_qwen_agent.py
.venv/bin/python examples/qwen_agent_demo/smoke_test_llm.py

# Run app under the new brain (after P1 exists)
TRAVELCARE_BRAIN=qwen_agent .venv/bin/python main.py
```

---

## 6. G0 — GOAL, BASELINE, BRANCH

**Goal (single sentence):** swap the hand-rolled orchestration brain for Qwen-Agent behind `TRAVELCARE_BRAIN` while every existing test and honesty invariant stays green.

**Non-goals:** no UI changes; no API contract changes; no main-branch changes; no push/deploy; no new external services; no real booking/payment; no ticketing activation.

**G0 steps (execute exactly, record evidence):**
1. `git status --porcelain` → must show only the known untracked items (`examples/` and similar). If tracked files are modified or staged, STOP and write `docs/V2_STATUS.md`.
2. `git log --oneline -1` → must be `c6e7a4e docs(readme): remove hackathon metadata and stale demo storyboard`. Any other HEAD: STOP + status note.
3. `git switch -c v2/qwen-agent-migration` (from that exact commit).
4. Run the FULL baseline: `TZ=UTC .venv/bin/python -m pytest -q` → 535 passed. Any failure BEFORE you changed anything: STOP + status note (do not migrate on a red baseline).
5. Boot the app, run `.venv/bin/python tests/e2e_full_journey.py` → 14/14. Shut the app down.
6. Run `bash scripts/security_check.sh` → all sections pass.
7. Create `docs/V2_LEARNINGS.md` with the header "V2 Migration Learnings Log" and one seed entry: "ModelScope free quota exhausted 2026-08-31 (HTTP 429); OpenRouter fallback is the expected live provider."
8. Commit: `git add docs/V2_LEARNINGS.md && git commit -m "v2(G0): baseline evidence + learnings log"`.

**G0 gate evidence:** branch name + HEAD commit, pytest summary line, canary 14/14 line, security gate summary line — all recorded in your phase report (§14).

---

## 7. P1 — PROVIDER FALLBACK LAYER + FEATURE FLAG SCAFFOLDING

**Intent:** build the dual-provider layer and the brain switch without changing any observable legacy behavior.

### 7.1 New file `services/llm_providers.py`
- Resolve provider chain: ModelScope primary → OpenRouter fallback.
  - ModelScope: base URL `https://api-inference.modelscope.ai/v1` (note `.ai`, NOT the legacy `.cn`), model `Qwen/Qwen3-235B-A22B-Instruct-2507`, key from `ALIBABA_MODEL_API_KEY`. Honor `LLM_BASE_URL` override if set.
  - OpenRouter: base URL `https://openrouter.ai/api/v1`, model `qwen/qwen3-235b-a22b-2507`, key from `OPENROUTER_API_KEY`.
- Skip any provider whose key is missing/empty/placeholder (starts with `your_`).
- Expose:
  - `resolve_llm_cfg() -> dict | None` — a Qwen-Agent-ready `llm_cfg` for the first HEALTHY provider (shape in §13.1), or `None` when none available.
  - `chat_with_fallback(messages, ...) -> tuple[str | None, str | None]` — try primary; on ANY HTTP/auth/quota error (401, 429, 5xx, timeout) try fallback; return `(content, provider_name)` or `(None, None)`. Never raise; never log key values.
  - `active_provider() -> str` — `"modelscope" | "openrouter" | "none"` for telemetry attribution.
  - `last_provider_outcome() -> dict` — machine-readable record `{primary: "ok|http_429|...", fallback: "ok|skipped|...", served_by: ...}` for telemetry surfaces.
- Health probe (cheap, used at brain init): a minimal completions call with `max_tokens=1` is acceptable; cache the result per process; a 429 from ModelScope permanently marks it unhealthy for the process lifetime. Bounded usage: at most ONE probe per process boot.

### 7.2 Flag in `config.py`
Add exactly: `travelcare_brain: str = os.getenv("TRAVELCARE_BRAIN", "legacy").strip().lower()` and validate it is one of `legacy|qwen_agent` at boot; unknown value → log a warning and coerce to `legacy` (fail-safe, never crash the app).

### 7.3 New file `services/brain.py`
- `def active_brain() -> str` — returns `settings.travelcare_brain`.
- `def is_qwen_brain() -> bool`.
- This module is the ONLY place callers check the flag.

### 7.4 New file `tests/test_v2_providers.py` (hermetic — mock httpx; zero network)
RED first. Cover: ModelScope success → no fallback called; ModelScope 429 → OpenRouter called and result tagged `openrouter`; both fail → `(None, None)` and honest outcome record; missing key skips provider; placeholder key skipped; no key value appears in any log record (capture logs and assert); `resolve_llm_cfg()` shape matches §13.1 and contains NO `stream` key.

### 7.5 New file `tests/test_v2_brain_flag.py`
Default is `legacy`; `TRAVELCARE_BRAIN=qwen_agent` selects qwen brain; garbage value coerces to `legacy` without raising.

### 7.6 `services/llm.py` boundary
Do NOT change legacy behavior. You may add a comment marking it "legacy brain raw LLM client — v2 uses services/llm_providers.py". Nothing else in this file changes.

### 7.7 P1 file scope (touch ONLY these)
`config.py`, `services/brain.py` (new), `services/llm_providers.py` (new), `services/llm.py` (comment only), `tests/test_v2_providers.py` (new), `tests/test_v2_brain_flag.py` (new), `docs/V2_LEARNINGS.md`.

**P1 gates:**
- RED: new tests fail before implementation.
- GREEN-1: `tests/test_v2_providers.py` + `tests/test_v2_brain_flag.py` green.
- GREEN-2: `TZ=UTC .venv/bin/python -m pytest -q` → 535 legacy + new, all green.
- GREEN-3: boot with default env → app behaves exactly as baseline (smoke: `GET /` returns the UI; one deterministic endpoint such as the skills listing responds). Boot with `TRAVELCARE_BRAIN=qwen_agent` → app still boots cleanly (brain wiring may still delegate to legacy paths; it must not crash).
- GREEN-4 (bounded live probe, ≤2 model calls): run `examples/qwen_agent_demo/smoke_test_llm.py` to confirm the fallback chain reaches a live provider (expect `openrouter` while ModelScope quota is exhausted); record provider attribution in the phase report. If both providers are down, record it in `docs/V2_LEARNINGS.md` and proceed — degraded mode is the honest path, never fabrication.
- Commit: `v2(P1): provider fallback layer + TRAVELCARE_BRAIN flag scaffolding`.

---

## 8. P2 — CONVERSATION LAYER SWAP (goal intake + clarification)

**Intent:** under `TRAVELCARE_BRAIN=qwen_agent`, a Qwen-Agent `Assistant` replaces the legacy routing for free-text goal intake and clarification, producing the SAME structured contracts the rest of the pipeline already consumes.

### 8.1 New package `services/qwen_brain/`
- `__init__.py`, `agent.py`, `tools/conversation.py`.
- `agent.py`: build the `Assistant` exactly per the proven demo pattern (`examples/qwen_agent_demo/demo_qwen_agent.py` is the reference implementation — same `llm_cfg` shape, same `bot.run(messages=..., stream=False)` consumption). System message: TravelCare concierge persona + hard honesty rules (never invent flight/visa/rights data; always call the right tool; label suggestions; report provenance). Build lazily on first use, cache per process; if `resolve_llm_cfg()` is `None`, the qwen brain reports itself unavailable and the caller falls back to the legacy controller for this request (logged, labeled, honest).
- Async bridging: tool `call()` is sync. Outside a running loop use `asyncio.run`; inside FastAPI's running loop run the sync tool in a thread executor (`asyncio.to_thread` from the caller, or `loop.run_in_executor` with a `ThreadPoolExecutor`) — NEVER call `asyncio.run` from inside a running loop.

### 8.2 Tools for this phase (contracts in §13)
- `goal_intake` — wraps `services/skills/goal_intake.py`: parse free-text into the existing TripGoal contract fields; missing fields returned as `missing_fields`.
- `clarify_loop` — wraps `services/skills/clarify_loop.py` + profile knowledge: given TripGoal + profile, return the NEXT single clarification question (one question max, matching legacy `QUESTION_FIELD_ORDER` semantics in `services/conversation_controller.py`) or `complete: true`.
- Both tools: description text sourced from their `SKILL.md` frontmatter `description` (read at import via the existing loader; do not hand-copy drift-prone strings); `call()` returns a JSON string; never raises (error JSON per §13.3).

### 8.3 Integration seam
In `routers/v1/trip.py` at the single point where the legacy conversation controller produces the goal-intake/clarification turn, add the branch: `if is_qwen_brain() and qwen brain available → qwen path else legacy path`. Response schema (`ConversationTurn`/related contracts in `models/schemas.py`) must be IDENTICAL in shape across both paths. Legacy path code stays untouched.

### 8.4 Parity tests — `tests/test_v2_conversation_parity.py` (mock LLM; hermetic)
RED first. Scripted goal list (minimum 10): complete goal; missing destination; missing dates; multi-airport origin ("Bangkok"); passport missing; goal with venue instead of city ("Marina Bay Sands"); non-English phrasing; over-detailed rambling goal; goal contradicting profile; empty/garbage input. For each:
1. Legacy path produces its turn; qwen path (LLM mocked to return canned tool calls) produces its turn.
2. Assert SAME structured fields: extracted TripGoal fields, `missing_fields` set, next-question field identity (e.g. both ask `dest_city` next), confirmation requirements (BKK/DMK ambiguity flagged in both), and safety/PII rules (never asks forbidden fields — reuse `FORBIDDEN_PII_FIELDS` from `services/conversation_controller.py`).
3. Malformed LLM output → qwen path falls back to legacy controller for that turn, labeled; no crash, no fabricated field.

### 8.5 P2 file scope
`services/qwen_brain/**` (new), `routers/v1/trip.py` (single seam), `tests/test_v2_conversation_parity.py` (new), `docs/V2_LEARNINGS.md`.

**P2 gates:**
- RED: parity tests fail before implementation.
- GREEN-1: parity suite green (all scripted goals, both paths) — mocked, zero network.
- GREEN-2: full pytest green under `TRAVELCARE_BRAIN=legacy` AND under `TRAVELCARE_BRAIN=qwen_agent` (run the whole suite twice; record both summary lines).
- GREEN-3 (bounded live smoke, ≤3 model calls): boot with `TRAVELCARE_BRAIN=qwen_agent`, send ONE free-text goal through the trip chat endpoint, capture the response showing structured intake + provider attribution; record a redacted transcript excerpt in the phase report.
- Commit: `v2(P2): qwen-agent conversation layer behind TRAVELCARE_BRAIN`.

---

## 9. P3 — SKILLS MIGRATION WAVE 1

**Intent:** wrap the first skill set as Qwen-Agent tools. Every tool delegates 100% to existing deterministic/product code — the LLM only DECIDES WHEN to call them, never computes their content.

### 9.1 Wave-1 tools (new files under `services/qwen_brain/tools/`)
| Tool name | Wraps | Notes |
|---|---|---|
| `flight_search` | `services/skills/flight_search.py` + `services/atlas_client.py` | Async `AtlasClient.search_flights` — bridge per §8.1. Response MUST carry `source: "atlas_sandbox"` + provenance note (copy the demo pattern). Sandbox inventory only; never bookable. |
| `visa_check` | `services/skills/visa_check.py` + `services/visa_guard.py` | Deterministic rules only; LLM must pass through the engine's verdict verbatim. |
| `rights_check` | `services/skills/rights_check.py` + `services/rights_engine.py` | Entitlement math stays in the engine; NONE-regime fallback note preserved. |
| `safety_check` | `services/safety/adapters.py` + `services/safety/policy.py` | One tool combining safety_monitor + safety_research adapters; `do_not_travel` outcome must block downstream suggestions exactly as legacy. |
| Concierge chat | `routers/v1/concierge.py` seam | Under qwen flag, the `/api/chat/concierge` path routes free-text through the qwen `Assistant` (with trip context injected into the system/user message) instead of `rescue_engine.answer_concierge`'s LLM path; response keys stay identical (`reply`, `action_taken`, `trip_id`, …). Deterministic proposal logic (e.g. passenger-count regex proposals) stays AFTER the LLM answer, unchanged. |

### 9.2 Per-tool contract rules (all wave-1 and wave-2 tools)
1. Registered with `@register_tool("<name>")`, class extends `BaseTool`; `description` loaded from the matching `SKILL.md` frontmatter at import time (safety tools: concatenate both safety manifest descriptions); `parameters` list matches §13 exactly.
2. `call(self, params: str, **kwargs) -> str`: parse with `json5.loads`, validate/coerce at this boundary, delegate to product code, return ONE JSON string. NEVER raise — all exceptions become error JSON (§13.3). NEVER log or return key material.
3. Tool output passes through unchanged to the agent; the agent's natural-language rendering must preserve every number and label the tool returned (honesty rule: the system message forbids altering tool facts).

### 9.3 Tests — `tests/test_v2_tools_wave1.py` (hermetic; Atlas/provider boundaries mocked exactly as legacy suites do)
RED first. For each tool: happy path returns the deterministic engine's exact payload shape; bad params → error JSON, no exception; tool never mutates engine results (compare against direct engine call); flight_search result carries `atlas_sandbox` provenance; safety `do_not_travel` propagates.

### 9.4 Parity criteria per tool (gate definition)
For a fixed scripted input set (≥5 inputs per tool), `tool.call(json.dumps(input))` parsed-JSON equals the legacy skill/engine output on all deterministic fields. LLM involvement is limited to tool SELECTION, proven by a mocked-Assistant test asserting the right tool is requested for 5 scripted user phrasings per tool.

### 9.5 P3 file scope
`services/qwen_brain/tools/` (new wave-1 files + registry update), `services/qwen_brain/agent.py` (function_list extended), `routers/v1/concierge.py` (flag seam only), `tests/test_v2_tools_wave1.py` (new), `docs/V2_LEARNINGS.md`.

**P3 gates:**
- RED: wave-1 tool tests fail before implementation.
- GREEN-1: `tests/test_v2_tools_wave1.py` green + full pytest green under BOTH flag values (two runs, record both).
- GREEN-2 (bounded live smoke, ≤5 model calls): one scripted conversation per wave-1 capability (flight search on a future date, visa question, rights question) through the qwen brain; verify every number in the answers traces to a tool result and provider attribution is present; record redacted transcript excerpts.
- Commit: `v2(P3): skills wave 1 (flight_search, visa_check, rights_check, safety_check, concierge)`.

---

## 10. P4 — SKILLS MIGRATION WAVE 2 (all remaining skills + engines)

**Intent:** complete the 13-skill coverage and wrap the remaining deterministic engines.

### 10.1 Wave-2 tools
| Tool name | Wraps | Notes |
|---|---|---|
| `location_resolve` | `services/skills/location_resolve.py` | Multi-airport ambiguity (BKK/DMK) MUST emit confirmation requirement; agent must not pick silently. |
| `itinerary` | `services/skills/itinerary.py` | Provenance tagging per section preserved (Atlas Sandbox vs suggestion). |
| `flight_book` | `services/skills/flight_book.py` | Approval-gated: tool verifies the ApprovalGate state before any booking attempt; ticketing boundary stays fail-closed (`TICKETING_ACTIVATION_REQUIRED` when not activated). The LLM can NEVER approve on the user's behalf. |
| `recovery_plan` | `services/skills/recovery_plan.py` | Prepares alternatives only; immutable approval request; separate recovery approval preserved. |
| `disruption_monitor` | `services/skills/disruption_monitor.py` | Watches active PNR; triggers recovery flow. |
| `guardian_push` | `services/skills/guardian_push.py` + `services/guardian.py` | Token-gated demo mode EXACTLY as today: live send only when token + chat id + explicit live-test flag all set; otherwise redacted simulated preview labeled as such. |
| `profile_capture` | `services/skills/profile_capture.py` | Confirmation-before-save preserved; source tags (`user`/`ai_inferred`) preserved; forbidden PII fields rejected (same `FORBIDDEN_PII_FIELDS` vocabulary). |
| `profile_edit` | `services/skills/profile_edit.py` | Deletions respected. |
| `web_intel` | `services/skills/web_intel.py` | TTL cache + dated citations preserved; network failure → labeled degraded baseline, never invented citations. |
| `radar_scan` | `services/radar.py` | Deterministic scan logic untouched; tool exposes scan/accept actions; radar background loop itself stays legacy-owned. |
| `research_brief` | `services/research_coordinator.py` | Curated research snapshot; provenance labels preserved. |

### 10.2 Tests — `tests/test_v2_tools_wave2.py` (hermetic)
Same contract rules as §9.2–9.4. Extra mandatory cases: `flight_book` without approval returns refusal JSON (never books); `guardian_push` without full token trio returns labeled simulated preview; `radar_scan` output equals direct `services/radar.py` engine output; all 13 public skill names appear in the qwen brain's registered `function_list` (assert programmatically from the skill registry).

### 10.3 P4 file scope
`services/qwen_brain/tools/` (wave-2 files + registry), `services/qwen_brain/agent.py`, `tests/test_v2_tools_wave2.py` (new), `docs/V2_LEARNINGS.md`. Routers: ONLY if a wave-2 capability needs a flag seam, add it at the single existing handler for that capability; no new routes.

**P4 gates:**
- RED: wave-2 tests fail before implementation.
- GREEN-1: full pytest green under BOTH flag values.
- GREEN-2: registry assertion — all 13 public skills registered as qwen tools (test output as evidence).
- GREEN-3 (bounded live smoke, ≤5 model calls): one multi-turn rescue-style conversation exercising at least 3 wave-2 tools with approval gates respected; record redacted transcript.
- Commit: `v2(P4): skills wave 2 — full 13-skill qwen-agent coverage`.

---

## 11. P5 — INTEGRITY & CLOSE

Execute in order; every step must pass.

1. **Dual-flag full suite:** `TZ=UTC .venv/bin/python -m pytest -q` once with `TRAVELCARE_BRAIN=legacy`, once with `TRAVELCARE_BRAIN=qwen_agent`. Both green, both recorded.
2. **Browser canary under qwen flag:** boot app with `TRAVELCARE_BRAIN=qwen_agent`, run `.venv/bin/python tests/e2e_full_journey.py` → 14/14. Also run it once under legacy flag. Record both.
3. **Security gate:** `bash scripts/security_check.sh` → ALL SECTIONS PASS.
4. **Secrets sweep:** `git grep -nE -f scripts/banned_secret_patterns.txt` → zero hits; confirm `.env` and any demo-local env file are untracked (`git ls-files | grep -E '(^|/)\.env' | grep -v '^\.env\.example$'` → empty); confirm no key value appears in `docs/V2_LEARNINGS.md` or any phase report.
5. **Honesty-label spot check (≤3 model calls):** under qwen flag, trigger one sandbox-labeled flight result, one simulated/labeled guardian or demo flow, and one degraded-provider flow (simulate by unsetting keys in a throwaway env copy — never edit the real `.env`); verify every surface carries its explicit label (Atlas Sandbox / simulated / degraded) and ticketing remains not-activated.
6. **Static freeze check:** `git diff main -- static/` → empty (UI untouched).
7. **README note (DRAFT ONLY):** append a short "V2 (in progress)" note to `README.md` on the v2 branch describing the flag and the brain swap. Do NOT push or publish; the owner approves any README publication.
8. **`docs/V2_STATUS.md`:** final status — phases completed, gate evidence table, provider state, remaining risks, explicit statement that NOTHING was pushed/merged and main is intact at `c6e7a4e`.
9. Commit: `v2(P5): integrity close — dual-flag green, canary, security, honesty spot check`.
10. **STOP per §2.** Do not merge, do not push. End the session with the final handoff report (§14).

---

## 12. SELF-LEARNING LOOP (mandatory failure protocol)

On ANY gate failure:
1. **Capture:** record the exact error text, command, and phase/gate in `docs/V2_LEARNINGS.md` (timestamped entry).
2. **Diagnose:** minimal root-cause analysis. Bound provider-error retries to ONE immediate retry per call; never mass-retry loops (quota guardrail, §2).
3. **Fix:** the MINIMAL root-cause fix. Never a symptom patch, never a test edit.
4. **Rerun:** rerun the exact gate command; green closes the cycle.
5. **Limit:** maximum 3 correction cycles per distinct failure. After the 3rd red cycle: STOP that phase, write a blocker note (repro steps, 3 attempted fixes, hypothesis, suggested next step) into `docs/V2_LEARNINGS.md` AND `docs/V2_STATUS.md`, commit them, and continue only with phases that do not depend on the blocked one (if none, stop the session per §2).
6. **Log everything discovered:** every gotcha (qwen-agent quirks, provider behaviors, async bridging surprises) becomes a dated entry in `docs/V2_LEARNINGS.md` — running log, append-only, following the team's lesson-log convention. Later phases and future agents read it FIRST.
7. **Invariant:** never weaken, skip, delete, or rewrite a test to pass a gate. A red legacy test means the migration broke a contract — repair the migration.

Known gotchas to seed `docs/V2_LEARNINGS.md` with (verified this session):
- `'stream'` inside `generate_cfg` raises `TypeError` in qwen-agent 0.0.34 → control streaming via `bot.run(..., stream=False)`.
- qwen-agent has undeclared import deps (numpy, soundfile, tqdm, jieba, python-dateutil) — already installed in `.venv`; do not "fix" requirements.txt.
- Async `AtlasClient.search_flights` needs `asyncio.run` inside sync tool `call()` when outside FastAPI, and a thread-executor bridge when inside a running event loop.
- Tools must return error JSON, never raise into the agent loop.
- ModelScope key is `.ai`-region only (`.cn` endpoint → 401); legacy `services/llm.py` defaults to `.cn` and stays that way.
- ModelScope free quota exhausted 2026-08-31 → HTTP 429; OpenRouter fallback is the expected live provider.

---

## 13. INTERFACES (exact contracts)

### 13.1 Qwen-Agent `llm_cfg` (the ONLY sanctioned shape; from the proven demo)
```python
llm_cfg = {
    "model": MODEL,                      # provider-specific model id (§7.1)
    "model_server": BASE_URL,            # provider base URL (§7.1)
    "api_key": API_KEY,                  # env-driven; never logged/printed
    "generate_cfg": {
        "fncall_prompt_type": "nous",
        "extra_body": {"enable_thinking": False},
        # NEVER put 'stream' here (TypeError in 0.0.34)
    },
}
bot = Assistant(llm=llm_cfg, system_message=..., function_list=[...],
                name="TravelCare Rescue", description=...)
for history in bot.run(messages=messages, stream=False):
    pass   # final `history` holds the message list incl. function_call objects
```

### 13.2 Tool registration contract
```python
@register_tool("flight_search")
class FlightSearchTool(BaseTool):
    description = "<loaded from flight_search.SKILL.md frontmatter>"
    parameters = [{"name": ..., "type": "string", "description": ..., "required": True}, ...]
    def call(self, params: str, **kwargs) -> str:  # JSON string in, JSON string out
```

### 13.3 Tool param/return JSON shapes
All tools: input = JSON object string per the table below; output = single JSON object string; error output = `{"error": "<Type>: <message>", "tool": "<name>", "status": "failed"}` (never raise, never leak keys, never include provider payloads verbatim beyond what the legacy skill already returns).

| Tool | Params (required unless noted) | Success return (key fields) |
|---|---|---|
| `goal_intake` | `text` | `{status, trip_goal: {origin_city, dest_city, date_window, passengers, passport_country, budget?, notes}, missing_fields: [...]}` |
| `clarify_loop` | `trip_goal` (object), `profile` (object) | `{complete: bool, next_field?, question?, reason?, confirmation_required: bool}` |
| `flight_search` | `origin`, `destination`, `date` (ISO) | `{source: "atlas_sandbox", provenance: "atlas_sandbox", note, query, offer_count, offers_returned, offers: [{offer_id, flight_number, airline, airline_code, origin, destination, departure_time, arrival_time, duration_minutes, stops, via, cabin_class, price_usd, seats_available}]}` |
| `visa_check` | `passport` (ISO-2), `origin`, `destination` | `{passport, passport_name, destination_rule: {status, note}, route_assessment: <visa_guard output>, as_of, citations?}` |
| `rights_check` | `origin`, `destination` | `{origin_country, destination_country, route_distance_km, applicable_jurisdictions: [...], entitlements: [...], note}` |
| `safety_check` | `destination`, `origin` (optional) | `{assessment: {..., trip_policy_status, overall_status, why_selected}, provenance_label, advisories: [...]}` |
| `location_resolve` | `text` | `{candidates: [{iata, name, city}], ambiguous: bool, confirmation_required: bool}` |
| `itinerary` | `trip_id` or `trip_goal` | `{sections: [...], provenance per section, suggestions labeled "suggestion only"}` |
| `flight_book` | `offer_id`, `trip_id`, `approval_state` | `{status: "booked"|TICKETING_ACTIVATION_REQUIRED|"approval_required"|..., receipt?...}` |
| `recovery_plan` | `trip_id` | `{alternatives: [...], approval_request: {...}, never_booked_without_approval: true}` |
| `disruption_monitor` | `trip_id` | `{pnr, status, disruption: {...}|null}` |
| `guardian_push` | `trip_id`, `message_kind` | `{status: "sent"|"simulated"|"skipped", preview?, label}` |
| `profile_capture` | `field`, `value`, `source`, `confirmed: bool` | `{status, stored_field?, source_tag}` |
| `profile_edit` | `field`, `value` or `delete: true` | `{status, profile_state}` |
| `web_intel` | `query` | `{findings: [...], citations: [{source_url, retrieved_date}], cache_hit, degraded: bool}` |
| `radar_scan` | `trip_id` (optional) | `{scans: [...], engine: "deterministic_radar"}` |
| `research_brief` | `trip_id` or `trip_goal` | `{brief, provenance: [...], degraded: bool}` |

### 13.4 Flag semantics
- `TRAVELCARE_BRAIN` unset or `legacy` → ALL request paths use v1 code exactly as submitted (byte-for-byte behavior contract).
- `TRAVELCARE_BRAIN=qwen_agent` → conversation/intent/tool-selection uses the Qwen-Agent brain; deterministic engines unchanged; any qwen-brain unavailability (no provider healthy, import failure, malformed model output) falls back to the legacy path per-request, labeled in telemetry.
- Any other value → coerced to `legacy` with a logged warning.

### 13.5 Provider fallback behavior contract
1. Every LLM call tries ModelScope first, then OpenRouter, per §7.1.
2. The serving provider's name is attached to every response/telemetry surface that already carries provider info (no new public surface required; existing telemetry hooks).
3. Both providers down → deterministic degraded mode with explicit labeling; zero fabricated content.
4. Key values never appear in logs, responses, tests, docs, or commits.

---

## 14. HANDOFF FORMAT (what you MUST report)

**At every phase gate (P1–P5), report:**
1. Phase + gate name.
2. Files changed (exact paths) with one-line purpose each.
3. Gate evidence: verbatim command + summary line(s) (pytest counts for BOTH flag values where required, canary 14/14, security gate summary, provider attribution for live smokes).
4. New `docs/V2_LEARNINGS.md` entries added.
5. Remaining risks / open questions for the owner.

**At completion, final report must contain:**
1. Commit list on `v2/qwen-agent-migration` (`git log --oneline main..HEAD`).
2. Dual-flag full-suite results + dual canary results + security gate result + secrets sweep result.
3. Honesty spot-check evidence (labels observed).
4. Confirmation statements, each explicit: main untouched at `c6e7a4e`; nothing pushed; nothing merged; no deployment; no payments; `examples/qwen_agent_demo/` intact and untracked; `static/` byte-frozen; no secrets committed; ticketing still not activated.
5. Full contents summary of `docs/V2_STATUS.md` and `docs/V2_LEARNINGS.md`.

---

## 15. CONSTRAINTS & PROHIBITIONS (absolute)

1. **NEVER** merge into, rebase, reset, or otherwise touch `main`; NEVER `git push` anything; NEVER rewrite history.
2. **NEVER** deploy, publish, release, or change public repo settings.
3. **NEVER** activate ticketing, process payments, or perform real bookings; Atlas interactions stay Sandbox via the authenticated CLI bridge only.
4. **NEVER** commit, print, log, or embed secret values (API keys, tokens). `.env` stays untracked; `.env.example` keeps placeholders only.
5. **NEVER** delete, skip, weaken, or rewrite any existing test; NEVER delete legacy code before P5 dual-green, and even then keep the legacy path functional (strangler-fig means both brains coexist).
6. **NEVER** modify `static/` (byte-frozen), `examples/qwen_agent_demo/` (keep intact as reference), `requirements.txt`, or `models/schemas.py` contracts in breaking ways.
7. **NEVER** let the LLM compute visa outcomes, rights amounts, safety verdicts, radar detections, or Atlas data — tool-wrap only (§4.4).
8. **NEVER** fabricate data to satisfy a gate; honest degraded mode is always acceptable, fabrication is disqualifying.
9. **NEVER** exceed the bounded model-call guardrail (§2); NEVER buy quota or create accounts.
10. Keep every phase independently verifiable: at any commit on the v2 branch, `TRAVELCARE_BRAIN=legacy` must reproduce the submitted product exactly.

---

*End of package. Execute G0 now.*
