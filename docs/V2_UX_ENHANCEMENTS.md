# V2 UX Enhancements Package — TravelCare AI Post-P5 UX Layer (OPTIONAL)

> **Status: DRAFT — NOT APPROVED FOR EXECUTION.**
> This is an OPTIONAL enhancement package. It may be executed ONLY after the core
> `V2_QWEN_AGENT_MIGRATION_PACKAGE.md` has completed and its **P5 gate has passed**
> (dual-flag green, dual canary 14/14, security gate green, honesty spot check clean).
> Until an owner explicitly says "run the UX package", this document is a plan, not a command.
>
> Target repo: `/Users/mac/Projects/code/alibaba-atlas-rescue-agent`
> Working branch: `v2/qwen-agent-migration` (the existing v2 branch — never `main`).

---

## §0 Scope & Sequencing

### 0.1 What this package is
A bounded set of UX upgrades that make the V2 Qwen-Agent product feel like a real
travel companion rather than a dashboard: a map, a timeline, rich suggestion cards,
a locale toggle (en + zh for the first release; see §U4), and prompt chips. Only the
GENERAL UX patterns are adapted from a proven Next.js + Leaflet award-winning MVP
reference — see §N: the reference project is UNLICENSED, so none of its code, markup,
CSS, images, or text may be copied. Everything is re-implemented originally into
TravelCare's actual stack:
**FastAPI backend + static single-page UI** (`static/index.html`, `app.js`, `trip.js`, `styles.css`).

### 0.2 Hard sequencing rules
1. **Gate dependency:** do not start any §U-item before the core package's P5 gate
   evidence exists in `docs/V2_STATUS.md` on `v2/qwen-agent-migration`.
2. **Order of execution:** U4 (i18n foundation) → U5 (chips) → U1 (map) → U2 (timeline) → U3 (cards).
   Rationale: i18n is the foundation layer every later surface must render through;
   chips are the cheapest win; map/timeline/cards are progressively heavier DOM work.
3. **Owner-absent protocol is INHERITED in full from the core package (§2):**
   - NO merge into `main`, NO `git push`, NO deploy/publish, NO payments/quota top-ups,
     NO account creation, NO external side effects beyond local runs and bounded model calls.
   - Commits on the v2 branch only, exact-path `git add` only, message prefix `v2(UX): …`.
   - On any blocker: write `docs/V2_STATUS.md`, commit it, stop. Never guess owner intent.
4. **UI freeze is lifted ONLY for this package, ONLY on the v2 branch, ONLY after P5.**
   The core package froze `static/` for the migration's sake; this package's explicit
   purpose is UI work. The canary `tests/e2e_full_journey.py` (14 steps) must still pass
   after every U-item — selectors it pins (`data-testid` attributes) are immutable.
5. **Each U-item is independently shippable:** each has its own file scope, tests, gate,
   and commit. If one item stalls 3 correction cycles, park it and continue with the rest.

### 0.3 Absolute constraints (inherited + UX-specific)
1. **LLM identity:** the ONLY sanctioned model is **Qwen3-235B** — ModelScope primary
   (`Qwen/Qwen3-235B-A22B-Instruct-2507`, `https://api-inference.modelscope.ai/v1`),
   OpenRouter fallback (`qwen/qwen3-235b-a22b-2507`). **NEVER Gemini, never any other
   model family.** All UX copy generation, translation drafting, and suggestion text flows
   through `services/llm_providers.py` — never a new provider path.
2. **Honesty is absolute:**
   - Every price, time, distance, duration, and flight number on any new surface must come
     from live tooling (Atlas Sandbox via `atlas-flight` CLI, deterministic engines).
   - Any coordinate/geolocation produced or suggested by the LLM MUST be visibly labeled
     **"estimated"** and rendered differently from tool-sourced coordinates.
   - Every simulated/demo state keeps its explicit label (simulated disruption, simulated
     guardian preview, degraded provider).
   - No real booking, no payments, ticketing stays not-activated (`TICKETING_ACTIVATION_REQUIRED`).
   - Fail-closed: on provider or tool failure the new UI surfaces show an honest, labeled
     degraded state — never a placeholder that looks real.
3. **Deterministic engines stay deterministic:** map pins, timeline rows, and card data are
   rendered FROM tool/engine output; the LLM may only decide WHEN to call tools and produce
   clearly-labeled suggestion prose.
