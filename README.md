# TravelCare AI — Autonomous Flight Disruption Recovery

[![CI Test Suite](https://github.com/aungheinkyaw/alibaba-atlas-rescue-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/aungheinkyaw/alibaba-atlas-rescue-agent/actions)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com)
[![Qoder](https://img.shields.io/badge/Alibaba%20Cloud-Qwen--2.5--72B-FF6A00.svg)](https://www.alibabacloud.com/)
[![Atlas GDS](https://img.shields.io/badge/Atlas%20Travel-ATRIP%20Sandbox-0F766E.svg)](https://sandbox.atriptech.com)
[![Tests](https://img.shields.io/badge/Tests-11%2F11%20Passed%20(100%25)-success.svg)](test_rescue_agent.py)

> **Hackathon:** Alibaba Cloud x Atlas Agentic AI Hackathon 2026
> **Track:** Flights & Aviation Autonomous Agents
> **Participant / Lead Architect:** Aung Hein Kyaw (Victor Job)
> **Team Mailbox:** `aihackathon048@aihackathon.atriptech.com`
> **Demo Submission Deadline:** August 30, 2026 (23:59 SGT)

---

## Overview

Flight cancellations and severe delays cost the global airline industry $60B+ annually and trap millions of travelers in exhausting 90-180 minute airport queues.

**TravelCare AI** is an Autonomous Travel Agent-as-a-Service SaaS that detects flight disruptions in real-time, scans 140+ airlines via Atlas GDS, and delivers curated rescue packages with 1-click rebooking in under 30 seconds.

**Core flow:** Flight disrupted -> AI agent detects -> Atlas GDS searches -> 2 rescue packages ranked by Qwen-2.5 -> 1-click rebook -> boarding pass + $250 auto-filed compensation.

---

## Design

**Warm Travel-App** aesthetic inspired by modern travel apps (TripIt, Airbnb, Google Travel). Clean, calm, professional.

| Token | Value | Usage |
|---|---|---|
| Background | `#FDF6EE` | Warm cream page background |
| Cards | `#FFFFFF` | White card surfaces |
| Accent | `#0F766E` | Teal primary buttons, brand |
| Borders | `#F3D4B8` | Soft amber card borders |
| Danger | `#DC2626` | Cancelled / error states |
| Success | `#059669` | Confirmed / payout states |

**Fonts:** Inter (UI) + JetBrains Mono (codes, times, prices). No emojis.

### Layout: Focused Two-Panel

Slim 48px icon sidebar + main content area. Only 3 views:

1. **Rescue Hub** (default) — disruption alert, route visual, AI reasoning trail, 2 rescue packages, auto-compensation
2. **Search** — GDS flight search with multi-currency
3. **Concierge** — AI chat assistant with quick prompt chips

---

## Tech Stack

| Layer | Component | Technology | Role |
|---|---|---|---|
| **Backend** | API Gateway | FastAPI + Uvicorn (Python 3.13) | Sub-20ms async request latency |
| **AI** | Reasoning Engine | Alibaba Cloud Qwen-2.5 via Qoder | Multi-criteria flight ranking |
| **GDS** | Flight APIs | Atlas Travel APIs (ATRIP Sandbox) | 140+ airlines search, fare-lock, booking |
| **Frontend** | Dashboard | Vanilla HTML/CSS/JS (Warm Travel-App) | 3-view two-panel layout |
| **Testing** | QA | Pytest + Playwright | 11 unit tests + 6 E2E browser tests |

---

## Repository Structure

```
alibaba-atlas-rescue-agent/
├── main.py                    # FastAPI app with CORS and static serving
├── config.py                  # Pydantic settings & env vars
├── models/
│   └── schemas.py             # Pydantic data contracts
├── routers/v1/
│   ├── flights.py             # POST /api/flights/search
│   ├── disruptions.py         # POST /api/disruption/analyze
│   ├── bookings.py            # POST /api/rescue/book
│   ├── concierge.py           # POST /api/chat/concierge
│   ├── claims.py              # POST /api/claims/generate
│   ├── hotels.py              # Transit hotel search (legacy)
│   └── telemetry.py           # Agent telemetry (legacy)
├── services/
│   ├── atlas_client.py        # ATRIP Sandbox client with mock fallback
│   ├── rescue_engine.py       # Qwen-2.5 multi-criteria optimizer
│   ├── state_graph.py         # DAG state machine
│   └── verifiers.py           # Deterministic verifier suite
├── static/
│   └── index.html             # Warm Travel-App dashboard (3 views)
├── docs/superpowers/specs/
│   └── 2026-08-14-travelcare-ui-redesign-design.md
├── test_rescue_agent.py       # 11/11 unit tests passing
├── test_e2e_playwright.py     # 6-step E2E browser test suite
└── README.md
```

---

## Quickstart

### 1. Start Server
```bash
uv run --with fastapi --with uvicorn --with pydantic --with httpx --with python-dotenv python main.py
```
Server: `http://localhost:8050` | API Docs: `http://localhost:8050/api/docs`

### 2. Run Unit Tests (11/11)
```bash
uv run --with pytest --with pytest-asyncio --with httpx --with fastapi --with uvicorn --with pydantic --with python-dotenv pytest test_rescue_agent.py -v
```

### 3. Run E2E Browser Tests (6 steps)
```bash
uv run --with playwright python test_e2e_playwright.py
```

---

## API Endpoints

| Action | Method | Endpoint | Body |
|---|---|---|---|
| Health check | GET | `/api/health` | - |
| Trigger disruption analysis | POST | `/api/disruption/analyze` | `{flight_number, passenger_name, date, currency}` |
| Flight search | POST | `/api/flights/search` | `{origin, destination, date, passengers, cabin_class, currency}` |
| 1-Click rebook | POST | `/api/rescue/book` | `{offer_id, passenger_name, passport_number, price_usd, baggage_addon, seat_selected}` |
| Concierge chat | POST | `/api/chat/concierge` | `{query, session_id}` |
| File compensation | POST | `/api/claims/generate` | `{flight_number, passenger_name}` |

All endpoints return mock data when `USE_MOCK_FALLBACK=true` (default). No external API keys required for demo.

---

## 3-Minute Video Demo Flow

1. **(0:00-0:20)** Show the clean TravelCare AI dashboard on Rescue Hub
2. **(0:20-0:30)** Click "Simulate Disruption" — banner, reasoning trail populate
3. **(0:30-1:00)** Show 2 rescue packages, explain Qwen-2.5 AI ranking
4. **(1:00-1:20)** Click "1-Click Rebook" on FASTEST — boarding pass modal
5. **(1:20-1:40)** Show boarding pass, close modal
6. **(1:40-2:00)** Show auto-filed $250 compensation card
7. **(2:00-2:30)** Switch to Search, do a quick flight search
8. **(2:30-3:00)** Switch to Concierge, ask about vegetarian meal

---

## License
MIT License. Built for the Alibaba Cloud x Atlas Agentic AI Hackathon 2026.
