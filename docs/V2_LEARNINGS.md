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