4. **Bounded model calls:** same guardrail as the core package — a handful of calls per gate
   (≤5 per live smoke), never bulk loops.

---

## §U1 Map Visualization

**Intent:** render the trip as a spatial story — origin, destination, route, disruption
points, and rescue alternatives on an interactive map. Only the general UX pattern is
taken from the reference MVP; ALL map integration code is written originally for the
static UI (the reference project is unlicensed — nothing may be copied from it, see §N).

### Scope
- **Leaflet via CDN or vendored static assets only** (no build step, no bundler — the UI is
  plain static files served by FastAPI). Prefer vendoring `leaflet.css`/`leaflet.js` under
  `static/vendor/` so the app works offline-ish and passes the secret/dep checks unchanged.
  OpenStreetMap tiles are acceptable; tile failure must degrade to the plain route summary
  (labeled), never block the view. Leaflet is BSD-2-Clause licensed and OSM tiles are
  ODbL-licensed — both license/attribution requirements MUST be honored in the UI
  (visible "© OpenStreetMap contributors" attribution control and Leaflet attribution kept
  intact, never removed or obscured).
- Map surfaces: (a) Trip view — origin/destination/route line for the active trip;
  (b) Rescue view — disrupted flight + ranked rescue alternatives as candidate pins;
  (c) Search view (optional, lowest priority) — search origin/destination pair.
- **Coordinate sourcing rule (honesty-critical):**
  - Tool-sourced coordinates (airport data from existing product code) render as solid pins.
  - LLM-suggested coordinates (e.g., a venue resolved to a city) render as hollow/ghost pins
    with a visible **"estimated"** badge. Never silently promote an estimated pin to solid.
- `location_resolve` ambiguity (BKK/DMK style) renders BOTH candidate airports with a
  confirmation affordance; the map never picks one silently.
- Map container is collapsible and must not displace any canary-pinned element.

### File scope
`static/index.html` (map containers), `static/trip.js` + `static/app.js` (render logic,
flag-guarded behind a UI feature flag in code, default-on after gate), `static/styles.css`,
`static/vendor/leaflet/*` (new), `tests/test_v2_ux_map.py` (new, hermetic — asserts API
payload shapes and coordinate-labeling rules server-side), `docs/V2_LEARNINGS.md`.

### Gate
- Hermetic tests green (coordinate labeling, ambiguity rendering contract, degraded tile fallback).
- Full pytest green under BOTH `TRAVELCARE_BRAIN` values; canary 14/14 under both.
- Live smoke (≤2 model calls): one trip with an estimated pin visibly labeled, one with
  multi-airport confirmation. Screenshot evidence attached to the phase report only
  (screenshots never committed).

---

## §U2 Day-by-Day Timeline

**Intent:** replace wall-of-text itinerary rendering with a vertical day-by-day timeline:
one column per day, time-anchored segments, provenance-coded.

### Scope
- Render from the EXISTING `itinerary` skill payload (`sections` + per-section provenance).
  No new backend contract unless a field is genuinely missing; if so, add it additively in
  the qwen-brain tool layer only, never breaking `models/schemas.py` contracts.
- **Provenance coding is mandatory and visual:** Atlas Sandbox segments (flights, real data)
  get one visual treatment; "suggestion only" segments get another (dashed border + label).
  The legend is always visible.
- Disruption/recovery events (from `disruption_monitor` / `recovery_plan`) insert marked
  timeline interruptions — never silently rewritten history; the original segment stays
  visible, struck through, labeled.
- Localized day/time labels render through the §U4 string table from day one (no English
  hardcoding in timeline markup).
- Empty state: honest "no itinerary yet" affordance, never fabricated placeholder days.

### File scope
`static/index.html`, `static/trip.js`, `static/styles.css`, `tests/test_v2_ux_timeline.py`
(new, hermetic), `docs/V2_LEARNINGS.md`.

### Gate
- Hermetic tests green (provenance coding, disruption rendering, localization hook presence).
- Dual-flag pytest + dual canary green.
- Live smoke (≤2 model calls): one itinerary with mixed provenance renders coded correctly.

---

## §U3 Suggestion Cards with Photos

**Intent:** concierge and itinerary suggestions render as rich cards — title, body, optional
photo, explicit provenance label. Only the general card-grid UX pattern is inspired by the
reference MVP; card markup, styling, and rendering code are ORIGINAL — nothing is copied
from the reference (unlicensed — see §N).

