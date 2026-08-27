# TravelCare AI — Autonomous Flight Disruption Recovery

[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com)
[![Alibaba Cloud](https://img.shields.io/badge/Qwen3--235B--A22B-ModelScope-FF6A00.svg)](https://www.alibabacloud.com/)
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

**TravelCare AI** is an autonomous travel agent that watches your flights, reacts to disruptions before you do, rebooks you through the Atlas GDS with visa-aware intelligence for passport-constrained travelers, and runs a Claims Autopilot that detects which air-passenger-rights regime actually applies to *your* route — then computes an honest entitlement and drafts regulation-cited claim/appeal letters.

**Core flow:** Radar detects disruption → agent pre-builds rescue plans → visa-safe packages ranked → 1-click rebook on Atlas Sandbox → Claims Autopilot resolves jurisdiction (EU261 / UK261 / Turkey SHY / US DOT / none) from the real airports + carrier → distance-band entitlement + Qwen cause classification → evidence pack, claim letter, appeal letter.

The agent is honest by design: on routes where no mandatory scheme exists (e.g. BKK→RGN), it says so and registers the duty-of-care/refund route instead of inventing cash.

## Data Authenticity

Atlas organizers confirmed (2026-08): *"We did not prepare a separate 'Hackathon Dataset' … You can directly use the Sandbox data to complete and demonstrate your project."*

| Layer | State |
|---|---|
| Flight search & fares | Live Atlas Sandbox via official `atlas-flight` CLI (`ATLAS_USE_CLI=true`); offers may carry `price_status=reference`, disclosed in the UI |
| Booking | Sandbox order settlement (`POST /api/rescue/book`) |
| LLM reasoning | Live Qwen3-235B-A22B-Instruct via ModelScope (`LLM_BASE_URL`, `ALIBABA_MODEL_API_KEY`) |
| Rights engine | Deterministic rule tables grounded in published regulations |
| Visa rules | Conservative curated table (2026-08), flags RISK over CLEAR |
| Telegram Guardian | Live push when `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` set; simulated preview otherwise |
| Transit hotels / care vouchers / baggage / seatmap | Demo content |
| Predictive radar numbers | Simulated telemetry |
| `GET /api/graph/state` | Canned replay (`mode=demo_replay`); live DAG trace ships inside every analyze response |

No hardcoded passenger names, dates, routes or payouts exist anywhere in the pipeline.

## Quickstart

### 1. Configure
```bash
cp .env.example .env   # if provided; else create .env with:
# ALIBABA_MODEL_API_KEY=...        # ModelScope key
# LLM_BASE_URL=https://api-inference.modelscope.cn/v1
# ATLAS_USE_CLI=true               # use atlas-flight CLI auth
# TELEGRAM_BOT_TOKEN=...           # optional, from @BotFather
# TELEGRAM_CHAT_ID=...
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
| Disruption analyze (full agentic run) | POST | `/api/disruption/analyze` |
| Self-healing recovery | POST | `/api/disruption/self-heal?flight_number=` |
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
    ├── atlas_client.py        # Atlas Sandbox client (CLI bridge + mock fallback)
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
2. **(0:20–0:40)** Simulate Disruption → banner + reasoning trail animates (VisaGuard, Guardian push steps appear)
3. **(0:40–1:10)** Visa-safe rescue packages fade in with live Sandbox fares ("Sandbox reference price" chip) → 1-Click Rebook → timeline → boarding pass
4. **(1:10–1:40)** Claims Autopilot panel: honest verdict — no mandatory regime on BKK→RGN, duty-of-care refund route registered
5. **(1:40–2:10)** API call: AF198 CDG→BKK → EU261 detected, real great-circle distance banding → EUR 600 entitlement + cited appeal letter via live Qwen
6. **(2:10–2:40)** Concierge chat (live Qwen) + multi-currency flight search
7. **(2:40–3:00)** Mobile viewport: bottom nav, stacked cards

---

## License

MIT License. Built for the Alibaba Cloud x Atlas Agentic AI Hackathon 2026.
