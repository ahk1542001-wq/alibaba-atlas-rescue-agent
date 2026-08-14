# Autonomous Rescue Agent — Development & Qoder Guide

## Project Purpose
Build the **Autonomous Rescue Agent** for the Alibaba Cloud x Atlas Hackathon.
The agent detects flight cancellations/delays, queries Atlas GDS (140+ airlines), and provides 1-click rebooking into 3 curated Rescue Packages.

## Codebase Architecture
- `main.py`: FastAPI server serving REST endpoints and the interactive simulation Web UI.
- `services/atlas_client.py`: Atlas travel platform integration (search, verify, create booking, e-ticket issuance).
- `services/rescue_engine.py`: Reasoning engine that analyzes disruption context and ranks Top 3 Rescue Packages.
- `static/index.html`: Modern, responsive interactive dashboard for the 3-minute video demo.
- `test_rescue_agent.py`: Automated test suite.

## Verification Commands
- Run tests: `uv run --with pytest --with pytest-asyncio --with fastapi --with pydantic --with httpx --with python-dotenv pytest test_rescue_agent.py -v`
- Run local server: `uv run --with fastapi --with uvicorn --with pydantic --with httpx --with python-dotenv python main.py`