### Scope
- Cards render suggestion prose produced by the Qwen-Agent brain (concierge answers,
  itinerary "suggestion only" sections, rescue rationale).
- **Photo rule (honesty-critical):** photos are NOT fabricated and NOT hotlinked from
  unverified sources. Permitted sources, in order: (1) owner-approved local assets committed
  under `static/assets/`; (2) clearly labeled placeholder blocks ("no image available").
  An LLM must never claim a photo depicts something it does not; every image carries an
  `alt` text describing its true source ("illustrative placeholder", not "photo of X").
- Every card carries its honesty footer: suggestion cards say "suggestion only";
  data cards show their source tag (`atlas_sandbox`, `deterministic engine`, `estimated`).
- Cards never contain booking/payment CTAs. The only actions are: "Ask follow-up",
  "Add to trip plan" (local plan, not a booking), "View on map" (§U1).
- Degraded provider → cards fall back to the deterministic legacy rendering, labeled.

### File scope
`static/index.html`, `static/app.js`, `static/styles.css`, `static/assets/` (new, only
owner-approved images), `tests/test_v2_ux_cards.py` (new, hermetic), `docs/V2_LEARNINGS.md`.

### Gate
- Hermetic tests green (provenance footer presence, no-payment CTA assertion, image
  source allow-list).
- Dual-flag pytest + dual canary green.
- Live smoke (≤3 model calls): one concierge answer renders as labeled suggestion cards.

---

## §U4 Locale Toggle — en + zh first release (my reserved, out of scope)

**Intent:** a first-class language toggle. The FIRST-RELEASE locales are **English (en)**
and **Chinese (zh)** only; **Myanmar (my) is an OPTIONAL later locale** — its string-table
slot is reserved from day one, but it is OUT OF SCOPE for the first release and ships
disabled/unpopulated. Implementation is a static i18n string-table approach: no framework,
no build step, consistent with the FastAPI + static UI. **English (`en`) is the source of
truth for every string.**

### 0) Architecture
- **String tables:** one `static/i18n/strings.<locale>.json` per locale (`en`, `my`, `zh`),
  flat key → string map, loaded via `fetch('/static/i18n/…')`. Keys are namespaced
  (`nav.rescue`, `topbar.simulate`, `safety.label.estimated`, …). Missing key → fall back
  to `en` value and log a warning (fail-closed honesty: never render raw keys, never
  invent translations at runtime).
- **Locale preference in `localStorage`** under key `travelcare.locale` (`en` | `zh`,
  default `en`; the `my` slot is reserved for the optional later locale but is not an
  active option in the first release). Toggle control in the topbar
  (`data-testid="locale-toggle"`, cycling en ↔ zh). Change persists immediately and
  re-renders without page reload.
- **Rendering mechanism:** `data-i18n` attributes on static elements; a single `applyLocale()`
  function in a new `static/i18n.js`. Dynamic JS-rendered strings go through `t(key)` —
  NO new user-visible literal English strings may be added outside the string tables.
- **LLM content boundary (honesty):** the toggle translates UI chrome only. LLM-generated
  answer prose is NOT machine-translated client-side. If localized LLM answers are ever
  wanted, that is a SEPARATE future item requiring the Qwen-Agent brain to emit the target
  locale — never a third-party translation API, never Gemini.
- **`zh` governance (owner cannot read Chinese — strict chain):** ALL `zh` strings are
  machine-drafted by **Qwen3-235B via the sanctioned provider chain only** and stored with
  `review_status: machine_draft` in the table header. The UI shows a visible
  **"machine-translated" footnote** whenever `zh` is active. `en` remains the source of
  truth; any `zh`/`en` conflict resolves to `en`. Documented future-review path: human
  review (community or professional) is REQUIRED before any marketing/public use of `zh` —
  until then `zh` is internal-testing grade only. No other translation source is permitted.

### 1) Surfaces translated FIRST (wave 1 — mandatory)
1. Prompt chips (§U5) — all chip labels.
2. View headers and section headers across all 5 views.
3. Safety labels and honesty badges: "estimated", "suggestion only", "Atlas Sandbox",
   "simulated", "degraded", `TICKETING_ACTIVATION_REQUIRED` messaging.
4. Topbar controls: locale toggle itself, "Your details", "+ Add Flight",
   "Simulate Disruption", health badge.
5. Sidebar navigation labels (`data-label` values are translated for display only —
   the attribute-based view switching logic is untouched).

