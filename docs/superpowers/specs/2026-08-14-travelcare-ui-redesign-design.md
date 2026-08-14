# TravelCare AI — UI Redesign Specification

**Project:** Alibaba Cloud x Atlas Agentic AI Hackathon 2026
**Track:** Flights & Aviation
**Author:** Victor Job (Aung Hein Kyaw)
**Date:** 2026-08-14
**Deadline:** Aug 30, 2026 (3-min video demo submission)

---

## 1. Problem Statement

The current dashboard (`static/index.html`, 1842 lines) is cluttered with gimmicky micro-interactions that obscure the core value proposition. Judges have 3 minutes to understand the product. The UI must tell a clear story: **flight disrupted → AI agent detects → Atlas GDS searches → rescue packages offered → 1-click rebook → boarding pass + compensation**.

## 2. Design Direction

**Warm Travel-App** — inspired by modern travel apps (TripIt, Airbnb, Google Travel). Cream backgrounds, teal accent, soft amber borders. Professional, calm, trustworthy. Not a tech demo — a product.

## 3. Layout Structure

**Focused Two-Panel** — slim icon sidebar (48px) + main content area. Only 3 navigation views:

1. **Rescue Hub** (default) — the core demo screen
2. **Search** — GDS flight search
3. **Concierge** — AI chat assistant

No DAG visualizer, token economics, verifier suite, telemetry inspector, or other engineering views.

```
┌──┬──────────────────────────────────────┐
│  │  Top bar: brand + status + trigger    │
│  ├──────────────────────────────────────┤
│ S│                                       │
│ i│  Main content area                    │
│ d│  (Rescue Hub / Search / Concierge)    │
│ e│                                       │
│  │                                       │
└──┴──────────────────────────────────────┘
```

## 4. Color Palette & Typography

### Color Tokens

| Token | Value | Usage |
|---|---|---|
| `--bg-cream` | `#FDF6EE` | Page background (warm cream) |
| `--bg-card` | `#FFFFFF` | Card backgrounds |
| `--accent-teal` | `#0F766E` | Primary buttons, active states, brand |
| `--accent-teal-light` | `#CCFBF1` | Teal tinted backgrounds |
| `--border-amber` | `#F3D4B8` | Card borders, dividers |
| `--text-dark` | `#1C1917` | Primary text |
| `--text-muted` | `#78716C` | Secondary text |
| `--status-danger` | `#DC2626` | Cancelled / error |
| `--status-danger-bg` | `#FEF2F2` | Alert backgrounds |
| `--status-warning` | `#F59E0B` | Warning badges |
| `--status-success` | `#059669` | Success / confirmed |

### Typography

- **UI text:** Inter (system fallback: -apple-system, BlinkMacSystemFont, sans-serif)
- **Codes, times, prices:** JetBrains Mono (fallback: monospace)
- **No emojis** anywhere — replace all emoji with text labels

## 5. Rescue Hub View (Main Demo Screen)

Top-to-bottom flow in one scrollable column:

### 5a. Disruption Alert Banner

Warm red background (`--status-danger-bg`), red left border, danger text.

```
┌─────────────────────────────────────────────────┐
│ TG 303 CANCELLED — Autonomous Rescue Active     │
│ Scanning 140+ airlines via Atlas GDS...          │
└─────────────────────────────────────────────────┘
```

- Two lines: flight number + status, scanning status
- No radar animation, no pulse-glow

### 5b. Flight Route Visual (NEW)

Simple inline SVG showing the rescue concept instantly:

```
  Cancelled:  BKK ──✕──→ RGN     (red, struck through)
  Rescue:     BKK ──✈──→ RGN     (teal, solid line)
```

- Airport codes as text, not emojis
- Red line with X for cancelled, teal line with plane icon for rescue
- No animation — static, clear, instant comprehension

### 5c. AI Agent Reasoning Trail (NEW)

Vertical timeline showing the agent's decision process transparently:

```
  ● 1. Detected TG 303 cancellation          (just now)
  ● 2. Searched 140+ airlines via Atlas GDS  (0.8s)
  ● 3. Qwen-2.5 ranked by time + price        (0.3s)
  ● 4. Fare locked on 2 alternatives          (active)
```

- 4 dots, vertical connector line, clean text
- Timestamps in muted text
- Step 4 shows "active" state (teal dot, slightly larger)
- Demonstrates Qoder Platform usage (judges see the AI reasoning)

### 5d. Rescue Package Cards (2 cards, side by side)

Two cards in a horizontal flex row:

**Card 1: FASTEST**
```
┌──────────────────┐
│ FASTEST          │
│ MAI 8M 336       │
│ BKK 11:45 → RGN  │
│ 12:35 • Nonstop  │
│                  │
│ Fare Lock        │
│ 14:58 remaining  │
│                  │
│ $145             │
│ Airline-covered  │
│                  │
│ [1-Click Rebook] │
└──────────────────┘
```

**Card 2: BEST VALUE**
```
┌──────────────────┐
│ BEST VALUE       │
│ AirAsia FD 251   │
│ DMK 16:20 → RGN  │
│ 17:05 • Nonstop  │
│                  │
│ $56 Surplus      │
│ Cash back        │
│                  │
│ $89              │
│ Instant payout   │
│                  │
│ [1-Click Rebook] │
└──────────────────┘
```

Card features:
- White background (`--bg-card`), amber border (`--border-amber`), rounded corners (12px)
- Label badge at top (FASTEST / BEST VALUE) in teal tinted background
- Airline name + flight code in JetBrains Mono
- Route + times in main text
- AI reasoning text: one line per card ("Departs in 1h 45m, minimizes downtime")
- Fare Lock Countdown (NEW): live timer counting down from 14:59 to 0:00, updates every second, JetBrains Mono
- Price prominent, large font
- Badge: "Airline-covered" or "Instant payout" in success green
- Button: teal background, white text, full width, "1-Click Rebook"

### 5e. Auto-Compensation Card (NEW)

Small card below the rescue packages:

```
┌─────────────────────────────────────────────────┐
│ Auto-Filed Compensation                          │
│ Claim #CLM-2026-8941 • $250.00 USD               │
│ Status: READY_FOR_INSTANT_PAYOUT                  │
│ [Instant 1-Click Payout]                         │
└─────────────────────────────────────────────────┘
```

- Full width, amber border, compact
- Shows the agent handles full recovery, not just flights
- Button: teal outline (not filled), to differentiate from rebook buttons

## 6. Search View

Clean flight search interface:

- Form: Origin (text input), Destination (text input), Date (date picker), Passengers (number select), Search button
- Results stream as simple cards below the form
- Each result card: airline, flight number, departure → arrival times, duration, price, "Select" button
- No fancy effects — just clean data display
- Multi-currency selector in top right of form

## 7. Concierge View

Chat interface:

- Message bubbles (user right, AI left)
- 4 quick prompt chips above input: "Vegetarian meal", "Gate D4 directions", "Baggage status", "Claim payout"
- Input box + send button (teal)
- No mic button, no voice recognition, no audio waveform
- Text only

## 8. Boarding Pass Modal

Triggered when 1-Click Rebook is clicked:

- Clean white card, centered, with dark overlay backdrop
- Route: BKK → RGN
- Flight code, gate, seat, boarding time
- Simple barcode SVG (vertical bars)
- "Done" button to close
- No 3D tilt, no gyroscope, no parallax

## 9. Simulate Disruption Trigger

Small button in the top bar (right side), teal outline:
- Label: "Simulate Disruption"
- On click: triggers the disruption alert banner, reasoning trail, and rescue packages
- Needed for demo — judges need to see the agent activate

## 10. What Gets Cut (Definitive List)

The following features/elements are **removed entirely** from the new UI:

