# Autonomous Rescue Agent — Development & Qoder Guide

## Project Purpose
Build the **Autonomous Rescue Agent** for the Alibaba Cloud x Atlas Hackathon.
The agent detects flight cancellations/delays, queries Atlas GDS (140+ airlines), and provides 1-click rebooking into 2 curated Rescue Packages.

## Codebase Architecture
- `main.py`: FastAPI server serving REST endpoints and the interactive dashboard.
- `services/atlas_client.py`: Atlas travel platform integration (search, verify, create booking, e-ticket issuance).
- `services/rescue_engine.py`: Reasoning engine that analyzes disruption context and ranks Top 3 Rescue Packages (UI shows 2).
- `static/index.html`: Warm Travel-App dashboard — 3 views (Rescue Hub, Search, Concierge), two-panel layout, cream/teal/amber palette.
- `test_rescue_agent.py`: Automated Pytest suite (11 tests).
- `test_e2e_playwright.py`: Playwright E2E browser tests (6 steps).
- `docs/superpowers/specs/`: UI redesign design spec.

## API Endpoints
- `POST /api/disruption/analyze` — trigger disruption analysis, returns rescue packages
- `POST /api/flights/search` — GDS flight search across 140+ airlines
- `POST /api/rescue/book` — 1-click rebook, returns boarding pass data
- `POST /api/chat/concierge` — AI travel concierge chat
- `POST /api/claims/generate` — auto-file $250 compensation claim
- `GET /api/health` — health check

## Verification Commands
- Run tests: `uv run --with pytest --with pytest-asyncio --with fastapi --with pydantic --with httpx --with python-dotenv pytest test_rescue_agent.py -v`
- Run local server: `uv run --with fastapi --with uvicorn --with pydantic --with httpx --with python-dotenv python main.py`
- Run E2E tests: `uv run --with playwright python test_e2e_playwright.py`