Wave 2 (after wave 1 gate): empty states, form labels, error/degraded messages,
timeline day labels (§U2), card provenance footers (§U3).

### 2) Font & script note
zh uses system/Noto CJK fallback — verify no tofu boxes in the gate screenshots. When the
optional `my` locale is enabled in a later release, add a Myanmar-script-capable font then
(e.g., Noto Sans Myanmar on the existing Google Fonts link). Font additions must not break
the existing Outfit/JetBrains Mono brand pairing elsewhere.

### File scope
`static/i18n.js` (new), `static/i18n/strings.en.json`, `static/i18n/strings.my.json`,
`static/i18n/strings.zh.json` (new), `static/index.html`, `static/app.js`, `static/trip.js`
(literal-string extraction), `static/styles.css` (toggle control + CJK/Myanmar font sizing),
`tests/test_v2_ux_i18n.py` (new, hermetic), `docs/V2_LEARNINGS.md`.

### Gate & acceptance criteria
1. **Both first-release locales render:** automated browser check (Playwright, extending the
   canary harness pattern, NOT replacing it) cycles en ↔ zh and asserts that wave-1 surfaces
   render non-empty, non-key text in each locale, with zero raw keys and zero tofu nodes.
   The reserved `my` slot must not break anything: missing `my` keys fall back to `en`
   silently and are logged; `my` is NOT user-selectable in the first release.
2. Locale preference persists across reload via `localStorage`.
3. Missing-key fallback to `en` is tested and logged, never a blank or raw key.
4. `zh` table is flagged `review_status: machine_draft` in docs; the documented future
   review path (community/professional human review before any marketing use) is recorded,
   and the `zh` status checklist is appended to `docs/V2_STATUS.md`.
5. Canary 14/14 and dual-flag pytest stay green (no canary-pinned selector renamed —
   `data-testid` values are locale-independent and never translated).
6. Live smoke (≤2 model calls): none required beyond deterministic checks unless the owner
   asks for LLM-drafted `zh` regeneration.

---

## §U5 Prompt Chips

**Intent:** lower the blank-input barrier with contextual quick-action chips above the
chat/intake inputs, adapted from the reference MVP's suggestion pills.

### Scope
- Chips appear in: Trip intake input, Concierge chat input, (optionally) Rescue view when a
  disruption is active.
- Chip sets are CONTEXTUAL and deterministic: derived from current trip state (e.g.,
  "Check visa requirements", "What are my rights if cancelled?", "Find tomorrow's flights")
  — never LLM-invented chip text in v1 of this item. Chips render through the §U4 string
  table in the first-release locales (en, zh); `my` chip keys are reserved but out of scope.
- Clicking a chip inserts/sends that prompt through the EXISTING input pipeline — chips are
  input conveniences only; they bypass nothing (no approval gates skipped, no extra tool
  calls beyond what the typed prompt would trigger).
- Disruption-active chips (e.g., "Show rescue options") must not imply auto-booking;
  wording stays suggestion-grade in all locales.

### File scope
`static/index.html`, `static/app.js`, `static/trip.js`, `static/styles.css`,
`static/i18n/strings.*.json` (chip keys), `tests/test_v2_ux_chips.py` (new, hermetic),
`docs/V2_LEARNINGS.md`.

### Gate
- Hermetic tests green (contextual sets per state, locale coverage, no-gate-bypass assertion).
- Dual-flag pytest + dual canary green.
- Live smoke (≤2 model calls): one chip-driven concierge turn produces a labeled answer.

---

## §R Patterns to Reuse (from the Next.js + Leaflet reference MVP)

The reference MVP won awards; these are the transferable IDEAS, not its code — the
reference project (Khayi Zin AI) has NO LICENSE, so its code, assets, and visual design
must NOT be copied in any form (§N). Each pattern below must be re-implemented originally:

1. **Map as narrative anchor:** spatial context first, lists second. TravelCare adapts this
   with Leaflet in the Trip/Rescue views (§U1) — vanilla JS, no React, and ALL integration
   code written originally (only the BSD-2-Clause Leaflet library itself and ODbL OSM tiles
   are reused, with attribution honored in the UI).
2. **Day-segmented timeline with provenance color-coding:** the reference's itinerary
   scannability (§U2) transfers directly; TravelCare adds its honesty legend, which the
   reference did not need.
3. **Card-grid suggestion rendering with generous whitespace and one clear action per card**
   (§U3) — transfers well to static DOM generation in `app.js`.
