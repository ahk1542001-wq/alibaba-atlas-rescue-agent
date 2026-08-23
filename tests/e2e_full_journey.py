"""Full-journey browser E2E for the TravelCare AI pivot build.

Covers the whole demo use case in a real Chromium:
  1. Homepage empty state
  2. Add Flight modal (passport selector)
  3. Simulate Disruption -> banner, reasoning trail, packages + visa badges,
     compensation card, Claims Autopilot panel (regime, verdict, classification,
     entitlement), guardian/visa trail entries
  4. Claim letter reveal
  5. Appeal drafting via real Qwen
  6. Radar view + scan
  7. Concierge chat via real Qwen
  8. Flight search results
  9. Mobile viewport sanity
"""

import re
import sys

from playwright.sync_api import sync_playwright, expect

BASE = "http://localhost:8050"
results = []


def check(name, fn):
    try:
        fn()
        results.append(("PASS", name))
        print(f"PASS  {name}")
    except Exception as e:
        results.append(("FAIL", name))
        print(f"FAIL  {name}: {e}")


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.set_default_timeout(30000)

    # ---------- 1. homepage ----------
    page.goto(BASE)
    check("homepage loads with empty state", lambda: expect(
        page.locator("#empty-state h2")).to_contain_text("No active disruption"))
    check("health badge live status", lambda: expect(
        page.locator("#health-badge")).to_contain_text("ealthy"))

    # ---------- 2. add flight ----------
    def add_flight():
        page.click("#btn-add-flight")
        expect(page.locator("#add-flight-overlay")).to_be_visible()
        assert page.locator("#input-nationality").input_value() == "MM"
        assert page.locator("#input-flight-number").input_value() == "TG303"
        page.click(".btn-af-add")
        expect(page.locator("#add-flight-overlay")).not_to_be_visible()
    check("add flight modal + MM passport default", add_flight)

    # ---------- 3. simulate disruption ----------
    def simulate():
        page.click("#btn-simulate")
        expect(page.locator("#disruption-banner")).to_be_visible()
        expect(page.locator("#banner-title")).to_contain_text("CANCELLED")
    check("simulate disruption shows banner", simulate)

    check("reasoning trail fills", lambda: expect(
        page.locator("#trail-list .trail-item").last).to_be_visible(timeout=25000))

    # rescue packages + visa badges (MM passport on BKK-RGN route => CLEAR)
    def packages_ready():
        expect(page.locator(".package-card").first).to_be_visible(timeout=30000)
        n = page.locator(".package-card").count()
        assert n >= 2, f"expected >=2 package cards, got {n}"
        badges = page.locator(".visa-clear")
        assert badges.count() >= 1, "expected at least one visa-clear badge"
        assert "Visa-safe" in badges.first.inner_text()
    check("rescue packages render with visa-safe badges", packages_ready)

    check("compensation card visible", lambda: expect(
        page.locator("#compensation-card")).to_be_visible())

    # ---------- claims autopilot panel ----------
    def rights_panel():
        panel = page.locator("#rights-panel")
        expect(panel).to_be_visible(timeout=45000)  # waits for /assess incl Qwen
        expect(page.locator("#rights-regime-badge")).to_have_text("EU261", timeout=60000)
        verdict = page.locator("#rights-verdict").inner_text()
        assert "Strong claim" in verdict or "extraordinary" in verdict.lower(), verdict
        chip = page.locator("#class-chip").inner_text()
        assert chip in ("COMPENSABLE", "EXTRAORDINARY"), chip
        conf = page.locator("#class-confidence").inner_text()
        assert re.search(r"confidence \d+%", conf), conf
        reasoning = page.locator("#class-reasoning").inner_text()
        assert len(reasoning) > 30, "classification reasoning too short"
        ent = page.locator("#ent-amount").inner_text()
        assert "EUR" in ent or "Refund" in ent, ent
    check("Claims Autopilot panel: regime EU261 + classification + entitlement", rights_panel)

    def evidence_pack():
        ev = page.locator("#rights-evidence")
        expect(ev).to_be_visible()
        items = page.locator("#evidence-list li")
        assert items.count() >= 5, f"evidence checklist {items.count()} < 5"
        page.locator(".claim-letter-box summary").first.click()
        letter = page.locator("#claim-letter-text").inner_text()
        assert "261/2004" in letter and "request payment within 14 days" in letter
    check("evidence pack + regulation-cited claim letter", evidence_pack)

    # ---------- 4. appeal ----------
    def appeal():
        btn = page.locator(".btn-appeal")
        expect(btn).to_be_visible()
        btn.click()
        box = page.locator("#appeal-box")
        expect(box).to_be_visible(timeout=60000)  # real Qwen call
        text = page.locator("#appeal-letter-text").inner_text()
        assert len(text) > 100, f"appeal letter too short: {len(text)} chars"
    check("appeal letter drafted via live Qwen", appeal)

    # trail entries from DAG nodes
    def trail_nodes():
        trail = page.locator("#trail-list").inner_text()
        assert "VisaGuard" in trail, "missing VisaGuard trail entry"
        assert "Telegram Guardian" in trail, "missing guardian trail entry"
    check("trail logs VisaGuard + Guardian steps", trail_nodes)

    # ---------- 5. radar ----------
    def radar():
        page.click("[data-view='radar']")
        expect(page.locator("#view-radar")).to_be_visible()
        expect(page.locator("#radar-flights .radar-flight-item, #radar-flights > *").first).to_be_visible(timeout=10000)
    check("radar view lists monitored flights", radar)

    # ---------- 6. concierge ----------
    def concierge():
        page.click("[data-view='concierge']")
        expect(page.locator("#view-concierge")).to_be_visible()
        page.fill("#chat-input", "My flight was cancelled - what are my rights?")
        page.click("#btn-send")
        page.wait_for_selector(".typing-dots", state="detached", timeout=90000)
        reply = page.locator("#chat-messages .msg-bubble.msg-ai").last.inner_text()
        assert len(reply) > 40, f"concierge reply too short: {reply!r}"
    check("concierge replies via live Qwen", concierge)

    # ---------- 7. search ----------
    def search():
        page.click("[data-view='search']")
        expect(page.locator("#view-search")).to_be_visible()
        page.click(".btn-search")
        expect(page.locator("#search-results > *").first).to_be_visible(timeout=20000)
    check("flight search returns offers", search)

    # ---------- 8. mobile ----------
    def mobile():
        m = browser.new_page(viewport={"width": 375, "height": 812})
        m.goto(BASE)
        assert not m.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1"), \
            "horizontal overflow on 375px"
        expect(m.locator("#bottom-nav")).to_be_visible()
        m.close()
    check("mobile 375px: no overflow + bottom nav", mobile)

    browser.close()

fails = [n for s, n in results if s == "FAIL"]
print(f"\n{len(results) - len(fails)}/{len(results)} passed")
sys.exit(1 if fails else 0)
