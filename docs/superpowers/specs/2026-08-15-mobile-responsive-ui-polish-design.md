# Mobile Responsive + Multi-Currency + UI Polish Design

**Date:** 2026-08-15
**Project:** TravelCare AI — Autonomous Flight Rescue Agent
**Hackathon:** Alibaba Cloud x Atlas Agentic AI Hackathon 2026

## Overview

Split the single-file `static/index.html` into three files (HTML + CSS + JS), add mobile responsive design with bottom nav bar, implement client-side multi-currency conversion for all monetary values, and apply UI polish across animations, boarding pass, concierge chat, and fare lock timer.

## 1. File Restructure

### Current State
- `static/index.html` — 1086 lines containing all HTML, CSS (`<style>`), and JS (`<script>`)

### Target State

| File | Contents | Approx Size |
|---|---|---|
| `static/index.html` | HTML markup only (sidebar, topbar, views, modals, overlays) | ~250 lines |
| `static/styles.css` | All CSS — `:root` variables, layout, components, `@media` queries, keyframes | ~500 lines |
| `static/app.js` | All JS — view switching, simulate disruption, rebook, chat, search, currency conversion | ~400 lines |

`index.html` links them:
```html
<link rel="stylesheet" href="/static/styles.css">
<script src="/static/app.js"></script>
```

No build step. FastAPI already mounts `/static` as a static file directory.

## 2. Mobile Responsive Design

### Breakpoint
`@media (max-width: 768px)` — targets phones and small tablets.

### Navigation: Bottom Nav Bar

The desktop left sidebar (48px vertical icon rail) is hidden on mobile and replaced by a fixed bottom navigation bar with three tabs:

| Tab | Icon | Label | Active Style |
|---|---|---|---|
| Rescue Hub | Heartbeat/pulse SVG | "Rescue" | Teal background, white icon |
| Search | Magnifying glass SVG | "Search" | Teal background, white icon |
| Concierge | Chat bubble SVG | "Chat" | Teal background, white icon |

The bottom nav uses the same SVG icons as the current sidebar, same teal accent color (`--accent-teal`), and the same active-state styling (teal background + white icon).

### Responsive Changes Table

| Element | Desktop | Mobile |
|---|---|---|
| Left sidebar (48px) | Visible — vertical icon rail | `display: none` |
| Bottom nav bar | `display: none` | Fixed bar, ~56px height, 3 tabs |
| Top bar action buttons | "+ Add Flight" + "Simulate Disruption" text buttons | Compact icon-only (plus icon + lightning icon), text hidden |
| Brand in top bar | "TravelCare AI" + "Autonomous Rescue Agent" subtitle | "TravelCare AI" only, subtitle hidden |
| Rescue package cards | Side-by-side (`flex-direction: row`) | Stacked vertically (`flex-direction: column`) |
| Route visual | 32px gaps between elements | 12px gaps, smaller font (11px) |
| Impact card grid | 2x2 grid | Stays 2x2 (compact enough on phone) |
| Modals (boarding pass, add flight) | Fixed 420px width | `width: calc(100vw - 16px); max-width: 420px` |
| Concierge chat chips | Row of 4 chips | Wrap to 2 rows, horizontal scroll on overflow |
| Content padding | `20px 24px` | `12px 16px` |
| Reasoning trail | Full width | Full width, font stays 13px (readable) |

## 3. Multi-Currency Conversion

### Current State
- Backend (`atlas_client.py`) already has `RATES` and `SYMBOLS` dicts and converts search results and rescue packages
- Frontend already reads `currency_symbol` and `price_converted` from API response for packages and search results
- **Gap:** Compensation card shows `eligible_payout_usd` (always USD), impact card shows hardcoded `$` values

### Proposed Changes

#### 3.1 Global Currency State
Add a `selectedCurrency` variable in `app.js`, initialized to `"USD"`. Updated when user selects currency in the Add Flight modal. Passed to `simulateDisruption()` API call (already done).

#### 3.2 Client-Side Rates Table
```js
const CURRENCY_RATES = { USD: 1.0, THB: 35.4, SGD: 1.34, MMK: 3500.0, EUR: 0.92 };
const CURRENCY_SYMBOLS = { USD: "$", THB: "฿", SGD: "S$", MMK: "Ks ", EUR: "€" };
```

Helper function:
```js
function convertCurrency(usdAmount) {
    const rate = CURRENCY_RATES[selectedCurrency] || 1.0;
    const symbol = CURRENCY_SYMBOLS[selectedCurrency] || "$";
    const converted = (usdAmount * rate).toFixed(2);
    return symbol + converted;
}
```

#### 3.3 Areas Converted

| Element | Current (hardcoded) | After conversion |
|---|---|---|
| Compensation card amount | `$250.00 USD` | `convertCurrency(250.00)` → e.g., `฿8,850.00` |
| Impact card: Call center cost | `$18.50` | `convertCurrency(18.50)` |
| Impact card: Compensation filed | `$250.00` | `convertCurrency(250.00)` |
| Impact card: Dining voucher | `$25.00` | `convertCurrency(25.00)` |
| Impact card: Total recovery value | `$293.50` | `convertCurrency(293.50)` |
| Rescue packages | Already converted by backend | No change |
| Search results | Already converted by backend | No change |