4. **Chip-to-prompt affordance:** contextual quick-starters dramatically improve demo flow
   (§U5) — critical for judging/demo situations.
5. **Staggered reveal on load:** one orchestrated, subtle entrance animation (CSS-only,
   `animation-delay` ladders) rather than scattered micro-interactions; keep it ≤300ms total
   perceived and disable-friendly for reduced-motion.
6. **Typography discipline:** the reference pairs a distinctive display face with a quiet
   body face — TravelCare already has Outfit + JetBrains Mono; extend deliberately for
   Myanmar/zh scripts rather than replacing.
7. **State-driven UI:** every visual derives from one state object; TravelCare equivalent:
   every new surface renders purely from API response payloads, zero duplicated client state.
8. **Empty states as designed surfaces:** honest, branded, actionable — never blank.

## §N What NOT to Copy

0. **ZERO copying from the reference project (Khayi Zin AI) — it has NO LICENSE.**
   Its code, markup, CSS, images, text, assets, and visual design must NOT be copied in
   ANY form. ALL implementation in this package must be ORIGINAL work written for
   TravelCare. From the reference project, ONLY the GENERAL UX patterns listed in §R
   (ideas, not artifacts) inform the design. The only third-party artifacts used are
   properly-licensed open-source libraries — Leaflet (BSD-2-Clause) and OpenStreetMap tiles
   (ODbL) — whose attribution requirements MUST be visibly honored in the UI (OSM
   copyright/attribution control and Leaflet attribution kept intact).
1. **No Next.js, no React, no build pipeline.** The product is FastAPI + plain static files;
   everything is vanilla HTML/CSS/JS. No bundlers, no npm runtime deps in `static/`.
2. **No SSR, no API routes from the frontend layer** — all data comes through existing
   `routers/v1/*` endpoints; add no new public API surface unless a U-item explicitly says so.
3. **No third-party translation services and no non-Qwen models** for localization (§U4) —
   machine-drafted `zh` comes from Qwen3-235B via the sanctioned provider chain only.
4. **No live map tile dependence as a hard requirement** — tile failure must degrade honestly.
5. **No stock-photo scraping/hotlinking** (§U3) — only owner-approved local assets or labeled
   placeholders.
6. **No booking/payment UI of any kind** — no checkout flows, no payment buttons, no
   "buy now" patterns from the reference, even as placeholders.
7. **No silent data smoothing:** no interpolating prices, guessing times, or filling gaps the
   tools didn't return. The reference's polish must never become TravelCare's fabrication.
8. **No analytics/tracking scripts.** No external fonts beyond the existing Google Fonts link.
9. **No canary selector changes:** anything `tests/e2e_full_journey.py` pins stays byte-stable.

## §V Verification Gates (package-level close)

Execute in order after all selected U-items pass their individual gates:

1. **Dual-flag full suite:** `TZ=UTC .venv/bin/python -m pytest -q` under
   `TRAVELCARE_BRAIN=legacy` AND `TRAVELCARE_BRAIN=qwen_agent` — both green, both recorded.
2. **Dual canary:** `tests/e2e_full_journey.py` 14/14 under both flags.
3. **Locale sweep:** the §U4 browser locale-cycle check passes for en and zh on wave-1
   surfaces; the reserved `my` slot falls back to `en` without errors (my is out of scope
   for the first release).
4. **Security gate:** `bash scripts/security_check.sh` → ALL SECTIONS PASS (vendored Leaflet
   must not trip secret/dependency checks; whitelist adjustments are a STOP item if needed).
5. **Honesty sweep:** one of each — sandbox-labeled flight data, estimated-coordinate pin,
   simulated flow, degraded-provider fallback — each visibly labeled in the UI.
6. **No-payment assertion:** automated check that no new CTA triggers booking/payment paths;
   ticketing remains `TICKETING_ACTIVATION_REQUIRED`.
7. **Secrets sweep:** no key values anywhere new; `static/vendor/` contains no credentials.
8. **`docs/V2_STATUS.md` update:** items completed, gate evidence, `zh` review status,
   explicit statement: nothing merged, nothing pushed, `main` intact at `c6e7a4e`.
9. Commit: `v2(UX): post-P5 UX layer — map, timeline, cards, locale toggle (en+zh), chips`.
10. **STOP.** No merge, no push, no deploy. Handoff report to the owner.

---

*End of package. This document authorizes nothing until the owner explicitly starts it after P5.*
