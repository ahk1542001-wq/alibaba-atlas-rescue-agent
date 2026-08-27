# ATLAS JOURNEY — Beginner-Friendly Trip UX Redesign Spec

**Date:** 2026-08-27
**Project:** TravelCare AI — Autonomous Flight Rescue Agent
**Branch / base commit:** `feature/trip-agent` @ `bc54833`
**Author:** Grace (Task #11 — audit + spec phase)
**Status:** Decision-complete spec for the implementer (Task #12)

**Hard constraints carried into implementation:**

1. SPEC PHASE produced this file only. No product code (`static/*`, `routers/*`, `services/*`) was touched here.
2. `static/app.js` is **FROZEN** — zero edits. The legacy sidebar + bottom nav keep working exactly as-is.
3. `tests/e2e_full_journey.py` pinned legacy selectors (`#btn-simulate`, `#disruption-banner`, `#banner-title`, `.package-card`, `.visa-clear`, `#compensation-card`, `#rights-panel`, `#rights-sub`, `#rights-regime-badge`, `#trail-list .trail-item`, `[data-view='radar']`, `[data-view='concierge']`, `#chat-input`, `#btn-send`, `.typing-dots`, `[data-view='search']`, `#search-origin`, `#search-destination`, `.btn-search`, `#bottom-nav`, `#empty-state h2`, `#health-badge`, add-flight modal ids) **MUST stay untouched and rendering**.
4. Legacy rescue / search / concierge / radar views are a **frozen canary** — no visual or behavioral changes.
5. All backend functionality and honesty contracts are preserved: Atlas Sandbox provenance sentence, `💡 suggestion only` / `researched mock data (as_of …)` chips, visa warnings never hidden, indicative-conversion labels.
6. XSS-safe DOM discipline: `createElement` / `textContent` only; never `innerHTML` with data.
7. Zero-console-error contract; the full 203+18 test suite must stay green.

---

## 0. Phase A Audit Findings

### 0.1 Method

Evidence was gathered from the **rendered** app at `http://127.0.0.1:8050` (Playwright, headless Chromium) plus full source review:

- Probe drove: landing → trip view → goal submit → clarify chips → scope 3-choice → options → approval modal → PNR → itinerary → DAG panel → profile editor → `simulate-disruption` → legacy views (search/radar/concierge/rescue) → mobile 375px.
- Screenshots captured to `/tmp/audit/` (01 landing … 20 mobile trip) + JSON dumps (`inventory_desktop.json`, `state_terminal.json`, `simulate_disruption.json`).
- Source read in full: `static/index.html` (483 lines), `static/trip.js` (1001 lines), `static/styles.css` (1902 lines), `routers/v1/trip.py` (874), `routers/v1/profile.py` (214), `routers/v1/skills.py`, `tests/test_ui_trip.py` (859), `tests/e2e_full_journey.py` (182).
- Runtime facts from the probe: 0 console errors, mobile 375px overflow = false, terminal trip had **12 DAG nodes, 6 flight options, 35 itinerary items**, booking ref `ATLAS-D9607B`, monitor armed.

### 0.2 Top findings (ranked by beginner-hostility)

| # | Finding | Evidence |
|---|---------|----------|
| A1 | **Wall-of-cards layout.** The trip view is one unstructured vertical wall: chat transcript, visa panel (with 6 raw citation URLs), approval banner, 6 option cards, 35-row itinerary — everything visible at once with no hierarchy. | screenshots 05/08 |
| A2 | **Engineering dashboard exposed.** Right rail shows a raw DAG with `skill_ref` names (`goal_intake`, `clarify_loop`, `visa_check`, `approve_booking`), per-node latencies, "18538 ms total", "at node: approve_booking". Beginners cannot parse this; it competes with the actual next action. | screenshot 02/08, `renderDag` in trip.js |
| A3 | **Jargon everywhere.** "PNR", "DAG", "ApprovalGate", "irreversible sandbox booking", raw statuses (`IDLE`, `AWAITING_APPROVAL`, `COMPLETED`) in the status pill, scope codes (`flight_only`, `flight_plus_booking`, `complete_trip`), skill names. | screenshots 02–07 |
| A4 | **Primary action buried.** The goal composer — the single most important control — sits at the **bottom** of the console, below status strip, chat, visa, approval, options and itinerary. | screenshot 02 |
| A5 | **Unranked, unlimited options.** 6 flight cards with no ranking reason, no "Show more" pattern; fare provenance chips exist but cards have identical visual weight. `date_note` warning chip overflows its container horizontally on desktop. | screenshot 05 |
| A6 | **No recovery surface.** After `simulate-disruption` the trip view renders nothing new (screenshot 09 identical to 07) even though the API returns a full recovery subgraph (`IngestionRadar` … `ClosedLoopVerified` — itself pure jargon). | simulate_disruption.json vs 09 |
| A7 | **Profile rail is a data grid.** 8 rows × Edit/Delete = 16 tiny buttons permanently visible; consent checkbox, source chips (`user`/`inferred`) and masked passport are shown as an engineering table, not a private drawer. | screenshot 08 |
| A8 | **Hidden / duplicated state.** The "remembered" greeting leaks stored fixture data ("Welcome back — planning from Shanghai again.") with no way to see or correct it; clarify answers appear both as chat bubbles and chips (duplicated). | screenshot 02 |
| A9 | **Competing actions per screen.** Chat input, chips, scope buttons, approval open/approve/reject, goal form, profile rows — often ≥4 interactive clusters visible simultaneously; no single primary action. | inventory_desktop.json |
| A10 | **Purposeless controls for beginners.** DAG live toggle, latency readout, node list, status pill with machine statuses — diagnostic value only. | trip.js renderStatusStrip/renderDag |
| A11 | **Live LLM ≠ test fakes.** On the live server, a goal without dates ("I need to get to Singapore from Bangkok") returns 422 `invalid_goal` ("could not be parsed"), while test fakes pause at clarification. The UI today shows this as a generic error. | probe run 1 |
| A12 | **Mobile rail stacking.** No overflow and bottom nav works, but the right rail stacks below the main column creating an extremely long scroll; Edit/Delete buttons are below comfortable touch size. | screenshot 20 |

### 0.3 Current inventory (what exists today)

**Views:** `view-rescue` (Rescue Hub), `view-search`, `view-concierge`, `view-radar`, `view-trip` (G4). Sidebar `nav-*` icons + mobile `bottom-nav` (`mnav-*`) — all frozen.

**Trip view surfaces:** `trip-greeting`, status strip (`trip-status-pill`, `trip-status-node`, `trip-latency`), chat log (`trip-chat`), clarify chips (`trip-clarify-chips` → `trip-chip-{field}` / `chip-input-{field}` / `chip-confirm-{field}`), scope choices (`trip-scope-choices` → `scope-choice-*`), visa panel (`trip-visa-panel` + `visa-fresh`/`visa-degraded`/`visa-stale` chips), approval banner (`trip-approval-banner` → `approval-open`), options (`trip-options` → `trip-option-card`, `trip-options-empty`), PNR screen (`trip-pnr-screen` → `pnr-code`/`pnr-status`/`pnr-monitor`/`pnr-provenance`), itinerary (`trip-itinerary` + `trip-itinerary-empty`, `itin-chip-llm`), error box (`trip-error`), goal form (`trip-goal-form`/`trip-goal-input`/`trip-goal-submit`/`trip-goal-loading`), DAG panel (`trip-dag-panel`/`trip-dag-list`/`trip-dag-live`/`trip-dag-empty` → `trip-dag-node`), profile editor (`trip-profile-editor`/`trip-profile-rows`/`trip-profile-empty` → `profile-edit`/`profile-save`/`profile-delete`/`profile-value`/`profile-row-{key}`/`profile-consent`), approval overlay (`trip-approval-overlay` → `approval-options`/`approval-note`/`approval-approve`/`approval-reject`).

**Interactive elements (desktop):** 5 sidebar nav icons, 3 bottom-nav items (hidden), top-bar badges + Add Flight + Simulate Disruption buttons, boarding-pass & add-flight modals, plus all trip surfaces above (≈40 focusable controls on a terminal trip screen).

### 0.4 Current Warm Travel design tokens (styles.css `:root`) — identity to preserve

| Token | Value | Role today |
|---|---|---|
| `--bg-cream` | `#F6F0E4` | warm parchment canvas |
| `--bg-card` | `#FFFDF8` | card surface |
| `--bg-inset` | `#FAF5EA` | inset surface |
| `--accent-teal` | `#12796B` | primary action (desaturated teal) |
| `--accent-teal-light` | `#DCEDE7` | selected/tint |
| `--accent-teal-dark` | `#0A574D` | hover/pressed |
| `--teal-ink` | `#0B4038` | deep teal text |
| `--border-amber` / `--border-amber-light` | `#E7DAC2` / `#F2E9D8` | warm borders |
| `--hairline` | `rgba(74,55,30,.10)` | hairlines |
| `--text-dark` / `--text-muted` / `--text-light` | `#231C13` / `#75695A` / `#A79A88` | text scale |
| `--status-danger(-bg)` | `#BE4433` / `#FBEBE6` | disruption/danger |
| `--status-warning` | `#CE7F2B` | attention |
| `--status-success(-bg)` | `#2E7D5B` / `#E7F2EB` | success |
| `--radius-lg/--radius/--radius-sm` | 20 / 14 / 10px | shape |
| `--shadow-sm/md/lg`, `--shadow-teal` | warm-tinted | elevation |
| `--ease` / `--spring` | `cubic-bezier(.22,1,.36,1)` / `(.34,1.4,.5,1)` | motion |
| `--font-display` / `--font-mono` | `'Outfit', …` / `'JetBrains Mono', …` | type (see Decision D1) |

The redesign **preserves the Warm Travel family** (cream canvas, desaturated teal, warm borders, warm shadows, ease curve) and introduces the ATLAS JOURNEY refinement tokens in §6 — mapped from these, not replacing them globally.

---

## 1. Information Architecture

### 1.1 The three destinations

Exactly **3 primary destinations**, reached from a new top-level trip navigation row inside `view-trip` (sidebar/bottom-nav unchanged):

| Destination | Purpose | Maps to today's |
|---|---|---|
| **Plan a trip** | Tell us what you need → choose options → review → confirm (steps 1–4). | goal form, chat, chips, scope choices, options, visa panel, approval overlay |
| **My trip** | Track a confirmed booking; recovery lives here when needed (step 5). | PNR screen, itinerary, monitor status, disruption recovery |
| **Help** | Short plain-language help: what Atlas Sandbox is, what approvals mean, how to change a plan, contact-free self-help. Static content card; no new backend. | (new; absorbs jargon explanations currently absent) |

**Profile & preferences** become a **drawer opened from the top bar** (new `aj-profile-drawer`, toggled by a new top-bar button `[data-testid="aj-profile-open"]` placed next to existing top-bar buttons — additive, legacy buttons untouched). No engineering dashboard: the DAG panel, latency readout, node list and raw status pill are **removed from the default UI** and folded into the "How this plan was made" disclosure (§5.5).

### 1.2 Surface mapping (existing → new IA)

| Existing surface | Disposition | New home |
|---|---|---|
| Goal form (`trip-goal-form`, bottom) | **Transformed** — becomes the hero of the start screen (top of Plan a trip). | Step 1 card, `[aj-step-1]` |
| Remembered greeting (`trip-greeting`) | **Renamed + sanitized** — "Welcome back." only; stored city never leaked into prose (it still pre-fills origin silently via profile). If profile has `home_city`, show it as an editable confirmed fact, not greeting text. | Step 1 facts summary |
| Chat log (`trip-chat`) | **Collapsed into a disclosure** ("Conversation so far") inside Step 1; step flow becomes the transcript of record. | Step 1 disclosure |
| Clarify chips (`trip-clarify-chips`) | **Transformed** into one-question-at-a-time question cards (§4). | Step 1 |
| Scope 3-choice (`trip-scope-choices`) | **Renamed** into the 3 starter choices on the start screen + editable "requested services" summary (§3). Codes stay `flight_only` / `flight_plus_booking` / `complete_trip` on the wire. | Step 1 |
| Visa panel (`trip-visa-panel`) | **Renamed** "Check entry requirements"; moved to Review step (always visible there when destination known) and to My trip. Raw citation URLs move into a **Sources** disclosure. | Steps 3 & 5 |
| Option cards (`trip-options`) | **Transformed** — max 3 ranked cards + "Show more", ranking reason per card (§5.4). | Step 2 |
| Approval banner + overlay (`trip-approval-banner`, `trip-approval-overlay`) | **Transformed** into Step 4 "Confirm booking" card/modal with plain-language consequence statement. | Step 4 |
| PNR screen (`trip-pnr-screen`) | **Renamed** — "Booking reference" inside My trip. The provenance sentence (`pnr-provenance`) stays verbatim. | Step 5 |
| Itinerary (`trip-itinerary`) | **Transformed** — day-by-day grouped, initially 6 items + "Show more" (Decision D4). | Step 5 |
| DAG panel (`trip-dag-panel`) | **Collapsed into disclosure** "How this plan was made" (§5.5). Not a dashboard. | Disclosure in Review/My trip |
| Profile editor (`trip-profile-editor`) | **Transformed** into the profile drawer (§8.7). | Drawer |
| Status pill / latency / node readout | **Removed** from default view. Machine status replaced by plain "What happens next" line (§5.1). Latency lives in the disclosure. | Disclosure |
| `trip-error` box | **Transformed** into state-specific inline messages (§9). Testid kept. | Everywhere |

**Legacy rescue/search/concierge/radar stay AS-IS** (frozen canary). The new AJ row renders only when `view-trip` is active and is additive markup — legacy DOM untouched.

---

## 2. Guided 5-Step Flow

One rail, five steps. **Only the current step is expanded.** Completed steps render as one-line compact summaries with an **Edit** button that re-opens that step (safe re-entry: editing a choice re-runs from that point; nothing downstream is silently discarded — downstream artifacts are marked "will be updated" before invalidation). Future steps are visibly disabled (muted, `aria-disabled`, not focusable).

| Step | Title (UI) | Expanded content | API interactions |
|---|---|---|---|
| 1 | **Tell us what you need** | Goal composer or starter choice, requested-services confirmation, clarification question cards, confirmed-facts summary | `POST /api/trip/start` `{goal_text, user_id}`; `POST /api/trip/{id}/clarify-answers` (fields `origin_city`/`dest_city`/`date_window`; also resumes `missing_route`/`missing_dates` failed trips); profile chips → `PUT /api/profile/{user_id}/{field}`; `GET /api/trip/{id}/state` polling (1s, epoch/seq race-safe) + `GET /api/trip/{id}/stream` SSE |
| 2 | **Choose your options** | Max 3 ranked flight cards + Show more; hotel/activity/transport sections only when requested; scope approval (`scope_clarification`) also resolves here when the goal was ambiguous | `GET …/state` (outputs.flight_search); approvals `{kind: scope_clarification}` → `POST /api/trip/{id}/approvals/{aid}` with `value.choice ∈ {flight_only, flight_plus_booking, complete_trip}` |
| 3 | **Review your plan** | Readable summary, editable sections, entry-requirements warning, total/range with currency, sandbox explanation | `GET …/state` (outputs.visa_check, options, itinerary preview) |
| 4 | **Confirm booking** | Immutable summary, price snapshot, passenger count, exact action approved, Approve / Change plan | approvals `{kind: approve_booking}` → `POST …/approvals/{aid}` with `value.option_id`; on `410 approval_expired` → expired state (§9) |
| 5 | **Track your trip** | Booking reference, day-by-day itinerary, next action, monitor status, disruption recovery when needed | `GET …/state` (outputs.booking, itinerary; `monitor_armed`); `GET …/simulate-disruption?allow_sim=1` only via existing top-bar button (legacy); recovery renders from subsequent state |

Step transitions are derived **only** from server state (never client-only): `current_state` / pending approvals / `outputs.*` determine which step is current. State → step mapping:

- no trip → Step 1 empty.
- running, no outputs → Step 1 working.
- pending `scope_clarification` → Step 1 (scope question card) or Step 2 header if facts already complete.
- `outputs.flight_search` present, no booking approval pending and not yet approved → Step 2.
- booking approval pending → Step 4 reached via Step 3 review (Step 3 auto-expands first).
- `outputs.booking` present → Step 5.
- disruption detected → Step 5 with Recovery panel (§8.6).

---

## 3. Start Screen (Step 1)

**Headline:** "Plan your trip."
**One-sentence explanation:** "Tell us where you need to go — we'll find options, show you the plan, and only book when you approve."

**Natural-language goal composer:** the existing `trip-goal-form`, restyled and repositioned as the hero. Placeholder: "e.g. I need to get to Singapore for a conference Sep 29–30 — plan my whole trip from Bangkok." Submit button label: **"Plan my trip"** (result-stating). Keep `data-testid="trip-goal-form|trip-goal-input|trip-goal-submit|trip-goal-loading"`.

**Exactly 3 starter choices** (buttons, each ≥44px, single tap):

| Choice | Initializes `RequestedServices` | Scope code sent |
|---|---|---|
| **Find a flight** | flights only | `flight_only` |
| **Find and book a flight** | flights + booking | `flight_plus_booking` |
| **Plan my complete trip** | flights + booking + hotel + activities (only what the goal/pipeline derives) | `complete_trip` |

Starter choices pre-fill a template goal text into the composer (still editable) and submit it. Requested services render as an **editable chip row** (`aj-requested-services`) under the composer: each chip removable; nothing is ever auto-added. **Custom goals infer services** from parsing; if scope is ambiguous the server issues `scope_clarification` and **only then** does the 3-choice card appear. The UI never auto-adds hotels, activities, transfers, monitoring, or notifications.

**Layout:**
- Desktop ≥1024px: composer left (~55%), **Living Journey Line preview** right (§7, empty→origin-only state), scope/starter choices below full-width.
- Mobile <768px: composer first, stacked choices, compact vertical step rail at top (5 dots + current label).

**Validation** (live server finding A11): on `422 invalid_goal`, show the validation-error state (§9) with plain guidance: "We couldn't work out the trip yet. Please include where you're going and roughly when — e.g. 'Bangkok to Singapore, Sep 29–30'." Never expose "parse" wording.

---

## 4. Clarification UX

**One focused question card at a time.** Card anatomy:

1. Short question (≤12 words): "Where are you travelling from?"
2. Why it's needed (one muted line): "Needed to search flights from the right airport."
3. Direct choices: quick-choice buttons when the backend suggests values (city/date presets); otherwise a single input.
4. Footer: **Back** (returns to previous fact/composer; never loses entered data) + **Save & continue** (primary).

Per-field mapping of today's chip mechanics:

| Today | New |
|---|---|
| `trip-chip-{field}` + `chip-input-{field}` + `chip-confirm-{field}` rendered all at once | One `aj-question-card` for the **first unanswered** field only; order: `origin_city` → `dest_city` → `date_window` → profile fields |
| Profile fields (`passport_country`, `home_city`, `expiry` — `PROFILE_CHIP_FIELDS`) → `PUT /api/profile/{user_id}/{field}` `{value, source:'user'}` | Same API, question card labelled "Save to your profile?" with explicit consent line (see §8.7) |
| Trip-shaping fields → `POST /api/trip/{id}/clarify-answers` `{answers:{field:value}}` | Unchanged API; card submits on Save & continue. On `missing_route`/`missing_dates` failed trips the same card resumes the trip via this endpoint (preserve trip.js `resumeFailedTrip` behavior) |

**Confirmed facts summary:** compact chip row (`aj-facts-summary`) under the step header — e.g. "From: Bangkok ✎ · To: Singapore ✎ · Dates: Sep 29–30 ✎". Each fact's pencil re-opens its question card. Facts persist across steps and are the only "transcript" beginners see; the full chat log remains in a collapsed disclosure.

Field-name safety: keep the existing discipline — never build selectors from server-supplied field names (trip.js F9 fix stays); question cards key off a static allow-list map.

---

## 5. Beginner Content Rules

### 5.1 Translations table (mandatory vocabulary)

| Never show | Always show as |
|---|---|
| PNR / PNR-shaped object | **Booking reference** (mono type, e.g. `ATLAS-D9607B`) |
| DAG / node graph / telemetry | **How this plan was made** (collapsed disclosure) |
| VisaCheckSkill / skill names | **Check entry requirements** |
| raw citations / URLs | **Sources** (collapsed list inside entry-requirements card) |
| staleness metadata | **Last checked** ("checked 2 min ago" style, from `as_of`) |
| machine statuses (`IDLE`, `AWAITING_APPROVAL`, `COMPLETED`) | **Booking status** — "Being planned" / "Waiting for your approval" / "Booked" / "Something changed — see recovery" |
| next-node readout ("at node: …") | **What happens next** — one sentence, e.g. "We're searching flights now. This usually takes a few seconds." |

### 5.2 Buttons

Result-stating labels only: **"Plan my trip", "Search flights", "Review plan", "Approve Sandbox booking", "Change flight", "Save & continue", "Show more", "Check entry requirements"**. **Banned:** Submit, Continue, Execute, Run, Proceed, OK, Done (as primary labels). **One primary action per screen** — exactly one Deep Teal filled button visible at a time; all others are secondary (outline) or tertiary (text).

### 5.3 Options

Max **3 ranked flight options initially** + **"Show more"** button revealing the rest in groups of 3. Each card shows: rank + concise ranking reason ("Best overall — direct flight, arrives before your event"), fare with currency, provenance chip (`💡 suggestion only` / `researched mock data (as_of …)` — exact existing chip contract preserved). Advanced filters, fare breakdown, provider diagnostics → collapsed disclosures per card.

### 5.4 Disclosures (collapsed by default)

Advanced filters · raw citations/Sources · provider diagnostics · **Agent Trace** (the old DAG, renamed, with latencies — for the curious only). Every disclosure is a native `<details>`-style button with `aria-expanded`, ≥44px target, content keyboard-reachable.

### 5.5 Never hidden (honesty contract, unchanged)

Visa warnings (degraded/stale chips always rendered, amber, above the fold of Review) · price changes · approval consequences ("Approving books this flight in the Atlas Sandbox. You can still change plans before you approve.") · provider degradation · booking uncertainty (the `date_note` clamp note: rendered as an amber inline note **inside** the card, wrapping — fixes A5 overflow). **Atlas Sandbox one-liner, always visible wherever booking is mentioned:** "Bookings are made in the Atlas Sandbox — a safe practice environment with researched mock data."

---

## 6. ATLAS JOURNEY Visual System

Foundation preserved: Warm Travel warmth, single teal accent family, warm shadows, `--ease`. Refinement — **no unrelated visual rewrite.** New tokens are additive under an `[data-aj]` scope; legacy `:root` tokens untouched so frozen views keep their identity.

### 6.1 Color tokens (new, scoped to `[data-aj]`)

| Token | Value | Usage | Maps from |
|---|---|---|---|
| `--aj-canvas` | `#FDF8F2` | Canvas Ivory — page/step background | refinement of `--bg-cream` |
| `--aj-ink` | `#183337` | Atlas Ink — text, nav, headings | refinement of `--text-dark` |
| `--aj-teal` | `#0F766E` | Deep Teal — primary actions, active journey line | refinement of `--accent-teal` |
| `--aj-teal-ink` | `#0A574D` | pressed/hover primary | reuse `--accent-teal-dark` value |
| `--aj-seafoam` | `#DDF3EE` | Seafoam — selected/completed step tints | refinement of `--accent-teal-light` |
| `--aj-amber` | `#E7A84D` | Sunline Amber — attention, provenance/source highlights, warnings | refinement of `--status-warning` |
| `--aj-amber-bg` | `#FBF3E4` | amber note background | new, warm-tinted |
| `--aj-coral` | `#D85C53` | Signal Coral — disruption & destructive actions **ONLY** | refinement of `--status-danger` |
| `--aj-coral-bg` | `#FBEBE9` | disruption note background | refinement of `--status-danger-bg` |
| `--aj-mist` | `#DCE7E4` | Border Mist — all borders/hairlines in AJ scope | refinement of `--border-amber` |
| `--aj-card` | `#FFFFFF` | White cards & dialogs | refinement of `--bg-card` |

**Rules:** green/teal only for verified completion; coral never for emphasis or branding; no purple gradients, neon, glassmorphism, or random decorative colors; the existing body radial gradients are suppressed inside `[data-aj]` (flat Canvas Ivory).

### 6.2 Typography

Keep the Inter/system stack direction: `--aj-font: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif` (Decision D1). **No new font dependencies.** Monospace (`--aj-mono: ui-monospace, 'JetBrains Mono', monospace`) **ONLY** for airport codes, flight numbers, times, prices, booking references. Headings: confident editorial (600–700 weight, tight tracking, no decorative effects). Body: **15–16px minimum**, 1.5–1.6 line-height. Muted text: Atlas Ink at 65% opacity minimum contrast-checked against Canvas Ivory.

### 6.3 Layout & components

Generous whitespace: 24–32px section gaps; consistent card padding 20–24px; **12px card radius** (`--aj-radius: 12px`); subtle `--shadow-sm`-style warm shadow, one border token (`--aj-mist`); **≥44px touch targets** everywhere; paragraphs ≤3 sentences; max content column 720px (readability); no decorative metrics, no badge overload, no emoji-dependent meaning (💡 chip survives as an established honesty mark with text beside it — never icon-only), no multiple gradients, no perpetual animation, no wall of cards (≤3 cards per visible section).

---


## 7. Signature Element — The Living Journey Line

The **only bold visual element** in the redesign. A route line connecting the 5 steps, rendered as inline **SVG** (path + 5 step nodes) styled with CSS — **no library**. Desktop: horizontal, spanning the step rail above the step cards. Mobile: compact vertical variant (5 dots connected by a 2px line) beside the current step label.

### 7.1 Geometry & rendering approach

- One SVG `<path>` per segment between consecutive step nodes (4 segments for 5 steps); each segment gets its own `data-testid="aj-line-seg-{1..4}"`.
- Each step node is a circle: empty = `stroke: --aj-mist, fill: --aj-card`; complete = `fill: --aj-teal`; current = `fill: --aj-card, stroke: --aj-teal` 2px.
- Segments "draw" via `stroke-dasharray` / `stroke-dashoffset` transition (duration 600ms, `--ease`), toggled by class only — no JS animation loops.
- Colors: muted base `--aj-mist`; completed segment Deep Teal `--aj-teal`; disrupted original segment muted-coral `--aj-coral` at 55% opacity.

### 7.2 Exact states

| State | Trigger (server-derived) | Rendering |
|---|---|---|
| `empty` | no trip | full line in `--aj-mist`, all nodes empty |
| `origin-only` | trip started, no step complete | node 1 filled teal; segment 1 begins drawing origin→destination preview (subtle dashed guide) |
| `drawing` | goal submitted, running | active segment animates once from previous node toward next (dashoffset transition); stops cleanly at node |
| `segments-complete` | step N finished | segments 1..N-1 solid teal; node N filled; future muted |
| `confirmed` | `outputs.booking` present | line reaches node 5; **ONE restrained pulse** on node 5 only — single 900ms scale 1→1.15→1 + opacity halo, `animation-iteration-count: 1`; then static |
| `disrupted` | disruption detected post-booking | original route kept, rendered muted-coral (NOT removed); a **branch path** (one extra quadratic SVG path, dashed teal) forks from the disrupted node toward a recovery node labelled "Recovery"; recovery approval turns the branch solid teal |
| `reduced-motion` | `prefers-reduced-motion: reduce` | all states static: completed = solid, drawing = already drawn, pulse = none, branch = dashed without motion. **Zero meaning loss** — every state is also distinguishable by node fill and step text, never by motion alone |

Implementation lives in a single `renderJourneyLine(state)` section of trip.js writing classes onto static SVG markup in index.html. Class vocabulary: `aj-line[data-state]` ∈ {empty, origin, drawing, s1, s2, s3, confirmed, disrupted}. Reduced motion handled purely in CSS (`@media (prefers-reduced-motion: reduce)`), preserving the existing global reduced-motion block in styles.css.

---

## 8. Screen Behavior Specs

### 8.1 Plan a trip — Step 1 (Tell us what you need)

Hero composer (§3) or starter choices; requested-services chip row (editable, removable, never auto-added); clarification question cards (§4) **only for missing facts** — facts already inferable from the goal or profile are not asked; confirmed-facts summary row; collapsed "Conversation so far" disclosure. One primary action: **Plan my trip** (pre-submit) / **Save & continue** (during clarify). Working state: "What happens next" line + drawing line segment.

### 8.2 Choose your options — Step 2

Max 3 ranked flight cards (§5.3): each shows rank reason, carrier/flight number (mono), times (mono), fare with currency, provenance chip, one secondary action **Choose this flight** plus disclosure "Details & sources". **Show more** reveals remaining options 3 at a time. Hotel / activity / transport sections render **only when present in requested services and returned by the pipeline** — never placeholders. One primary action: **Review plan** (enabled once a flight is chosen; choosing a card does not auto-advance past review).

### 8.3 Review your plan — Step 3

One readable summary card: route, dates, chosen flight, requested extras, **entry-requirements block** (visa verdict chip `visa-fresh|degraded|stale` kept verbatim — degraded/stale always amber and visible), **total or price range with currency** (indicative-conversion labels preserved), Atlas Sandbox one-liner. Every section has **Edit** (returns to its step). Collapsed disclosures: Sources, How this plan was made, fare breakdown. One primary action: **Approve Sandbox booking** (only when booking is in scope; for `flight_only` the primary is "Done — keep searching flights", which simply completes the plan).

### 8.4 Confirm booking — Step 4

Immutable summary (no editing from here; **Change plan** returns to Step 3): flight, price snapshot, passenger count, booking reference pending line, **exact action being approved** in one sentence ("Approving will book SQ 905, Bangkok → Singapore, Sep 29 in the Atlas Sandbox."). Buttons: **Approve Sandbox booking** (primary, keeps `approval-approve` testid) / **Change plan** (secondary, keeps `approval-reject` semantics — rejecting does not destroy the trip; it re-opens review). On `410 approval_expired` → expired-approval state (§9).

### 8.5 My trip — Step 5 (Track your trip)

Booking reference (mono, copy-friendly text, label "Booking reference" — `pnr-code` testid kept), **Booking status** plain line, **What happens next** line, monitor status ("We're watching this flight for changes" when `monitor_armed`), day-by-day itinerary (grouped by day; initial 6 items + **Show more** — Decision D4; `itin-chip-llm` honesty chip preserved), provenance sentence (`pnr-provenance` verbatim). Collapsed: How this plan was made, Sources. Disruption recovery renders **only when needed** (§8.6).

### 8.6 Recovery (inside My trip)

Triggered when state indicates disruption after booking (post `simulate-disruption` / poll shows recovery nodes). Renders: (a) **Original trip preserved** — the confirmed plan stays visible, muted-coral, never deleted; (b) **Replacement options** as separate cards, each with a plain suitability reason ("Leaves earlier, same airline, your seat class is available"); (c) **SEPARATE recovery approval** — approving a replacement is its own explicit action with its own consequence sentence; never auto-rebooked. Journey line shows the branch (§7.2 `disrupted`). Until approval, status reads "Something changed — review your options". Provider degradation or uncertainty in replacement data is shown, not smoothed over.

### 8.7 Profile drawer (from top bar)

Safe fields only (canonical §5/F5/F17 allowlist: `passport_country`, `home_city`, `preferred_origin_airport`, `cabin`, `diet`, `budget_range`, `display_currency`, `accessibility_notes`, `airlines_like`). No passport number, expiry, legal identity, or payment data is ever collected or stored. Each safe field: value, **Edit / Delete** actions at ≥44px. **Persistence consent:** the existing consent gate (`profile-consent`) is the first visible element with plain text: "Only save details I give you. You can delete anything at any time." No consent → fields are session-only, clearly labelled. **Explicit statement, always visible at the drawer footer:** "Passport number, payment details, and legal identity are not stored by this demo. Only safe preferences (passport country, home city, cabin, budget, and similar) are kept — with your consent." — aligned with `profile.py` boundary enforcement. Profile-field PUTs keep `source:'user'`; inferred values show a "Suggested by Atlas" tag with one-tap confirm/reject. *(R1 reconciled: prior draft mentioning masked passport numbers superseded).*

---

## 9. States & Accessibility

### 9.1 State matrix (every screen implements all applicable states)

| State | Trigger (real API condition) | Rendering |
|---|---|---|
| empty | no trip / no options yet / empty itinerary | friendly prompt + primary action; `trip-options-empty`, `trip-itinerary-empty`, `trip-dag-empty` testids preserved on new empties |
| loading | `POST /api/trip/start` in flight; poll between outputs | spinner + "What happens next" sentence; buttons disabled; ARIA live "polite" |
| success | outputs present, no warnings | normal render + success tint only on completed step |
| partial-degraded | `visa_data_stale_or_unverified` / degraded visa chip / provider hint in `error.hint` | amber note inline, content still shown, warning never dismissible-only |
| validation-error | `422 invalid_goal`, `missing_route`, `missing_dates` | inline message + what to change + retry keeps entered text (§3) |
| recoverable-provider-failure | `error.recoverable === true`, `provider_failure` | amber card "We hit a snag — try again" + **Try again** (re-POST same call); trip not abandoned |
| expired-approval | `410 approval_expired` | plain message "That approval link timed out." + **Get a fresh approval** (refetch state → new pending approval) |
| uncertain-booking | `fare_unverified`, `date_note` clamp, booking uncertainty fields | amber note quoting the uncertainty verbatim-in-plain-words; booking shown with "provisional" label |
| offline-fallback | `fetch` rejects / network error | "We can't reach Atlas right now. Your last saved view is below." + cached last state rendered + Retry |

Error envelopes come from `trip.py` §6 `{error:{code,message,recoverable,hint}}` and `profile.py` (consent/field errors); `_HINTS` values are translated through §5.1 vocabulary before display — raw codes never shown.

### 9.2 Accessibility contract

- **Keyboard-only completion** of the entire 5-step flow; DOM order = visual order; no keyboard traps except dialogs.
- Visible focus: 2px Deep Teal outline + 2px offset on every focusable element in `[data-aj]`.
- Semantic labels: real `<button>`/`<label>`/headings h2→h4 per step; question cards are `role="group"` with `aria-labelledby`.
- **ARIA live regions:** step header status + async results announce via `aria-live="polite"` (`aj-live`); disruption/recovery via `aria-live="assertive"`.
- Contrast: Atlas Ink on Canvas Ivory ≥ 12:1; teal button text white on `#0F766E` ≥ 4.6:1; amber text uses dark amber ink `#8A5A17` on `#FBF3E4` (never raw amber for text).
- Reduced motion per §7.2; honors existing global block.
- **No horizontal overflow at 360px** (verified in review loop; fixes A5 chip overflow by wrapping notes inside containers with `overflow-wrap: anywhere`).
- Dialogs (approval modal, profile drawer): **focus trap + focus restore** to trigger; Esc closes; backdrop click does not silently discard approval state (asks nothing, just closes).

---

## 10. Implementation Mapping

### 10.1 Files

| File | Change policy |
|---|---|
| `static/index.html` | **Additive only.** New `<section data-aj id="aj-shell">` inside `#view-trip`: AJ nav row (Plan a trip / My trip / Help), step rail + Journey Line SVG, 5 step card containers, profile drawer, Help card. All existing ids kept in place. |
| `static/trip.js` | Rework render layer inside the existing IIFE: new sections `renderAj`, `renderStepRail`, `renderJourneyLine`, `renderQuestionCard`, `renderOptionsRanked`, `renderReview`, `renderConfirm`, `renderMyTrip`, `renderRecovery`, `renderProfileDrawer`. Keep: `el()/clear()` discipline, poll/SSE lifecycle with epoch/seq, `confirmChip` routing (`PROFILE_CHIP_FIELDS` → profile PUT, else clarify-answers), `resumeFailedTrip`, `window.__tripId/__tripState/__tripRender` hooks (tests rely on them). |
| `static/styles.css` | **Additive** `[data-aj]` token block (§6) + AJ component styles + reduced-motion block. No edits to existing rules (legacy + canary frozen). |
| `static/app.js` | **FROZEN. No edits.** |
| `routers/*`, `services/*` | No changes needed — every behavior above is served by existing endpoints. |

### 10.2 data-testid scheme (new = `aj-*`; all existing pinned testids retained)

| Area | Testids |
|---|---|
| Shell | `aj-shell`, `aj-nav-plan`, `aj-nav-mytrip`, `aj-nav-help`, `aj-profile-open`, `aj-live` |
| Steps | `aj-step-1..5`, `aj-step-{n}-summary`, `aj-step-{n}-edit`, `aj-step-current` |
| Journey line | `aj-journey-line`, `aj-line-node-1..5`, `aj-line-seg-1..4`, `aj-line-branch` |
| Start | `aj-starter-flight-only`, `aj-starter-flight-booking`, `aj-starter-complete`, `aj-requested-services`, `aj-service-chip-{name}`, `aj-service-remove-{name}` |
| Clarify | `aj-question-card`, `aj-question-field`, `aj-question-input`, `aj-question-choices`, `aj-question-back`, `aj-question-save`, `aj-facts-summary`, `aj-fact-{field}`, `aj-fact-edit-{field}` |
| Options | `aj-option-card-{rank}` (also carries legacy `trip-option-card`), `aj-option-reason-{rank}`, `aj-option-select-{rank}`, `aj-show-more-options` |
| Review/Confirm | `aj-review-summary`, `aj-review-entry-req`, `aj-review-total`, `aj-review-sandbox-note`, `aj-confirm-summary`, `aj-confirm-price`, `aj-confirm-pax`, `aj-change-plan` (approval buttons keep `approval-approve`/`approval-reject`) |
| My trip | `aj-booking-ref` (with `pnr-code`), `aj-booking-status`, `aj-next-action`, `aj-monitor-status`, `aj-itinerary-day-{n}`, `aj-show-more-itinerary` |
| Recovery | `aj-recovery-panel`, `aj-recovery-original`, `aj-recovery-card-{n}`, `aj-recovery-reason-{n}`, `aj-recovery-approve`, `aj-recovery-reject` |
| Profile | `aj-profile-drawer`, `aj-profile-consent-note`, `aj-profile-field-{key}` (rows keep `profile-row-{key}` etc.), `aj-profile-privacy-note` |
| Disclosures | `aj-disclosure-trace`, `aj-disclosure-sources`, `aj-disclosure-chat`, `aj-disclosure-filters` |
| States | `aj-state-{empty|loading|validation|provider|expired|uncertain|offline}` |

### 10.3 Test plan (`tests/test_ui_trip.py`)

**Updated/extended (behavior unchanged on the wire):** `test_B1..B6` flows re-driven through new step cards — all existing pinned testids (`trip-goal-*`, `trip-chip-*`/`chip-*`, `scope-choice-*`, `approval-*`, `pnr-*`, `trip-option-card`, `trip-status-pill`, `visa-*`, `profile-*`, `trip-dag-*` empties, `itin-chip-llm`) continue to resolve; where a surface moved (e.g. DAG into disclosure), the test first opens the disclosure. F1–F10 (mobile/testid-sweep/XSS) extended with the `aj-*` inventory.

**NEW regressions (one per directive rule):**

| Test | Asserts |
|---|---|
| `test_AJ01_ia_three_destinations` | exactly 3 AJ nav items; no DAG dashboard visible by default |
| `test_AJ02_starter_choices_services` | 3 starters initialize requested services; no auto-add of hotel/activity/monitoring chips |
| `test_AJ03_one_question_at_a_time` | only one `aj-question-card`; Back preserves input; facts summary updates |
| `test_AJ04_max_three_options_show_more` | ≤3 `aj-option-card-*` initially; each has reason + fare + provenance chip; Show more reveals rest |
| `test_AJ05_vocabulary` | page text never contains "PNR", "DAG", "Submit", "Proceed"; contains "Booking reference", "What happens next" |
| `test_AJ06_honesty_never_hidden` | sandbox one-liner visible at review+confirm; degraded visa chip visible; date_note wraps (no overflow) |
| `test_AJ07_journey_line_states` | data-state transitions empty→origin→drawing→segments→confirmed (one pulse class); disrupted shows coral original + branch |
| `test_AJ08_recovery_separate_approval` | after simulate-disruption: original preserved, replacement reasons shown, separate approve action |
| `test_AJ09_profile_drawer_privacy` | drawer opens from top bar; consent gate first; masked passport only; privacy note present |
| `test_AJ10_states_matrix` | validation(422)/expired(410)/recoverable-provider/offline states each render their `aj-state-*` with retry path |
| `test_AJ11_a11y_keyboard` | full flow completable via Tab/Enter; dialogs trap+restore focus; `aj-live` announced |
| `test_AJ12_reduced_motion` | with emulateMedia reduce: line states static, pulse class never applied |
| `test_AJ13_legacy_canary` | e2e_full_journey.py pinned selectors all still present; legacy views byte-frozen (app.js hash) |

---

## 11. Design Review Loop Plan

**Viewport matrix:** 1440×900 (desktop primary), 768×1024 (tablet), 360×800 (phone worst case). Each screen of every step reviewed at all three.

**Skeptical-beginner checkpoints (reviewer must answer NO to all):**
1. Is there any word a first-time traveller wouldn't know (check against §5.1)?
2. Is there more than one filled primary button on screen?
3. Is any number/status shown without saying what it means or what to do next?
4. Would a user ever wonder "what just happened / what happens next"?
5. Is anything moving that doesn't communicate a state change?

**Mechanical checks each loop:** Chrome DevTools console (zero errors — font fetch noise excluded per existing convention), network (no unexpected calls; poll stops on terminal + view exit), keyboard-only walkthrough, focus-visible audit, horizontal overflow scan at 360px, reduced-motion emulation, touch-target measure (≥44px), contrast spot-checks (§9.2).

**Exit criteria:** zero high/medium usability findings across all checkpoints for two consecutive loops; all AJ regression tests green; full 203+18 suite green; canary legacy flow unchanged.

---

## 12. Risk / Preservation List (MUST NOT regress)

1. **B1–B6 intents** (start→clarify→scope→options→approval→PNR→itinerary, profile PUTs, resume-on-missing-route) — same API calls, same ordering guarantees.
2. **Honesty contracts:** Atlas Sandbox provenance sentence verbatim; `💡 suggestion only` + `researched mock data (as_of …)` chips; visa degraded/stale warnings never hidden; indicative conversions labeled; `date_note` clamp disclosed.
3. **Zero-console-error contract** across all views & view-switches (poll/SSE teardown on view exit preserved).
4. **XSS-safe DOM discipline:** `createElement`/`textContent` only; no selector construction from server field names; keep F9 guard.
5. **Frozen canary:** rescue/search/concierge/radar views + `static/app.js` byte-identical; `tests/e2e_full_journey.py` passes unmodified.
6. **Suite integrity:** 203+18 tests green; existing pinned testids in `test_ui_trip.py` all resolve (moved surfaces reachable via disclosures).
7. **Safety gates:** approval required before any booking POST; recovery approval separate; `simulate-disruption` only with `allow_sim=1` (403 otherwise); profile consent gate; passport always masked at boundary.
8. **Lifecycle:** poll interval 1s with epoch/seq race-safety; polling stops on terminal status and view exit; window hooks (`__tripId`/`__tripState`/`__tripRender`) retained.

---

## 13. Decisions Log (directive ambiguities resolved)

| # | Ambiguity | Decision |
|---|---|---|
| D1 | Directive §6 says "keep Inter/system stack, no new font deps", but the current app loads **Outfit + JetBrains Mono** (Google Fonts link in index.html), and legacy views are frozen. | Add AJ-scoped `--aj-font: 'Inter', -apple-system, …` applied only inside `[data-aj]`; **no new font links added** (existing link untouched so legacy keeps Outfit); mono uses the already-loaded JetBrains Mono stack for the §6.2 allowed cases only. Warm Travel identity survives via color/shape/motion, not the display font. |
| D2 | Live server returns `422 invalid_goal` for date-less goals, while unit-test fakes pause at clarification. Which behavior does the UI design for? | Design for **both**: the question-card flow handles fake-paused clarification; the validation-error state (§9, §3) handles live `invalid_goal` with plain retry guidance. Goal composer placeholder and Help card teach the "from/to/when" shape. |
| D3 | Recovery screen has no dedicated trip-view endpoint today; `simulate-disruption` returns a subgraph of jargon nodes. Where does Recovery get data? | Recovery renders from **continued state polling** after disruption (same `/state` + SSE lifecycle): replacement options surface via the pipeline outputs/approvals exactly like initial options; raw subgraph node names are never rendered (they live in the Agent Trace disclosure). No new backend required. |
| D4 | Itinerary cap: directive caps *flight options* at 3, but the probe showed a 35-row itinerary wall. | Apply the same beginner pattern to itinerary: **day-grouped, first 6 items + "Show more"**; no item is ever removed. (Flight options stay 3 + Show more per directive.) |
| D5 | New screens could collide with existing pinned testids. | **Dual-testid policy:** legacy pinned testids stay attached to equivalent elements inside the new components (e.g. `aj-option-card-{rank}` AND `trip-option-card`), so old and new tests pass simultaneously; new ids are strictly `aj-*`. |
| D6 | Directive says "remembered greeting" maps into the IA, but it leaks fixture data (A8). | Greeting reduced to "Welcome back."; remembered origin appears only as an **editable confirmed fact**, satisfying both preservation and privacy. |
| D7 | Where does the AJ nav live without touching frozen sidebar/bottom-nav? | Inside `#view-trip` as an in-view tab row (desktop) / compact step rail (mobile). Sidebar & bottom nav keep routing *to* the trip view unchanged. |
