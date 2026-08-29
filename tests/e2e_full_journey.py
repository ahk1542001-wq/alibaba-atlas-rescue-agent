"""Full-journey browser E2E for the TravelCare AI pivot build.

Covers the whole demo use case in a real Chromium:
  1. Legacy Rescue destination empty state (opened explicitly from the
     beginner-friendly Trip Agent landing page)
  2. Add Flight modal (user-typed data, no prefills; MM passport default)
  3. Explicitly simulate disruption -> demo banner, reasoning trail, packages
     + visa badges, compensation card, and an honest unable-to-verify rights
     panel because Atlas Sandbox exposes no flight-status route
  4. Radar view + scan
  5. Concierge chat via the configured LLM or deterministic fallback
  6. Flight search results (typed route)
  7. Mobile viewport sanity
Plus an API-level provider-truth case: client-supplied CDG-BKK hints must not
manufacture EU261 when the connected provider exposes no flight-status route.
"""

import sys
import datetime

import httpx
from playwright.sync_api import sync_playwright, expect

BASE = "http://localhost:8050"
results = []

FLIGHT_DATE = (datetime.date.today() + datetime.timedelta(days=2)).strftime("%Y-%m-%d")


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
    page.click('[data-testid="nav-rescue"]')
    check("homepage loads with empty state", lambda: expect(
        page.locator("#empty-state h2")).to_contain_text("No active disruption"))
    check("health badge live status", lambda: expect(
        page.locator("#health-badge")).to_contain_text("ealthy"))

    # ---------- 2. add flight ----------
    def add_flight():
        page.click("#btn-add-flight")
        expect(page.locator("#add-flight-overlay")).to_be_visible()
        assert page.locator("#input-nationality").input_value() == "MM"
        assert page.locator("#input-flight-number").input_value() == "", \
            "flight number must not be prefilled"
        assert page.locator("#input-passenger-name").input_value() == "", \
            "passenger name must not be prefilled"
        page.fill("#input-flight-number", "TG303")
        page.fill("#input-flight-date", FLIGHT_DATE)
        page.fill("#input-passenger-name", "E2E Tester")
        page.click(".btn-af-add")
        expect(page.locator("#add-flight-overlay")).not_to_be_visible()
    check("add flight modal: typed inputs only, MM passport default", add_flight)

    # ---------- 3. simulate disruption ----------
    def simulate():
        page.click("#btn-simulate")
        expect(page.locator("#disruption-banner")).to_be_visible()
        expect(page.locator("#banner-title")).to_contain_text("DEMO CANCELLATION")
        expect(page.locator("#banner-sub")).to_contain_text(
            "policy-ranked options ready", timeout=30000)
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

    # ---------- claims autopilot panel (honest provider limitation) ----------
    def rights_panel():
        panel = page.locator("#rights-panel")
        expect(panel).to_be_visible(timeout=45000)  # waits for /assess incl Qwen
        sub = page.locator("#rights-sub").inner_text()
        assert "Unable to verify rights" in sub, \
            f"missing provider route must fail closed, got: {sub!r}"
        badge = page.locator("#rights-regime-badge")
        assert badge.inner_text().strip() == "", "no regime badge may be shown on BKK-RGN"
    check("Claims Autopilot panel: missing provider route fails closed", rights_panel)

    # ---------- provider-truth case via API (client hints are not truth) ----------
    def claims_provider_truth():
        response = httpx.post(
            f"{BASE}/api/claims/assess",
            json={"flight_number": "AF198", "date": FLIGHT_DATE,
                  "passenger_name": "E2E Tester",
                  "origin_airport": "CDG", "destination_airport": "BKK"},
            timeout=90.0,
        )
        assert response.status_code == 422, response.text
        assert response.json()["detail"] == \
            "Cannot determine true flight route from status."
        assert "EU261" not in response.text
    check("Claims API ignores client route hints and fails closed", claims_provider_truth)

    # ---------- radar ----------
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
    check("concierge replies via configured LLM or deterministic fallback", concierge)

    # ---------- 7. search ----------
    def search():
        page.click("[data-view='search']")
        expect(page.locator("#view-search")).to_be_visible()
        page.fill("#search-origin", "BKK")
        page.fill("#search-destination", "SIN")
        page.click(".btn-search")
        outcome = page.locator(
            "#search-results .search-result-card, "
            "#search-results .search-error")
        expect(outcome.first).to_be_visible(timeout=25000)
        if page.locator("#search-results .search-error").count():
            expect(page.locator("#search-results .search-error")) \
                .to_contain_text("Search failed")
        else:
            expect(page.locator("#search-results .search-result-card").first) \
                .to_contain_text("BKK")
    check("flight search renders Atlas offers or an honest unavailable state", search)

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
