# V2 Migration Learnings Log

## 2026-08-31 — G0 Baseline & Seed Learnings
- **ModelScope Quota**: ModelScope free quota was exhausted on 2026-08-31 (HTTP 429); OpenRouter fallback (`qwen/qwen3-235b-a22b-2507`) is the expected active provider.
- **ModelScope Region**: ModelScope API key requires `https://api-inference.modelscope.ai/v1` (`.ai` domain); `.cn` returns 401 Unauthorized. Legacy `services/llm.py` defaults to `.cn` and stays untouched for legacy brain.
- **Qwen-Agent 0.0.34**: `'stream'` inside `generate_cfg` raises `TypeError` in `qwen-agent` 0.0.34. Control streaming strictly via `bot.run(messages=..., stream=False)`.
- **Async Bridging**: Tool `call()` is synchronous. Outside a running loop, use `asyncio.run()`. Inside FastAPI's running event loop, execute sync tools via a thread executor (`loop.run_in_executor` or `asyncio.to_thread`) — never call `asyncio.run()` inside a running loop.
- **Tool Exceptions**: Tools must return structured error JSON (`{"error": "<Type>: <message>", "tool": "<name>", "status": "failed"}`) rather than raising exceptions into the agent loop.
- **Baseline Evidence (G0)**:
  - Branch: `v2/qwen-agent-migration` (created from `main` @ `c6e7a4e`)
  - Pytest baseline: `535 passed` (`TZ=UTC .venv/bin/python -m pytest -q`)
  - Browser E2E canary: `14/14 passed` (`.venv/bin/python tests/e2e_full_journey.py`)
  - Security check: `ALL SECTIONS PASS` (`bash scripts/security_check.sh`)


## 2026-08-31 — P1 Provider Fallback & Scaffolding
- **Dual-Provider Verification**: Live ModelScope probe returned HTTP 429 quota exhaustion; fallback chain gracefully caught the error, logged structured warning without key exposure, and routed request to OpenRouter (`qwen/qwen3-235b-a22b-2507`), successfully returning live completion.
- **TRAVELCARE_BRAIN Feature Flag**: Flag cleanly toggles between legacy brain and Qwen-Agent brain with fail-safe coercion of invalid values to "legacy".
- **Test Evidence (P1)**:
  - 10 new hermetic tests in `tests/test_v2_brain_flag.py` and `tests/test_v2_providers.py` PASSED.
  - Full suite: 545 passed in 217s.
  - Smoke boots on both `TRAVELCARE_BRAIN=legacy` and `qwen_agent` returned HTTP 200 on `/api/health`.

## Phase 2 (P2) - Conversation Layer Swap (Goal Intake + Clarification)
- **Implemented**:
  - `services/qwen_brain/`: package scaffolding with `__init__.py`.
  - `services/qwen_brain/tools/conversation.py`: `GoalIntakeTool` and `ClarifyLoopTool` Qwen-Agent tool implementations registered via `@register_tool`. Tools wrap `GoalIntakeSkill` and `ClarifyLoopSkill` with resilient exception containment returning JSON error payloads on bad input.
  - `services/qwen_brain/agent.py`: `build_travelcare_agent` constructing `Assistant` with resolved dual-provider LLM config and async executor `run_qwen_conversation` using `asyncio.to_thread`.
  - `services/qwen_brain/conversation.py`: `run_qwen_goal_intake` and `run_qwen_trip_turn` executing goal intake and conversation turns while propagating orchestrator context (`mock_mode`, `flight_corpus`, `user_id`) and profile store references.
  - `routers/v1/trip.py`: Seam in `TripOrchestrator.start` branching to `run_qwen_goal_intake` when `is_qwen_brain()` is True.
  - `tests/test_v2_conversation_parity.py`: 7 hermetic parity tests covering Assistant factory, GoalIntakeTool extraction, ClarifyLoopTool questions, JSON fault resilience, and full `/api/trip/start` state parity across flags.
- **Evidence**:
  - Parity suite: 7/7 PASSED in 2.26s.
  - Full test suite under `TRAVELCARE_BRAIN=legacy`: 552 passed in 195s.
  - Full test suite under `TRAVELCARE_BRAIN=qwen_agent`: 552 passed in 194s.
  - Dual browser canary (`tests/e2e_full_journey.py`): 14/14 PASSED on `legacy` and 14/14 PASSED on `qwen_agent`.
  - Security check (`scripts/security_check.sh`): ALL SECTIONS PASS.
- **Learnings**:
  - When wrapping skills into Qwen-Agent tools, always pass orchestrator context (`ctx`) and shared store references (e.g. `ProfileStore`) into tool constructors and invocations to preserve mock mode, test fixtures, and shared state across test suites.

## Phase 3 (P3) - Skills Migration Wave 1 (Flight, Visa, Rights, Safety, Concierge)
- **Implemented**:
  - `services/qwen_brain/tools/flight.py`: `FlightSearchTool` wrapping `AtlasClient.search_flights` with sandbox provenance and exception shielding.
  - `services/qwen_brain/tools/visa.py`: `VisaCheckTool` wrapping `visa_guard` rules and `assess_offer`.
  - `services/qwen_brain/tools/rights.py`: `RightsCheckTool` wrapping `rights_engine` distance calculation, jurisdiction detection, and entitlement computation.
  - `services/qwen_brain/tools/safety.py`: `SafetyCheckTool` wrapping `SafetyResearchSkill` and `SafetyPolicyEngine`.
  - `services/qwen_brain/concierge.py`: `run_qwen_concierge_turn` integrating assistant with trip context and tool execution.
  - `routers/v1/concierge.py`: Seam delegating `/api/chat/concierge` to `run_qwen_concierge_turn` under `is_qwen_brain()` while preserving error sanitization and passenger count proposal logic.
  - `tests/test_v2_tools_wave1.py`: 9 hermetic tests covering happy paths, resilience on malformed inputs, NONE regimes, and concierge endpoints under both brain modes.
- **Evidence**:
  - Wave 1 test suite: 9/9 PASSED in 15.52s.
  - Full test suite under `TRAVELCARE_BRAIN=legacy`: 561 passed in 208s.
  - Full test suite under `TRAVELCARE_BRAIN=qwen_agent`: 561 passed in 279s.
  - Dual browser canary (`tests/e2e_full_journey.py`): 14/14 PASSED on `legacy` and 14/14 PASSED on `qwen_agent`.
  - Security check (`scripts/security_check.sh`): ALL SECTIONS PASS.
- **Learnings**:
  - Injected router dependencies (e.g. monkeypatched `rescue_engine` in tests) must be accepted by high-level dispatchers to maintain contract parity with error sanitization test suites.