#### 3.4 Currency Indicator in Top Bar
Add a small badge showing the active currency (e.g., "USD", "THB") next to the Qwen-2.5 badge. Updates when `selectedCurrency` changes.

## 4. UI Polish

### 4.1 Smooth Animations

| Element | Implementation |
|---|---|
| Rescue package cards | Add `.fade-in-up` class via JS with staggered `setTimeout` (200ms, 400ms). CSS: `opacity: 0→1`, `transform: translateY(8px)→translateY(0)`, `transition: 0.4s ease` |
| Compensation card | Same `.fade-in-up` class, applied when card becomes visible |
| Simulate button spinner | Replace text-only "Activating..." with spinner SVG icon + "Activating..." text |
| Search loading skeleton | Replace text loading with 3 grey pulsing placeholder cards (`@keyframes skeleton-pulse { 0%,100% { opacity: 1 } 50% { opacity: 0.5 } }`) |

### 4.2 Boarding Pass Polish

| Element | Current | Proposed |
|---|---|---|
| Plane icon | Text `[ > ]` | Inline SVG plane path (simple aircraft silhouette) |
| Barcode | 40 random-height bars, random opacity | Generate from PNR string: iterate PNR characters, map each to a bar pattern (thick for '1' bits, thin for '0'). ~50 bars total. Looks like a real boarding pass barcode. |

### 4.3 Concierge Chat Polish

| Element | Current | Proposed |
|---|---|---|
| AI avatar | None — plain bubble | Small teal circle (28px) with bot SVG icon, positioned left of AI message bubbles |
| Timestamps | None | Small grey text (11px, `--text-light`) below each message, showing current time (e.g., "11:42 AM") |
| Typing indicator | Text "..." in a bubble | Three dots that bounce sequentially: `@keyframes typing-bounce { 0%, 60%, 100% { transform: translateY(0) } 30% { transform: translateY(-4px) } }`, staggered `animation-delay` per dot |
| Auto-scroll | `scrollTop = scrollHeight` (instant jump) | `scrollTo({ top: scrollHeight, behavior: 'smooth' })` |
| Chat chips on mobile | Static row | Horizontal scroll with `overflow-x: auto; flex-wrap: nowrap` |

### 4.4 Fare Lock Visual Timer — Circular Countdown Ring

Replace the current `14:59` text-only timer with an SVG circular countdown ring:

**Structure:**
- SVG circle (80px diameter, `r=34`, `stroke-width=4`)
- Background ring: `stroke="var(--border-amber)"`
- Progress ring: `stroke="var(--accent-teal)"`, `stroke-dasharray` = circumference (2π×34 ≈ 213.6), `stroke-dashoffset` decreases as time runs out
- Center text: `14:59` in JetBrains Mono, positioned absolute center
- `transform: rotate(-90deg)` so ring starts from top

**Color shifts by remaining time:**
- > 10 min: `var(--accent-teal)` (teal)
- 5–10 min: `var(--status-warning)` (amber)
- < 5 min: `var(--status-danger)` (red)

**JS update logic:**
```js
function updateFareLockRing(secondsRemaining, totalSeconds = 899) {
    const circumference = 2 * Math.PI * 34; // ~213.6
    const progress = secondsRemaining / totalSeconds;
    const offset = circumference * (1 - progress);
    ring.style.strokeDashoffset = offset;
    // Color shift
    if (secondsRemaining > 600) ring.style.stroke = 'var(--accent-teal)';
    else if (secondsRemaining > 300) ring.style.stroke = 'var(--status-warning)';
    else ring.style.stroke = 'var(--status-danger)';
}
```

Only shown on the FASTEST package card (same as current behavior — BEST VALUE card has no fare lock).

## Testing

### Manual Test Checklist
1. Open `http://localhost:8050` on desktop — verify no visual regression from file split
2. Add a flight, simulate disruption — verify packages, compensation, impact card all show in selected currency
3. Switch currency in Add Flight modal — verify top bar badge updates
4. Resize browser to mobile width (375px) — verify bottom nav bar appears, cards stack, modals go full-width
5. Tap bottom nav tabs — verify Rescue/Search/Concierge views switch correctly
6. Simulate disruption on mobile — verify fade-in animations, fare lock ring, stacked cards
7. Open concierge — verify AI avatar, typing dots, timestamps, smooth scroll
8. Click 1-Click Rebook — verify boarding pass with SVG plane and realistic barcode
9. Verify search skeleton loaders appear briefly before results

### No Automated Tests
This is CSS/JS polish work on a hackathon demo. Manual visual verification is sufficient.

## Assumptions
- The FastAPI server on port 8050 continues to serve `static/index.html` at `/`
- The `/static` mount already serves static files from the `static/` directory
- No backend changes needed — all currency conversion for compensation/impact is client-side
- The `.superpowers/` directory is added to `.gitignore`
