# UX Enhancement Package — Takeover Handoff to Antigravity

> **Branch:** `ux/enhancements-u1-u5`  
> **HEAD:** see `git log --oneline main..HEAD`  
> **Base:** `main` @ `d58173e` (v2 merged, TRAVELCARE_BRAIN flag live, qwen_brain present)  
> **Spec:** `docs/V2_UX_ENHANCEMENTS.md` (authoritative)  
> **Tool contracts:** `docs/V2_QWEN_AGENT_MIGRATION_PACKAGE.md` §13  

---

## 1. What Is Complete

### U4 — i18n Foundation ✅ (commit `5f67673`)

| Deliverable | Status | Evidence |
|---|---|---|
| `static/i18n.js` | Complete | `applyLocale()`, `t(key)`, `toggleLocale()`, localStorage `travelcare.locale`, en↔zh cycle, `my` NOT selectable, missing-key fallback to en with console.warn |
| `static/i18n/strings.en.json` | Complete | Source of truth, all wave-1 surface keys (topbar, nav, views, safety labels, chips, map, timeline, cards) |
| `static/i18n/strings.zh.json` | Complete | Machine-drafted, `_meta.review_status: "machine_draft"`, full key parity with en |
| `static/i18n/strings.my.json` | Complete | Reserved slot, `_meta` only, zero translatable keys |
| `static/index.html` updates | Complete | `data-testid="locale-toggle"` in topbar, `data-i18n` on wave-1 surfaces, `data-i18n-nav` on sidebar/bottom-nav, `#i18n-machine-translated-note` footnote (hidden by default), i18n.js loaded BEFORE app.js |
| `static/styles.css` additions | Complete | `.btn-locale-toggle` styling, `.i18n-machine-note`, CJK font stack for `html[lang="zh-Hans"]` |
| `tests/test_v2_ux_i18n.py` | Complete | 23 hermetic tests, ALL GREEN under both flags |

**Gate evidence (U4):**
- `TRAVELCARE_BRAIN=legacy`: 23/23 U4 tests pass; full suite 680 passed, 5 pre-existing failures (see §4)
- `TRAVELCARE_BRAIN=qwen_agent`: 23/23 U4 tests pass
- `node --check` on all 3 JS files: clean
- All existing `data-testid` values byte-stable (canary selectors untouched)

### U5 — Prompt Chips ✅ (commit `5c38e04`)

| Deliverable | Status | Evidence |
|---|---|---|
| `static/index.html` updates | Complete | `#trip-prompt-chips` (`data-testid="trip-prompt-chips"`), `#rescue-prompt-chips` (`data-testid="rescue-prompt-chips"`), `#concierge-context-chips` (`data-testid="concierge-context-chips"`), existing canary chip testids preserved |
| `static/styles.css` additions | Complete | `.prompt-chip`, `.trip-prompt-chips`, `.rescue-prompt-chips`, `.concierge-context-chips`, focus-visible & active states |
| `static/trip.js` updates | Complete | `renderContextualTripChips(s)` renders contextual chips based on trip state (empty vs active trip), wires clicks to `submitGoal()`, subscribes to `TravelCareI18n.onLocaleChange()` |
| `static/app.js` updates | Complete | `renderRescuePromptChips()` renders suggestion-grade disruption recovery chips, `renderContextualConciergeChips()` provides contextual chat starters, both wire clicks through `sendQuickChat()` without gate bypass, subscribe to `onLocaleChange()` |
| `tests/test_v2_ux_chips.py` | Complete | 13 hermetic tests covering string table integrity, contextual derivation, suggestion-grade wording, gate-bypass prevention, canary testid immutability, and locale change subscription |

**Gate evidence (U5):**
- `TRAVELCARE_BRAIN=legacy`: 13/13 U5 tests pass; combined U4+U5 36/36 tests pass
- `TRAVELCARE_BRAIN=qwen_agent`: 13/13 U5 tests pass; combined U4+U5 36/36 tests pass
- `node --check` on all 3 JS files (`static/i18n.js`, `static/app.js`, `static/trip.js`): clean
- `scripts/security_check.sh`: ALL 6 SECTIONS PASS

---

## 2. What Remains (U1 → U2 → U3)

### U1 — Map Visualization ✅ (commit `1989c83`)

| Deliverable | Status | Evidence |
|---|---|---|
| `static/vendor/leaflet/*` | Complete | `leaflet.js` (144KB) + `leaflet.css` (14KB) vendored locally (BSD-2-Clause) |
| `static/map.js` | Complete | `TravelCareMap` module: coordinate registry, `resolve()` with BKK/DMK ambiguity support, solid vs estimated pin logic, tileerror fallback hook |
| `static/index.html` updates | Complete | `#trip-map-block` with `#trip-map` & `#btn-trip-map-toggle`, `#rescue-map-block` with `#rescue-map` & `#btn-rescue-map-toggle`, OSM & Leaflet visible attribution |
| `static/styles.css` additions | Complete | `.map-wrapper`, `.btn-map-toggle`, `.map-legend-bar`, `.solid-dot`, `.hollow-dot`, `.disrupted-dot`, `.rescue-dot`, `.map-badge-estimated` |
| `static/trip.js` + `static/app.js` | Complete | `renderTripMap(s)` in Trip view, `renderRescueMap(data)` in Rescue view, zero innerHTML sinks |
| `tests/test_v2_ux_map.py` | Complete | 11 hermetic tests covering vendoring, attribution words, coordinate honesty, ambiguity, and toggles |