1. Predictive Radar Banner
2. Flight Diff Card (redundant with route visual)
3. Seat Map (cabin seat selector)
4. Baggage IoT Pulse timeline
5. DAG State Graph visualizer
6. Token Economics grid
7. Deterministic Verifier Suite table
8. Siri-style audio waveform canvas
9. 3D gyroscope tilt on boarding pass
10. Floating glassmorphism HUD toasts
11. Self-healing loop button
12. Dynamic Island top bar
13. All emojis (replaced with text labels)
14. All pulse-glow animations (replaced with simple status badges)
15. Hotels & Hospitality view (not relevant to Flights track)
16. Claims & Compensation Ledger view (merged into Rescue Hub as compact card)
17. Atlas API & Webhook Telemetry view (engineering, not user-facing)

## 11. Backend API Contract

The new UI calls the same existing FastAPI endpoints. No new endpoints needed:

| Action | Endpoint | Method |
|---|---|---|
| Trigger disruption | `/api/v1/disruptions/simulate` | POST |
| Get rescue packages | `/api/v1/disruptions/rescue-packages` | GET |
| 1-Click Rebook | `/api/v1/bookings/rebook` | POST |
| Flight search | `/api/v1/flights/search` | GET |
| Concierge chat | `/api/v1/concierge/chat` | POST |
| Get boarding pass | `/api/v1/bookings/boarding-pass/{id}` | GET |
| File compensation | `/api/v1/claims/file` | POST |

All responses use the existing mock fallback data in `services/atlas_client.py` and `services/rescue_engine.py`. No external API keys required for demo.

## 12. Testing Strategy

### Unit Tests (`test_rescue_agent.py`)

- Update any assertions that reference removed UI elements
- Ensure rescue package data structure still matches (2 packages, not 3)
- Verify disruption simulation returns correct status flow
- Verify compensation claim filing

### E2E Tests (`test_e2e_playwright.py`)

- Update selectors for new class names/IDs
- Test flow: load page → click Simulate Disruption → verify alert banner → verify 2 rescue packages → click 1-Click Rebook → verify boarding pass modal → close
- Test Search view: fill form → verify results
- Test Concierge view: type message → verify response
- Remove tests for: seat map, baggage timeline, DAG graph, token economics, verifier suite, audio waveform

## 13. Demo Recording Guide (for Victor)

The 3-minute video demo should follow this flow:

1. **(0:00-0:20)** Show the clean TravelCare AI dashboard on Rescue Hub view
2. **(0:20-0:30)** Click "Simulate Disruption" — banner appears, reasoning trail populates
3. **(0:30-1:00)** Show the 2 rescue packages, explain AI ranking (Qwen-2.5 via Qoder)
4. **(1:00-1:20)** Click "1-Click Rebook" on FASTEST package — boarding pass modal appears
5. **(1:20-1:40)** Show boarding pass, close modal
6. **(1:40-2:00)** Show auto-filed compensation card ($250)
7. **(2:00-2:30)** Switch to Search view, do a quick flight search
8. **(2:30-3:00)** Switch to Concierge, ask a quick question, show response

## 14. Submission Checklist (for Victor)

- [ ] Record 3-minute video demo (by Aug 30, 22:59 BKK)
- [ ] Upload video to submission form: https://survey.alibabacloud.com/uone/sg/survey/oGAudHR-U
- [ ] Ensure video shows: disruption detection, Atlas API search, Qwen-2.5 reasoning, 1-click rebook, boarding pass, compensation
- [ ] Verify GitHub repo is clean and README is updated
- [ ] Attend Kickoff Workshop Aug 19 (1:00 PM BKK via Zoom)

## 15. Out of Scope

- Real Atlas API integration (sandbox keys not yet configured; mock data is sufficient for demo)
- Real Qwen-2.5 API calls (mock reasoning data demonstrates the concept)
- Authentication/user accounts (single-user demo)
- Mobile responsive design (demo is on desktop)
- Internationalization (English only)
- Analytics/tracking
- Performance optimization beyond basic load times
