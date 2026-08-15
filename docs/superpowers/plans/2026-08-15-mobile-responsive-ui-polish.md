# Mobile Responsive + Multi-Currency + UI Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split index.html into three files, add mobile responsive design with bottom nav, implement client-side multi-currency conversion, and apply UI polish across animations, boarding pass, concierge chat, and fare lock timer.

**Architecture:** Vanilla HTML/CSS/JS — no framework, no build step. FastAPI serves static files from `/static`. All changes are in `static/index.html`, `static/styles.css`, and `static/app.js`.

**Tech Stack:** HTML5, CSS3 (flexbox, @media queries, @keyframes), vanilla JavaScript (ES6+), SVG

**Spec:** `docs/superpowers/specs/2026-08-15-mobile-responsive-ui-polish-design.md`

---

## File Structure

| File | Responsibility |
|---|---|
| `static/index.html` | HTML markup only — sidebar, topbar, views, modals, overlays. Links CSS and JS. |
| `static/styles.css` | All CSS — `:root` variables, layout, components, `@media` queries, `@keyframes` animations |
| `static/app.js` | All JS — view switching, simulate disruption, rebook, chat, search, currency conversion, fare lock ring |

**Working directory:** `/Users/mac/Projects/code/alibaba-atlas-rescue-agent/`

**Server:** Already running on port 8050 with `--reload`

---

### Task 1: Extract CSS and JS into Separate Files

**Files:**
- Create: `static/styles.css`
- Create: `static/app.js`
- Modify: `static/index.html` (remove `<style>` and `<script>` blocks, add link/script tags)

- [ ] **Step 1: Create `static/styles.css`**

Copy the entire contents of the `<style>` block (lines 11-388 of current `index.html` — everything between `<style>` and `</style>`) into `static/styles.css`. Do not include the `<style>` or `</style>` tags themselves.

- [ ] **Step 2: Create `static/app.js`**

Copy the entire contents of the `<script>` block (lines 630-1082 of current `index.html` — everything between `<script>` and `</script>`) into `static/app.js`. Do not include the `<script>` or `</script>` tags themselves.

- [ ] **Step 3: Update `static/index.html`**

Replace the `<style>...</style>` block (lines 10-389) with:
```html
    <link rel="stylesheet" href="/static/styles.css">
```

Replace the `<script>...</script>` block (lines 629-1083) with:
```html
    <script src="/static/app.js"></script>
```

The final `index.html` should have this structure:
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TravelCare AI — Autonomous Flight Rescue</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/static/styles.css">
</head>
<body>
    <!-- ... all existing HTML body content stays unchanged ... -->
    <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 4: Verify no regression**

Run: `curl -s http://localhost:8050 | head -20`
Expected: HTML response with `<link rel="stylesheet" href="/static/styles.css">`

Open `http://localhost:8050` in browser. Verify:
- Dashboard loads with same styling
- "Simulate Disruption" works
- All three tabs (Rescue/Search/Concierge) switch correctly

- [ ] **Step 5: Commit**

```bash
git add static/index.html static/styles.css static/app.js
git commit -m "refactor: split index.html into styles.css and app.js"
```

---

### Task 2: Add Mobile Bottom Nav Bar

**Files:**
- Modify: `static/index.html` (add bottom nav HTML)
- Modify: `static/styles.css` (add bottom nav styles)
- Modify: `static/app.js` (update switchView to handle bottom nav)

- [ ] **Step 1: Add bottom nav HTML to `static/index.html`**

Add this markup just before the closing `</body>` tag (after the rescue timeline overlay, before the `<script>` tag):

```html
    <!-- MOBILE BOTTOM NAV -->
    <div id="bottom-nav">
        <div class="bottom-nav-item active" data-label="Rescue" data-view="rescue" onclick="switchView('rescue', this)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
            <span>Rescue</span>
        </div>
        <div class="bottom-nav-item" data-label="Search" data-view="search" onclick="switchView('search', this)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
            <span>Search</span>
        </div>
        <div class="bottom-nav-item" data-label="Concierge" data-view="concierge" onclick="switchView('concierge', this)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>
            <span>Chat</span>
        </div>
    </div>
```

- [ ] **Step 2: Add bottom nav CSS to `static/styles.css`**

Add at the end of the file:

```css
/* MOBILE BOTTOM NAV */
#bottom-nav {
    display: none;
    position: fixed;
    bottom: 0; left: 0; right: 0;
    background: var(--bg-card);
    border-top: 1px solid var(--border-amber);
    padding: 6px 0;
    z-index: 50;
    justify-content: space-around;
    box-shadow: 0 -2px 8px rgba(0,0,0,0.06);
}
.bottom-nav-item {
    display: flex; flex-direction: column;
    align-items: center; gap: 2px;
    cursor: pointer;
    color: var(--text-muted);
    transition: color 0.2s var(--ease);
    padding: 4px 12px;
}
.bottom-nav-item svg { width: 22px; height: 22px; }
.bottom-nav-item span { font-size: 10px; font-weight: 600; }
.bottom-nav-item.active { color: var(--accent-teal); }
.bottom-nav-item.active svg { stroke: var(--accent-teal); }
```

- [ ] **Step 3: Update `switchView()` in `static/app.js`**

Find the existing `switchView` function and replace it with:

```js
function switchView(view, el) {
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    document.querySelectorAll('.nav-icon').forEach(n => n.classList.remove('active'));
    document.querySelectorAll('.bottom-nav-item').forEach(n => n.classList.remove('active'));
    document.getElementById('view-' + view).classList.add('active');
    if (el) {
        el.classList.add('active');
        // Sync the other nav (sidebar <-> bottom nav)
        const viewName = el.getAttribute('data-view');
        document.querySelectorAll('[data-view="' + viewName + '"]').forEach(n => n.classList.add('active'));
    }
}
```

- [ ] **Step 4: Verify**

Open `http://localhost:8050` on desktop — bottom nav should be hidden (sidebar visible).
Resize to 375px width — bottom nav should appear.

- [ ] **Step 5: Commit**

```bash
git add static/index.html static/styles.css static/app.js
git commit -m "feat: add mobile bottom nav bar with tab switching"
```

---

### Task 3: Add Mobile Responsive @media Queries

**Files:**
- Modify: `static/styles.css` (add @media block)

- [ ] **Step 1: Add @media block to `static/styles.css`**

Add at the end of the file:

```css
/* ===== MOBILE RESPONSIVE ===== */
@media (max-width: 768px) {
    #sidebar { display: none; }
    #bottom-nav { display: flex; }
    #content { padding: 12px 16px; padding-bottom: 70px; }
    #brand-sub { display: none; }
    #btn-add-flight, #btn-simulate {
        font-size: 0;
        padding: 6px 8px;
        display: flex; align-items: center; justify-content: center;
    }
    #btn-add-flight::before { content: "+"; font-size: 16px; font-weight: 700; }
    #btn-simulate::before { content: "\26A1"; font-size: 14px; }
    #rescue-packages { flex-direction: column; }
    #route-visual { gap: 12px; }
    .route-label { font-size: 10px; width: 50px; }
    .route-codes { font-size: 12px; }
    #boarding-pass, .af-card {
        width: calc(100vw - 16px) !important;
        max-width: 420px;
    }
    .bp-airport-code { font-size: 22px; }
    .chat-chips { flex-wrap: nowrap; overflow-x: auto; }
    .msg-bubble { max-width: 85%; }
}
```

- [ ] **Step 2: Verify**

Open `http://localhost:8050`, resize browser to 375px width. Verify:
- Sidebar hidden, bottom nav visible
- "+ Add Flight" and "Simulate" buttons show icons only
- Package cards stack vertically after simulating disruption
- Modals go full width
- Content padding is tighter

- [ ] **Step 3: Commit**

```bash
git add static/styles.css
git commit -m "feat: add mobile responsive @media queries"
```

---

### Task 4: Multi-Currency Conversion

**Files:**
- Modify: `static/app.js` (add rates table, convertCurrency, update rendering)
- Modify: `static/index.html` (add currency badge in top bar)
- Modify: `static/styles.css` (add currency badge style)

- [ ] **Step 1: Add currency rates and helper to `static/app.js`**

Add at the top of `app.js` (after `let rescueData = null;`):