**Gate evidence (U1):**
- `TRAVELCARE_BRAIN=legacy`: 11/11 U1 tests pass; combined U4+U5+U1 47/47 tests pass
- `TRAVELCARE_BRAIN=qwen_agent`: 11/11 U1 tests pass; combined U4+U5+U1 47/47 tests pass
- `node --check` on all 4 JS files: clean
- `scripts/security_check.sh`: ALL 6 SECTIONS PASS

---

## 2. What Remains (U2 → U3)

Per §0.2 sequencing: **U2 (timeline) → U3 (cards)**

### U2 — Day-by-Day Timeline (NOT STARTED)

**What to build:**
- Render from EXISTING `itinerary` skill payload (`sections` + per-section provenance)
- Vertical day-grouped timeline: one column per day, time-anchored segments
- Clock times via deterministic heuristic, labeled "estimates" (i18n key: `timeline.time_estimate`)
- Provenance coding MANDATORY and visual:
  - Atlas Sandbox segments (flights, real data) → solid treatment
  - "Suggestion only" segments → dashed border + label
  - Legend always visible
- Disruption/recovery events insert marked timeline interruptions — original segment stays visible, struck through, labeled `timeline.original_strikethrough`
- Localized day/time labels through §U4 string table (`timeline.day`, `timeline.disruption`, `timeline.recovery`)
- Empty state: honest "no itinerary yet" (`timeline.empty` key already exists)
- File scope: `static/index.html` (timeline container in trip-itinerary-block area), `static/trip.js`, `static/styles.css`
- Test: `tests/test_v2_ux_timeline.py` (hermetic — provenance coding, disruption rendering, localization hook presence)

### U3 — Suggestion Cards (NOT STARTED)

**What to build:**
- Cards render suggestion prose from Qwen-Agent brain (concierge answers, itinerary "suggestion only" sections, rescue rationale)
- Card structure: photo/placeholder + name + key fact + action
- Photo rule (HONESTY-CRITICAL):
  - Permitted: (1) owner-approved local assets under `static/assets/`; (2) labeled placeholder blocks ("no image available")
  - NEVER hotlink, NEVER fabricate, every image carries honest `alt` text
  - `alt` must describe true source: "illustrative placeholder", NOT "photo of X"
- Honesty footer on every card: "suggestion only" / source tag (`atlas_sandbox`, `deterministic engine`, `estimated`)
- Actions limited to: "Ask follow-up", "Add to trip plan" (local), "View on map" (§U1)
- **NO booking/payment CTAs of any kind**
- Degraded provider → cards fall back to deterministic legacy rendering, labeled
- File scope: `static/index.html`, `static/app.js`, `static/styles.css`, `static/assets/` (new, only if owner-approved images exist)
- Test: `tests/test_v2_ux_cards.py` (hermetic — provenance footer presence, no-payment CTA assertion, image source allow-list)

---

## 3. Architecture & Integration Notes

### How i18n works (for U5/U1/U2/U3)

```javascript
// Static HTML elements: add data-i18n="key.name" attribute
// i18n.js processes them automatically on applyLocale()

// Dynamic JS-rendered strings:
var label = t('chips.trip.visa');  // window.t() is globally available
var dayLabel = t('timeline.day', {n: dayNum});  // interpolation

// After dynamically rendering new DOM with data-i18n attrs:
TravelCareI18n.applyLocale();  // re-process

// Listen for locale changes to re-render dynamic content:
TravelCareI18n.onLocaleChange(function(locale) { reRenderMyStuff(); });
```

### Key files to know

| File | Purpose |
|---|---|
| `static/i18n.js` | Locale system — `t()`, `applyLocale()`, toggle, localStorage |
| `static/i18n/strings.en.json` | EN source of truth — add new keys here FIRST |
| `static/i18n/strings.zh.json` | ZH machine draft — must maintain key parity with en |
| `static/app.js` | Legacy views (rescue, search, concierge, radar) — 1194 lines |
| `static/trip.js` | Atlas Journey trip view — 3170 lines, strict DOM (no innerHTML with data) |
| `static/index.html` | Single-page shell — all 5 views + modals |
| `static/styles.css` | Design system (Refined Warm palette, Outfit + JetBrains Mono) |
| `tests/e2e_full_journey.py` | Canary (14 steps) — pins `data-testid` selectors, MUST stay green |
| `scripts/security_check.sh` | Security gate — vendored files must not trip it |

### Design system variables (for consistent styling)

```css
--bg-cream: #F6F0E4;     --bg-card: #FFFDF8;
--accent-teal: #12796B;   --accent-teal-dark: #0A574D;
--border-amber: #E7DAC2;  --text-dark: #231C13;
--text-muted: #75695A;    --status-danger: #BE4433;
--status-warning: #CE7F2B; --status-success: #2E7D5B;
--radius: 14px;           --radius-sm: 10px;
--font-display: 'Outfit'; --font-mono: 'JetBrains Mono';
--ease: cubic-bezier(0.22, 1, 0.36, 1);
```

