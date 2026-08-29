# TravelCare AI — Autonomous Flight Disruption Recovery

[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com)
[![AI runtime](https://img.shields.io/badge/AI-configured%20LLM%20or%20deterministic%20fallback-FF6A00.svg)](https://www.alibabacloud.com/)
[![Atlas GDS](https://img.shields.io/badge/Atlas%20Travel-ATRIP%20Sandbox-0F766E.svg)](https://sandbox.atriptech.com)
[![Tests](https://img.shields.io/badge/Tests-19%20unit%20%2B%2014%20E2E-success.svg)](tests/)

> **Hackathon:** Alibaba Cloud x Atlas Agentic AI Hackathon 2026
> **Track:** Flights & Aviation Autonomous Agents
> **Participant / Lead Architect:** Aung Hein Kyaw (Victor Job)
> **Team Mailbox:** `aihackathon048@aihackathon.atriptech.com`
> **Demo Submission Deadline:** August 30, 2026

---

## Overview

Flight cancellations strand travelers for hours while the compensation they are legally owed goes unclaimed — roughly EUR 5.9B/year under EU261 alone, and airlines wrongfully reject ~52% of claims citing "extraordinary circumstances".

**TravelCare AI** is an agentic travel assistant that searches the official Atlas Sandbox, ranks visa-aware options for passport-constrained travelers, and runs a Claims Autopilot that detects which air-passenger-rights regime actually applies to *your* route — then computes an honest entitlement and drafts regulation-cited claim/appeal letters.

**Core flow:** traveler plans a trip naturally through conversation → pure deterministic Conversation Controller projects state into beginner-friendly turns → deterministic TripGraph executes provider calls, safety checks, and research → traveler reviews their complete reversible travel plan (flights, lodging, activities, transit, and entry requirements) before booking → fare is re-verified immediately before booking → traveler explicitly approves Atlas Sandbox booking attempt → ticketing either creates a real Sandbox order or fails closed with `TICKETING_ACTIVATION_REQUIRED` without fabricating PNRs → Claims Autopilot resolves jurisdiction (EU261 / UK261 / Turkey SHY / US DOT / none).

## Data Authenticity

Atlas organizers confirmed (2026-08): *"We did not prepare a separate 'Hackathon Dataset' … You can directly use the Sandbox data to complete and demonstrate your project."*

| Layer | State |
|---|---|
| Conversation Controller | Pure deterministic projection (`services/conversation_controller.py`); at most one active question; safety and approval gates take priority; no PII collected |
| Flight search & fares | Official Atlas Sandbox through the authenticated `atlas-flight` CLI; exact-airport results only, with provider `price_status` and `bookable` truth preserved |
| Booking & Ticketing | Fail-closed Sandbox order path with 8-field capability boundary. This account reports `TICKETING_ACTIVATION_REQUIRED`; no PNR or ticket is fabricated |
| LLM reasoning | Configured ModelScope-compatible model via `LLM_BASE_URL` + `ALIBABA_MODEL_API_KEY`; deterministic fallback when no model is configured |
| Rights engine | Deterministic rule tables grounded in published regulations |
| Visa rules | Conservative curated table (2026-08), flags RISK over CLEAR |
| Telegram Guardian | Live push requires `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` + `TELEGRAM_LIVE_TEST=true`; returns redacted simulated preview otherwise |
| Disruption rescue, transit hotels, care vouchers, baggage, seatmap, predictive radar | Explicitly labeled demo simulation only; never a provider fallback |
| `GET /api/graph/state` | Canned replay (`mode=demo_replay`); live DAG trace ships inside every analyze response |

Runtime Atlas search and verification never fall back to product-coded offers. Hermetic test doubles remain in tests, and the visible “Simulate Disruption” experience is explicitly labeled simulation data.

## Quickstart

### 1. Configure
```bash
cp .env.example .env   # if provided; else create .env with:
# ALIBABA_MODEL_API_KEY=...        # ModelScope key
# LLM_BASE_URL=https://api-inference.modelscope.cn/v1
# TELEGRAM_BOT_TOKEN=...           # optional, from @BotFather (requires CHAT_ID + LIVE_TEST=true)
# TELEGRAM_CHAT_ID=...
# TELEGRAM_LIVE_TEST=false
```

### 2. Run
```bash
python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt
atlas-flight auth login            # one-time Atlas Sandbox auth
.venv/bin/python main.py           # http://localhost:8050
```

### 3. Test
```bash
.venv/bin/python -m pytest tests/test_rights_and_visa.py -v   # 19 unit tests
.venv/bin/python tests/e2e_full_journey.py                    # 14-step legacy browser canary
```

---

## API Endpoints

| Action | Method | Endpoint |
|---|---|---|
| Health + AI engine info | GET | `/api/health` |
| Real disruption analyze (fails closed until a status source exists) | POST | `/api/disruption/analyze` |
| Explicit disruption demo | POST | `/api/disruption/analyze?allow_sim=true` |
| Explicit self-healing demo | POST | `/api/disruption/self-heal?flight_number=` |
| Flight search | POST | `/api/flights/search` |
| 1-click rebook | POST | `/api/rescue/book` |
| Claims Autopilot assess | POST | `/api/claims/assess` |
| Appeal letter drafting | POST | `/api/claims/appeal` |
| Concierge chat | POST | `/api/chat/concierge` |
| Radar state / scan / watch / SSE | GET·POST | `/api/radar`, `/api/radar/scan`, `/api/radar/watch`, `/api/radar/stream` |
| Transit hotels / care vouchers | GET | `/api/hotels/search`, `/api/hotels/vouchers/care` |
| Baggage / seatmap / predictive radar / agent telemetry / graph replay | GET | `/api/baggage/track`, `/api/seatmap`, `/api/radar/predictive`, `/api/agent/telemetry`, `/api/graph/state` |

Interactive docs: `/api/docs`.

## Repository Structure

```
alibaba-atlas-rescue-agent/
├── main.py                    # FastAPI app, lifespan radar loop, health
├── config.py                  # Pydantic settings (.env-driven)
├── models/schemas.py          # Pydantic contracts (no fake defaults)
├── routers/v1/
│   ├── flights.py             # POST /api/flights/search
│   ├── disruptions.py         # POST /api/disruption/analyze, /self-heal
│   ├── bookings.py            # POST /api/rescue/book
│   ├── concierge.py           # POST /api/chat/concierge
│   ├── claims.py              # POST /api/claims/assess, /appeal
│   ├── hotels.py              # transit hotels + care vouchers
│   ├── radar.py               # watchlist, scan, SSE stream
│   └── telemetry.py           # baggage, seatmap, predictive radar, graph replay
├── services/
    ├── atlas_client.py        # Strict Atlas Sandbox CLI boundary + explicit demo fixtures
    ├── rescue_engine.py       # DAG orchestration, package curation, claims
    ├── rights_engine.py       # jurisdictions, distance bands, letters, airport maps
    ├── visa_guard.py          # passport-aware rebooking filter/rank
    ├── guardian.py            # proactive Telegram push (token-driven)
    ├── radar.py               # autonomous monitoring loop
    ├── state_graph.py         # closed-loop DAG state recorder
    └── llm.py                 # OpenAI-compatible Qwen client (ModelScope etc.)
├── static/                    # index.html, styles.css, app.js (vanilla)
├── tests/
│   ├── test_rights_and_visa.py    # 19 unit tests
│   └── e2e_full_journey.py        # 14-step Playwright full-journey E2E
└── docs/superpowers/          # design specs & plans
```

---

## 3-Minute Video Demo Flow

1. **(0:00–0:20)** Dashboard empty state → Add Flight: type flight (TG303), date, passenger name, MM passport
2. **(0:20–0:40)** Simulate Disruption → explicitly labeled demo banner + reasoning trail animates; no Atlas provider call or external notification occurs
3. **(0:40–1:10)** Demo visa-safe rescue packages fade in. Separately show a real Atlas Sandbox search in the trip flow; booking remains unavailable until provider ticketing is activated
4. **(1:10–1:35)** Approve one real Sandbox offer → show the honest `TICKETING_ACTIVATION_REQUIRED` response and confirm that no PNR or ticket appears
5. **(1:35–2:05)** Explicit disruption simulation → demo-only recovery graph, visa-aware ranking, and no external notification or booking
6. **(2:05–2:30)** Claims panel → show that a missing provider flight route fails closed instead of manufacturing a jurisdiction or payout
7. **(2:30–2:50)** Evidence → 14/14 legacy browser canary, strict provider tests, security gate, and exact-airport filtering
8. **(2:50–3:00)** Mobile viewport + closing value statement

This is a provisional storyboard. Confirm the official Devpost video duration,
hosting, visibility, and form fields before recording the final cut.

---

## License

MIT License. Built for the Alibaba Cloud x Atlas Agentic AI Hackathon 2026.