```js
// MULTI-CURRENCY
const CURRENCY_RATES = { USD: 1.0, THB: 35.4, SGD: 1.34, MMK: 3500.0, EUR: 0.92 };
const CURRENCY_SYMBOLS = { USD: "$", THB: "\u0E3F", SGD: "S$", MMK: "Ks ", EUR: "\u20AC" };
let selectedCurrency = "USD";

function convertCurrency(usdAmount) {
    const rate = CURRENCY_RATES[selectedCurrency] || 1.0;
    const symbol = CURRENCY_SYMBOLS[selectedCurrency] || "$";
    const converted = (usdAmount * rate).toFixed(2);
    return symbol + converted;
}

function updateCurrencyBadge() {
    const badge = document.getElementById('currency-badge');
    if (badge) badge.textContent = selectedCurrency;
}
```

- [ ] **Step 2: Add currency badge HTML to `static/index.html`**

In the topbar, add after the Qwen badge line (`<div id="qoder-badge">...</div>`):

```html
            <div id="currency-badge">USD</div>
```

Add CSS for it in `static/styles.css`:

```css
#currency-badge {
    font-size: 11px; font-weight: 600;
    color: var(--text-dark);
    background: var(--border-amber-light);
    padding: 3px 10px; border-radius: 20px;
}
```

- [ ] **Step 3: Update `submitAddFlight()` in `static/app.js`**

Find the `submitAddFlight` function. After the line `monitoredFlights.push(...)`, add:

```js
            const currencySelect = document.getElementById('input-currency');
            if (currencySelect) {
                selectedCurrency = currencySelect.value;
                updateCurrencyBadge();
            }
```

- [ ] **Step 4: Update `renderRescueData()` in `static/app.js`**

Find the compensation card rendering line that sets `comp-amount`. Replace:

```js
            document.getElementById('comp-amount').textContent = '$' + claim.eligible_payout_usd.toFixed(2) + ' USD';
```

with:

```js
            document.getElementById('comp-amount').textContent = convertCurrency(claim.eligible_payout_usd);
```

- [ ] **Step 5: Update `showImpactCard()` in `static/app.js`**

Replace the entire function:

```js
function showImpactCard(pkg) {
    const card = document.getElementById('impact-card');
    document.getElementById('impact-time').textContent = '190 min';
    document.getElementById('impact-cost').textContent = convertCurrency(18.50);
    document.getElementById('impact-comp').textContent = convertCurrency(250.00);
    document.getElementById('impact-voucher').textContent = convertCurrency(25.00);
    document.getElementById('impact-total').textContent = convertCurrency(293.50);
    card.classList.add('visible');
}
```

- [ ] **Step 6: Verify**

Open `http://localhost:8050`. Add a flight, select "THB" as currency. Simulate disruption. Verify:
- Compensation card shows `฿8,850.00` instead of `$250.00 USD`
- Impact card shows all values in THB
- Top bar shows "THB" badge

- [ ] **Step 7: Commit**

```bash
git add static/index.html static/styles.css static/app.js
git commit -m "feat: multi-currency conversion for compensation and impact card"
```

---

### Task 5: Smooth Animations — Fade-in, Skeleton Loaders, Spinner

**Files:**
- Modify: `static/styles.css` (add animation classes)
- Modify: `static/app.js` (apply animations in render functions)

- [ ] **Step 1: Add animation CSS to `static/styles.css`**

Add at the end:

```css
/* ANIMATIONS */
.fade-in-up {
    opacity: 0;
    transform: translateY(8px);
    animation: fadeInUp 0.4s var(--ease) forwards;
}
@keyframes fadeInUp {
    to { opacity: 1; transform: translateY(0); }
}
/* SKELETON LOADER */
.skeleton-card {
    background: var(--bg-card);
    border: 1px solid var(--border-amber);
    border-radius: var(--radius);
    padding: 14px 16px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    animation: skeletonPulse 1.5s ease-in-out infinite;
}
@keyframes skeletonPulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
}
.skeleton-line {
    height: 12px;
    background: var(--border-amber-light);
    border-radius: 4px;
    margin-bottom: 6px;
}
.skeleton-line.short { width: 60px; }
.skeleton-line.med { width: 120px; }
/* SPINNER */
.spinner {
    display: inline-block;
    width: 14px; height: 14px;
    border: 2px solid currentColor;
    border-top-color: transparent;
    border-radius: 50%;
    animation: spin 0.6s linear infinite;
    margin-right: 6px;
    vertical-align: middle;
}
@keyframes spin { to { transform: rotate(360deg); } }
```