---

## 4. Test Status & Known Issues

### Current dual-flag results (U4 commit)

| Flag | Passed | Failed | Notes |
|---|---|---|---|
| `TRAVELCARE_BRAIN=legacy` | 680 | 5 | Pre-existing failures (see below) |
| `TRAVELCARE_BRAIN=qwen_agent` | 23 (U4 only) | 0 | Full suite not re-run (same 5 expected) |

### Pre-existing failures (NOT caused by UX work)

All 5 are in `tests/test_v2_tools_wave1.py::test_safety_check_parity_with_legacy_skill`:
- `[SG-Level 1: Exercise normal precautions.]`
- `[TH-Level 2: Exercise increased caution.]`
- `[MM-Level 3: Reconsider travel.]`
- `[XX-Level 4: Do not travel.]`
- `test_safety_do_not_travel_propagates_unmutated`

These fail on `main` @ `d58173e` as well — they are a known v2 parity issue unrelated to UX.

### Fixed during handoff (U4 defect correction)

While verifying the branch, one latent U4 defect was found and corrected (commit follows U4):
- `static/index.html` mapped the safety card title `<h3 id="aj-safety-title">Safety check</h3>` to the WRONG i18n key `view.trip.help_disruption_q` ("What if my flight is disrupted?"), so `applyLocale()` would have overwritten "Safety check" with unrelated text in both locales.
- **Fix:** added a correct key `view.trip.safety_title` ("Safety check" / zh "安全检查") to BOTH `strings.en.json` and `strings.zh.json` (parity preserved) and remapped the element to it. The stale `help_disruption_q` key remains (still used by the Help accordion). All 23 U4 tests stay green under both flags after the fix.

### Canary status

`tests/e2e_full_journey.py` requires a running server at `localhost:8050`. Not re-run during U4 (hermetic-only gate). Antigravity should run it after each phase per the spec.

---

## 5. Gotchas & Lessons Learned

1. **JSON with Chinese quotes:** The `zh` table uses `\u201c` / `\u201d` (curly quotes) inside strings. If you write JSON via shell heredoc, these can get mangled to ASCII `"` breaking the JSON. Use Python `json.dump()` with `ensure_ascii=False` to write the zh table safely.

2. **data-testid immutability:** The canary pins exact `data-testid` values. NEVER rename them. New elements get NEW testids. The i18n system translates display text only — `data-testid` attributes are locale-independent.

3. **Script load order:** `i18n.js` MUST load before `app.js` and `trip.js` so `window.t()` is available. This is already wired in `index.html`.

4. **Security check with vendored files:** When vendoring Leaflet under `static/vendor/`, verify `scripts/security_check.sh` doesn't flag the minified JS as containing secrets. If it does, the whitelist in `scripts/banned_secret_patterns.txt` may need adjustment — but per §V.4, whitelist changes are a STOP item requiring owner approval.

5. **No innerHTML with data:** `trip.js` uses strict `textContent`/`createElement` DOM construction (XSS contract §9.3). Follow this pattern for all new rendering.

6. **Feature flag for map:** Per §U1, map render logic should be "flag-guarded behind a UI feature flag in code, default-on after gate."

7. **Locale toggle does NOT translate LLM prose:** Per §U4 LLM content boundary — the toggle translates UI chrome only. LLM-generated answers are NOT machine-translated client-side.

8. **Pre-existing test failures:** The 5 safety_check parity failures exist on main and are unrelated to UX. Don't try to fix them as part of this package.

---

## 6. Constraints (Inherited — DO NOT VIOLATE)

- **NO merge to main, NO push, NO deploy** without owner approval
- **ORIGINAL implementation only** — zero code/markup/CSS/images/text from the unlicensed reference repo (Khayi Zin AI)
- Only Leaflet (BSD-2) and OSM tiles (ODbL) are reused, with attribution honored in the UI
- **Honesty invariants:** numbers from live tooling only; simulations labeled; fail-closed
- **Bounded model calls:** ≤5 per live smoke, never bulk loops; OpenRouter fallback only (ModelScope is 429-exhausted)
- **Both flag paths must work:** all new UI renders correctly under `TRAVELCARE_BRAIN=legacy` AND `TRAVELCARE_BRAIN=qwen_agent`
- **Commit message prefix:** `v2(UX): …`
- **Exact-path `git add` only** — never `git add .`

---

## 7. Recommended Execution Order

1. **U5 (chips)** — cheapest win, builds on U4 i18n directly, keys already exist
2. **U1 (map)** — vendor Leaflet, heaviest DOM work, needs security check validation
3. **U2 (timeline)** — renders from existing itinerary payload, moderate complexity
4. **U3 (cards)** — depends on U1 for "View on map" action, do last

After each phase: run dual-flag pytest + canary, commit with gate evidence.

---

*Handoff produced by Jay (full-stack-engineer) on 2026-09-02. Branch left clean and buildable.*