- [ ] **Step 2: Update `renderPackages()` in `static/app.js`**

In the `renderPackages` function, after `container.appendChild(card);`, add fade-in. Replace `container.appendChild(card);` with:

```js
                container.appendChild(card);
                setTimeout(() => card.classList.add('fade-in-up'), idx * 200);
```

- [ ] **Step 3: Update compensation card in `renderRescueData()` in `static/app.js`**

After the line `document.getElementById('compensation-card').classList.add('visible');`, add:

```js
            document.getElementById('compensation-card').classList.add('fade-in-up');
```

- [ ] **Step 4: Update simulate button in `simulateDisruption()` in `static/app.js`**

Find `btn.textContent = 'Activating...';` and replace with:

```js
            btn.innerHTML = '<span class="spinner"></span>Activating...';
```

Find `btn.textContent = 'Simulate Disruption';` (at end of function) and replace with:

```js
            btn.innerHTML = 'Simulate Disruption';
```

- [ ] **Step 5: Update search loading in `searchFlights()` in `static/app.js`**

Find the line `results.innerHTML = '<div class="loading">Searching 140+ airlines via Atlas GDS...</div>';` and replace with:

```js
            results.innerHTML = '<div class="skeleton-card"><div><div class="skeleton-line med"></div><div class="skeleton-line short"></div></div><div class="skeleton-line short" style="width:40px"></div></div><div class="skeleton-card"><div><div class="skeleton-line med"></div><div class="skeleton-line short"></div></div><div class="skeleton-line short" style="width:40px"></div></div><div class="skeleton-card"><div><div class="skeleton-line med"></div><div class="skeleton-line short"></div></div><div class="skeleton-line short" style="width:40px"></div></div>';
```

- [ ] **Step 6: Verify**

Open `http://localhost:8050`. Simulate disruption — cards fade in staggered. Button shows spinner. Search shows skeleton cards briefly.

- [ ] **Step 7: Commit**

```bash
git add static/styles.css static/app.js
git commit -m "feat: smooth animations — fade-in, skeleton loaders, spinner"
```

---

### Task 6: Boarding Pass Polish — SVG Plane + Realistic Barcode

**Files:**
- Modify: `static/index.html` (replace text plane icon with SVG)
- Modify: `static/app.js` (update barcode generation)

- [ ] **Step 1: Replace plane icon in `static/index.html`**

Find the line:
```html
                    <div class="bp-plane-icon">[ > ]</div>
```
Replace with:
```html
                    <div class="bp-plane-icon">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="24" height="24"><path d="M17.8 19.2L16 11l3.5-3.5C21 6 21.5 4 21 3c-1-.5-3 0-4.5 1.5L13 8 4.8 6.2c-.5-.1-.9.1-1.1.5l-.3.5c-.2.5-.1 1 .3 1.3L9 12l-2 3-4-1-1.5 1.5L5 18l1 2.5L7.5 19l-1-4 3-2 3.5 4c.4.4 1 .5 1.5.2l.5-.3c.4-.2.6-.6.5-1.1z"/></svg>
                    </div>
```

- [ ] **Step 2: Update barcode generation in `showBoardingPass()` in `static/app.js`**

Find the barcode generation section (the `for` loop with `Math.random()`). Replace the entire barcode block:

```js
            const barcode = document.getElementById('bp-barcode');
            barcode.innerHTML = '';
            const pnr = ticket.pnr || 'ATLAS-XXXXXX';
            for (let i = 0; i < 50; i++) {
                const charCode = pnr.charCodeAt(i % pnr.length);
                const isThick = (charCode + i) % 3 === 0;
                const bar = document.createElement('div');
                bar.className = 'bp-bar';
                bar.style.width = isThick ? '4px' : '2px';
                bar.style.height = (24 + ((charCode + i) % 12)) + 'px';
                bar.style.opacity = (charCode + i) % 2 === 0 ? '1' : '0.4';
                barcode.appendChild(bar);
            }
```

- [ ] **Step 3: Verify**

Open `http://localhost:8050`. Add a flight, simulate disruption, click "1-Click Rebook". Verify:
- Plane icon shows as SVG aircraft silhouette
- Barcode looks like a real boarding pass barcode

- [ ] **Step 4: Commit**

```bash
git add static/index.html static/app.js
git commit -m "feat: boarding pass polish — SVG plane icon and realistic barcode"
```

---

### Task 7: Concierge Chat Polish — Avatar, Timestamps, Typing Dots, Smooth Scroll

**Files:**
- Modify: `static/styles.css` (add chat polish styles)
- Modify: `static/app.js` (update sendConciergeQuery)

- [ ] **Step 1: Add chat polish CSS to `static/styles.css`**

Add at the end:

```css
/* CHAT POLISH */
.msg-row { display: flex; gap: 8px; align-items: flex-start; }
.msg-row.msg-ai-row { align-self: flex-start; }
.msg-avatar {
    width: 28px; height: 28px; border-radius: 50%;
    background: var(--accent-teal);
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
}
.msg-avatar svg { width: 16px; height: 16px; color: white; }
.msg-content { display: flex; flex-direction: column; gap: 2px; }
.msg-time { font-size: 11px; color: var(--text-light); margin-top: 2px; }
.msg-bubble.msg-ai { margin-top: 0; }
.typing-dots { display: flex; gap: 4px; padding: 4px 0; }
.typing-dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: var(--text-light);
    animation: typingBounce 1.2s infinite;
}
.typing-dot:nth-child(2) { animation-delay: 0.15s; }
.typing-dot:nth-child(3) { animation-delay: 0.3s; }
@keyframes typingBounce {
    0%, 60%, 100% { transform: translateY(0); }
    30% { transform: translateY(-4px); }
}
```

- [ ] **Step 2: Update `sendConciergeQuery()` in `static/app.js`**

Replace the entire `sendConciergeQuery` function:

```js
async function sendConciergeQuery(query) {
    const container = document.getElementById('chat-messages');
    const now = new Date();
    const timeStr = now.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });

    // User message with timestamp
    const userRow = document.createElement('div');
    userRow.className = 'msg-content';
    userRow.style.alignSelf = 'flex-end';
    userRow.innerHTML = '<div class="msg-bubble msg-user">' + query + '</div><div class="msg-time" style="text-align:right">' + timeStr + '</div>';
    container.appendChild(userRow);

    // AI typing indicator with avatar
    const aiRow = document.createElement('div');
    aiRow.className = 'msg-row msg-ai-row';
    aiRow.innerHTML = '<div class="msg-avatar"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 1 3 3v1a3 3 0 0 1-3 3 3 3 0 0 1-3-3V5a3 3 0 0 1 3-3z"/><path d="M12 14c-4 0-7 2-7 5v3h14v-3c0-3-3-5-7-5z"/></svg></div><div class="msg-content"><div class="msg-bubble msg-ai"><div class="typing-dots"><div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div></div></div></div>';
    container.appendChild(aiRow);
    container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });

    try {
        const res = await fetch('/api/chat/concierge', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: query })
        });
        const data = await res.json();
        const replyTime = new Date().toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
        aiRow.querySelector('.msg-bubble').innerHTML = data.reply;
        var timeDiv = document.createElement('div');
        timeDiv.className = 'msg-time';
        timeDiv.textContent = replyTime;
        aiRow.querySelector('.msg-content').appendChild(timeDiv);
    } catch (err) {
        aiRow.querySelector('.msg-bubble').textContent = 'Sorry, I could not process your request right now.';
        console.error('Concierge failed:', err);
    }
    container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
}
```

- [ ] **Step 3: Verify**

Open `http://localhost:8050`. Click Concierge tab. Send a message or click a quick chip. Verify:
- AI messages have a teal avatar circle with bot icon
- User messages have timestamps
- Typing indicator shows three bouncing dots before reply
- Chat auto-scrolls smoothly

- [ ] **Step 4: Commit**

```bash
git add static/styles.css static/app.js
git commit -m "feat: concierge chat polish — avatar, timestamps, typing dots, smooth scroll"
```

---

### Task 8: Fare Lock Circular Countdown Ring

**Files:**
- Modify: `static/app.js` (update renderPackages and startFareLockCountdown)
- Modify: `static/styles.css` (add ring styles)

- [ ] **Step 1: Add ring CSS to `static/styles.css`**

Add at the end:

```css
/* FARE LOCK RING */
.farelock-ring {
    position: relative;
    width: 80px; height: 80px;
    flex-shrink: 0;
}
.farelock-ring svg { transform: rotate(-90deg); }
.farelock-ring-text {
    position: absolute; top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    font-family: 'JetBrains Mono', monospace;
    font-size: 14px; font-weight: 700;
    color: var(--accent-teal-dark);
}
.package-farelock {
    display: flex; align-items: center; gap: 10px;
    margin-top: 10px;
}
.package-farelock-label {
    font-size: 12px; color: var(--accent-teal-dark); font-weight: 600;
}
```

- [ ] **Step 2: Update fare lock HTML in `renderPackages()` in `static/app.js`**

In the `renderPackages` function, find the fare lock section for the FASTEST card. Replace the fare lock HTML block:

```js
                        (isFastest ?
                            '<div class="package-farelock"><div class="package-farelock-label">Fare Lock</div>' +
                            '<div class="farelock-ring">' +
                                '<svg width="80" height="80">' +
                                    '<circle cx="40" cy="40" r="34" fill="none" stroke="var(--border-amber)" stroke-width="4"/>' +
                                    '<circle class="farelock-progress" cx="40" cy="40" r="34" fill="none" stroke="var(--accent-teal)" stroke-width="4" stroke-dasharray="213.6" stroke-dashoffset="0" stroke-linecap="round" style="transition: stroke-dashoffset 1s linear, stroke 0.5s"/>' +
                                '</svg>' +
                                '<div class="farelock-ring-text" data-pkg="' + idx + '">14:59</div>' +
                            '</div></div>' : '') +
```

- [ ] **Step 3: Update `startFareLockCountdown()` in `static/app.js`**

Replace the entire function:

```js
function startFareLockCountdown() {
    if (fareLockInterval) clearInterval(fareLockInterval);
    let seconds = 899;
    const total = 899;
    const circumference = 2 * Math.PI * 34;

    fareLockInterval = setInterval(() => {
        seconds--;
        if (seconds < 0) { clearInterval(fareLockInterval); return; }

        const m = Math.floor(seconds / 60);
        const s = seconds % 60;
        const display = String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');

        document.querySelectorAll('.farelock-ring-text').forEach(el => el.textContent = display);

        const progress = seconds / total;
        const offset = circumference * (1 - progress);
        document.querySelectorAll('.farelock-progress').forEach(ring => {
            ring.style.strokeDashoffset = offset;
            if (seconds > 600) ring.style.stroke = 'var(--accent-teal)';
            else if (seconds > 300) ring.style.stroke = 'var(--status-warning)';
            else ring.style.stroke = 'var(--status-danger)';
        });
    }, 1000);
}
```

- [ ] **Step 4: Verify**

Open `http://localhost:8050`. Add a flight, simulate disruption. Verify:
- FASTEST card shows a circular ring with "14:59" in center
- Ring depletes as time counts down
- BEST VALUE card has no ring
- Color stays teal (amber/red only after 10/15 min)

- [ ] **Step 5: Commit**

```bash
git add static/styles.css static/app.js
git commit -m "feat: circular fare lock countdown ring with color shifts"
```

---

### Task 9: Final Manual Test

**Files:** None (verification only)

- [ ] **Step 1: Desktop full-flow test**

Open `http://localhost:8050` on desktop. Verify:
1. Dashboard loads with all styling intact
2. Add a flight with "THB" currency — top bar shows "THB" badge
3. Simulate disruption — spinner on button, cards fade in staggered, fare lock ring visible
4. Compensation card shows `฿8,850.00` (not `$250.00 USD`)
5. Impact card shows all values in THB
6. Click "1-Click Rebook" — boarding pass shows SVG plane, realistic barcode
7. Concierge tab — send message — avatar, typing dots, timestamp, smooth scroll
8. Search tab — search shows skeleton cards briefly, then results

- [ ] **Step 2: Mobile responsive test**

Resize browser to 375px width. Verify:
1. Sidebar hidden, bottom nav bar visible with 3 tabs
2. Action buttons are icon-only
3. Package cards stack vertically
4. Modals go full width
5. Tap bottom nav tabs — views switch correctly
6. Simulate disruption on mobile — fade-in, ring, stacked cards all work

- [ ] **Step 3: Verify git state**

```bash
git log --oneline -10
```
Expected: 8 new commits from Tasks 1-8
