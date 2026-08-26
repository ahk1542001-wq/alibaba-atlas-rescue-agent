"""G4 UI Gate — Playwright browser suites (§8 B1–B6 + edge flows).

Boot pattern: the G3 in-process app is served on 127.0.0.1:8050 by a
session-scoped uvicorn thread; each test installs a fresh
ProfileStore + TripOrchestrator (G3 harness pattern) so fakes keep the
UI suites deterministic — FakeAtlas for the sandbox plumbing, fake
web-intel fetchers for fresh/stale/offline visa states, stubbed LLM so
goal_intake uses its deterministic extractor.

Honesty: no screenshot or assertion is fabricated; every flow captures
browser console messages and fails on ANY console error/pageerror.
Screenshots land in screenshots/ (gitignored, created locally).
"""

import re
import socket
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import uvicorn
from playwright.sync_api import expect, sync_playwright

from main import app
from routers.v1.profile import set_profile_store
from routers.v1.trip import TripOrchestrator, set_trip_orchestrator
from services.profile_store import ProfileStore
from services.web_intel_client import WebIntelClient

BASE = "http://127.0.0.1:8050"
SHOTS = Path(__file__).resolve().parent.parent / "screenshots"
SHOTS.mkdir(exist_ok=True)

HAPPY_GOAL = ("I need to get to WiT Singapore, Marina Bay Sands, Sep 29-30 "
              "— plan my whole trip from Bangkok.")
AMBIGUOUS_GOAL = "I need to get to Singapore from Bangkok."
XSS_GOAL = ('I need to get to <script>window.__xss=1</script>Singapore from '
            'Bangkok <img src=x onerror="window.__xss2=1"> on 2026-09-29.')


# --- G3-pattern fakes ---------------------------------------------------------


async def _no_llm(*args, **kwargs):
    """Stubbed LLM: goal_intake falls back to its deterministic extractor."""
    return None


class FakeAtlas:
    """Deterministic Atlas stand-in for UI rendering."""

    async def search_flights(self, origin, destination, date_, passengers=1,
                             **kwargs):
        return [{
            "offer_id": "off_ui_sq_712", "airline_code": "SQ",
            "airline": "Singapore Airlines", "flight_number": "SQ712",
            "origin": origin, "destination": destination,
            "departure_time": f"{date_} 09:30",
            "arrival_time": f"{date_} 11:00",
            "duration_minutes": 150, "price_usd": 210.0, "currency": "USD",
        }, {
            "offer_id": "off_ui_tr_302", "airline_code": "TR",
            "airline": "Scoot", "flight_number": "TR302",
            "origin": origin, "destination": destination,
            "departure_time": f"{date_} 13:10",
            "arrival_time": f"{date_} 14:45",
            "duration_minutes": 155, "price_usd": 118.0, "currency": "USD",
        }]

    async def verify_fare(self, offer_id):
        return {"verified": True, "offer_id": offer_id,
                "verified_at": datetime.now(timezone.utc).isoformat()}

    async def create_booking_order(self, offer_id, passenger, **kwargs):
        return {"order_id": "ORD-UI1", "pnr": "ATLAS-UI7Q2Z",
                "status": "CONFIRMED", "offer_id": offer_id,
                "booking_timestamp": datetime.now(timezone.utc).isoformat()}


def _fresh_fetcher():
    async def fetch(query):
        return {"answers": [], "citations": [{
            "url": "https://www.example.org/visa-entry-rules",
            "title": "Entry and transit requirements (official-derived)",
            "retrieved_date": date.today().isoformat(),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "snippet_max280": "visa/entry requirements verified for route",
        }]}
    return fetch


def _stale_fetcher(days: int = 3):
    old_iso = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    async def fetch(query):
        return {"answers": [], "citations": [{
            "url": "https://www.example.org/visa-entry-rules",
            "title": "Entry and transit requirements (outdated)",
            "retrieved_date": old_iso[:10],
            "fetched_at": old_iso,
            "snippet_max280": "dated citation",
        }]}
    return fetch


async def _offline_fetch(query):
    raise ConnectionError("no network (simulated)")


# --- server + orchestrator fixtures ----------------------------------------------


@pytest.fixture(scope="session")
def app_server(tmp_path_factory):
    """Boot the real FastAPI app on 127.0.0.1:8050 in a thread."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if probe.connect_ex(("127.0.0.1", 8050)) == 0:
            pytest.fail("port 8050 is already in use — stop the other server "
                        "before running the G4 UI suites")
    store = ProfileStore(root=tmp_path_factory.mktemp("profiles"))
    set_profile_store(store)
    set_trip_orchestrator(TripOrchestrator(
        profile_store=store, atlas=FakeAtlas(),
        web_intel=WebIntelClient(ddg_fetcher=_fresh_fetcher(),
                                 tavily_api_key="", serper_api_key=""),
        llm_chat=_no_llm))
    config = uvicorn.Config(app, host="127.0.0.1", port=8050,
                            log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(150):
        try:
            if httpx.get(BASE + "/api/health", timeout=1.0).status_code == 200:
                break
        except Exception:
            time.sleep(0.1)
    else:
        pytest.fail("uvicorn did not become ready on 127.0.0.1:8050")
    yield
    server.should_exit = True
    thread.join(timeout=10)
    set_trip_orchestrator(None)
    set_profile_store(None)


@pytest.fixture
def install_orch(tmp_path):
    """Fresh per-test store + orchestrator (G3 harness pattern)."""

    def _install(fetcher=None, atlas=None):
        store = ProfileStore(root=tmp_path / "profiles")
        set_profile_store(store)
        orch = TripOrchestrator(
            profile_store=store,
            atlas=atlas or FakeAtlas(),
            web_intel=WebIntelClient(ddg_fetcher=fetcher or _fresh_fetcher(),
                                     tavily_api_key="", serper_api_key=""),
            llm_chat=_no_llm)
        set_trip_orchestrator(orch)
        return orch

    yield _install


# Zero console errors is part of EVERY flow (§8 smoke contract).
_THIRD_PARTY_FONT = re.compile(r"fonts\.(googleapis|gstatic)\.com")


@pytest.fixture(scope="module")
def ui_browser():
    """Chromium engine owned by THIS module.

    pytest-playwright's session-scoped engine keeps its asyncio loop
    "running" on the main thread (greenlet pump) for the whole pytest
    session, which breaks the repo's asyncio.run()-based suites that
    collect after this module. Scoping the engine to the module and
    stopping it in teardown restores a clean main thread.
    """
    with sync_playwright() as engine:
        browser = engine.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def tracked_page(app_server, ui_browser):
    errors = []

    def on_console(msg):
        if msg.type == "error" and not _THIRD_PARTY_FONT.search(msg.text):
            errors.append(msg.text)

    context = ui_browser.new_context()
    page = context.new_page()
    page.on("console", on_console)
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.set_default_timeout(15000)
    yield page
    context.close()
    assert not errors, f"browser console errors detected: {errors}"


# --- helpers ---------------------------------------------------------------------


def goto_trip(page):
    page.goto(BASE)
    page.click('[data-testid="nav-trip"]')
    expect(page.locator("#view-trip")).to_be_visible()


def start_goal(page, goal):
    page.fill('[data-testid="trip-goal-input"]', goal)
    page.click('[data-testid="trip-goal-submit"]')


def set_passport_via_api(value="MM"):
    resp = httpx.put(f"{BASE}/api/profile/victor/passport_country",
                     json={"value": value, "source": "user"}, timeout=10.0)
    assert resp.status_code == 200, resp.text


# --- B1: landing → goal chat submit → clarify chips appear → confirm --------------


def test_b1_goal_chat_clarify_chips_confirm(tracked_page, install_orch):
    install_orch()
    page = tracked_page
    goto_trip(page)

    # empty states before any trip
    expect(page.locator('[data-testid="trip-options-empty"]')).to_be_visible()
    expect(page.locator('[data-testid="trip-itinerary-empty"]')).to_be_visible()
    expect(page.locator('[data-testid="trip-dag-empty"]')).to_be_visible()

    # ambiguous goal pauses at scope clarification — chips stay reachable
    start_goal(page, AMBIGUOUS_GOAL)
    expect(page.locator('[data-testid="trip-chip-passport_country"]')) \
        .to_be_visible(timeout=20000)
    expect(page.locator('[data-testid="trip-chip-home_city"]')).to_be_visible()

    # keyboard-reachable submit path: focus the button, press Enter
    page.locator('[data-testid="trip-goal-submit"]').focus()

    # confirm a chip -> saved to profile server-side (source enforced user)
    page.fill('[data-testid="chip-input-passport_country"]', "MM")
    page.click('[data-testid="chip-confirm-passport_country"]')
    expect(page.locator('[data-testid="trip-chip-passport_country"]')) \
        .to_have_class(re.compile(r"confirmed"))
    expect(page.locator('[data-testid="chip-confirm-passport_country"]')) \
        .to_have_text("\u2713 saved to profile")
    prof = httpx.get(f"{BASE}/api/profile/victor", timeout=10.0).json()
    assert prof["identity"]["passport_country"] == "MM"

    # the goal echo rendered verbatim as inert text
    expect(page.locator('[data-testid="trip-chat"]')) \
        .to_contain_text(AMBIGUOUS_GOAL)
    page.screenshot(path=str(SHOTS / "g4_b1_clarify_chips.png"))


# --- B2 + B3: sandbox option cards → approval modal → PNR screen ------------------


def test_b2_b3_sandbox_options_approval_pnr(tracked_page, install_orch):
    install_orch()
    page = tracked_page
    set_passport_via_api("MM")
    goto_trip(page)

    start_goal(page, HAPPY_GOAL)

    # B2: option cards render the sandbox flights with provenance
    first_card = page.locator('[data-testid="trip-option-card"]').first
    expect(first_card).to_be_visible(timeout=25000)
    carriers = page.locator('[data-testid="trip-option-card"]')
    all_text = " ".join(
        carriers.nth(i).inner_text() for i in range(carriers.count()))
    assert "Singapore Airlines" in all_text, all_text
    assert "Scoot" in all_text, all_text
    expect(page.locator('[data-testid="sandbox-provenance"]').first) \
        .to_have_text("Atlas Sandbox data")
    # SGD primary / THB secondary currency display (§16.1)
    assert "S$" in all_text and "\u0e3f" in all_text, all_text
    # visa panel with fresh citations surfaced alongside
    expect(page.locator('[data-testid="trip-visa-panel"]')).to_be_visible()
    expect(page.locator('[data-testid="visa-fresh-chip"]')).to_be_visible()
    # approval banner appears (gate paused) — options stay inspectable behind it
    expect(page.locator('[data-testid="approval-open"]')).to_be_visible()
    page.screenshot(path=str(SHOTS / "g4_b2_option_cards.png"))

    # B3: approval modal → confirm → PNR screen
    page.click('[data-testid="approval-open"]')
    expect(page.locator('[data-testid="trip-approval-overlay"]')).to_be_visible()
    n_opts = page.locator('[data-testid="trip-approval-options"] button').count()
    assert n_opts == 2, f"expected 2 approval options, got {n_opts}"
    page.click('[data-testid="approval-approve"]')
    expect(page.locator('[data-testid="pnr-code"]')) \
        .to_have_text("ATLAS-UI7Q2Z", timeout=20000)
    expect(page.locator('[data-testid="pnr-status"]')) \
        .to_contain_text("CONFIRMED")
    expect(page.locator('[data-testid="pnr-monitor"]')).to_be_visible()
    expect(page.locator('[data-testid="pnr-provenance"]')) \
        .to_contain_text("Atlas Sandbox")
    page.screenshot(path=str(SHOTS / "g4_b3_pnr_screen.png"))

    # itinerary renders honesty chips (researched-mock hotels/activities)
    expect(page.locator('[data-testid="trip-itin-item"]').first) \
        .to_be_visible(timeout=20000)
    itin_text = page.locator('[data-testid="trip-itinerary"]').inner_text()
    assert "researched mock data (as_of" in itin_text, itin_text
    assert "\U0001f4a1 suggestion only" in itin_text or \
        "atlas sandbox record" in itin_text.lower(), itin_text


# --- B4: live DAG panel grows at the 1s polling cadence ----------------------------


def test_b4_dag_panel_node_growth_within_1s(tracked_page, install_orch):
    install_orch()
    page = tracked_page
    goto_trip(page)

    start_goal(page, AMBIGUOUS_GOAL)
    nodes = page.locator('[data-testid="trip-dag-node"]')
    expect(nodes.first).to_be_visible(timeout=20000)
    # scope pause: goal_intake + clarify_loop + scope_clarification recorded
    expect(page.locator('[data-testid="trip-dag-node"]')).to_have_count(3, timeout=10000)

    # resolving scope resumes the graph; the DAG must reflect the new nodes
    # within ~1s polling cadence
    page.click('[data-testid="scope-choice-flight_only"]')
    t0 = time.monotonic()
    expect(nodes).not_to_have_count(3, timeout=3000)
    elapsed = time.monotonic() - t0
    assert elapsed <= 1.6, f"DAG growth took {elapsed:.2f}s (> 1s cadence + slack)"
    # status strip carries latency telemetry
    expect(page.locator('[data-testid="trip-latency"]')) \
        .to_contain_text("ms total")
    page.screenshot(path=str(SHOTS / "g4_b4_dag_panel.png"))


# --- B5: profile editor — edit, save, masked passport display ----------------------


def test_b5_profile_editor_and_masked_passport(tracked_page, install_orch):
    install_orch()
    page = tracked_page
    goto_trip(page)

    # edit home_city
    page.click('[data-testid="profile-edit-home_city"]')
    page.fill('[data-testid="profile-input-home_city"]', "Bangkok")
    page.click('[data-testid="profile-save-home_city"]')
    expect(page.locator('[data-testid="profile-value-home_city"]')) \
        .to_have_text("Bangkok")

    # passport number is stored + displayed masked, never raw
    page.click('[data-testid="profile-edit-passport_no"]')
    page.fill('[data-testid="profile-input-passport_no"]', "MD1234567")
    page.click('[data-testid="profile-save-passport_no"]')
    expect(page.locator('[data-testid="profile-value-passport_no"]')) \
        .to_have_text("MD*****67")
    row_text = page.locator('[data-testid="profile-row-passport_no"]').inner_text()
    assert "MD1234567" not in row_text.replace("MD*****67", ""), row_text
    whole = page.content()
    assert "MD1234567" not in whole, "raw passport leaked into the DOM"

    # consent toggle round-trips through POST /api/profile/victor/consent
    page.check('[data-testid="profile-consent"]')
    expect(page.locator('[data-testid="profile-consent"]')).to_be_checked()

    # delete clears the field (never the file)
    page.click('[data-testid="profile-delete-home_city"]')
    expect(page.locator('[data-testid="profile-value-home_city"]')) \
        .to_have_text("\u2014")
    page.screenshot(path=str(SHOTS / "g4_b5_profile_editor.png"))


# --- B6: two-run memory — reload greets with remembered home_city -------------------


def test_b6_two_run_memory_greeting(tracked_page, install_orch):
    install_orch()
    page = tracked_page
    goto_trip(page)

    # run 1: teach the agent the home city
    page.click('[data-testid="profile-edit-home_city"]')
    page.fill('[data-testid="profile-input-home_city"]', "Bangkok")
    page.click('[data-testid="profile-save-home_city"]')
    expect(page.locator('[data-testid="profile-value-home_city"]')) \
        .to_have_text("Bangkok")

    # run 2: fresh page load — profile answers without re-asking
    page.reload()
    page.click('[data-testid="nav-trip"]')
    expect(page.locator('[data-testid="trip-greeting"]')) \
        .to_contain_text("Bangkok")
    expect(page.locator('[data-testid="trip-greeting"]')) \
        .to_contain_text("Welcome back")
    page.screenshot(path=str(SHOTS / "g4_b6_remembered_greeting.png"))


# --- scope clarification: exactly three choices, flight-only intent -----------------


def test_scope_three_choice_flow_and_flight_only(tracked_page, install_orch):
    install_orch()
    page = tracked_page
    set_passport_via_api("MM")
    goto_trip(page)

    start_goal(page, AMBIGUOUS_GOAL)
    choices = page.locator('.trip-scope-choice')
    expect(choices.first).to_be_visible(timeout=20000)
    assert choices.count() == 3, "scope clarification must offer exactly 3 choices"
    expect(page.locator('[data-testid="scope-choice-flight_only"]')) \
        .to_contain_text("Search flights only")
    expect(page.locator('[data-testid="scope-choice-flight_plus_booking"]')) \
        .to_contain_text("Atlas Sandbox")
    expect(page.locator('[data-testid="scope-choice-complete_trip"]')) \
        .to_contain_text("Complete trip")

    # flight-only: no hotel/activities surfaces anywhere
    page.click('[data-testid="scope-choice-flight_only"]')
    expect(page.locator('[data-testid="trip-status-pill"]')) \
        .to_have_text("completed", timeout=25000)
    expect(page.locator('[data-testid="trip-option-card"]').first).to_be_visible()
    # itinerary stays in its empty state; the DAG ran no leisure/booking nodes
    expect(page.locator('[data-testid="trip-itinerary-empty"]')).to_be_visible()
    dag_text = page.locator('[data-testid="trip-dag-list"]').inner_text()
    for forbidden in ("hotel_research", "activities_research", "itinerary",
                      "flight_book", "approve_booking"):
        assert forbidden not in dag_text, dag_text
    # no approval banner/modal surfaced on the flight-only intent
    expect(page.locator('[data-testid="trip-approval-banner"]')).to_be_hidden()
    page.screenshot(path=str(SHOTS / "g4_scope_flight_only.png"))


# --- degraded + stale visa warnings are visible --------------------------------------


def test_degraded_and_stale_visa_warnings(tracked_page, install_orch):
    # (a) offline web-intel -> degraded, baseline-only, visibly labeled
    install_orch(fetcher=_offline_fetch)
    page = tracked_page
    set_passport_via_api("MM")
    goto_trip(page)
    start_goal(page, HAPPY_GOAL)
    expect(page.locator('[data-testid="visa-degraded-warning"]')) \
        .to_be_visible(timeout=25000)
    expect(page.locator('[data-testid="visa-degraded-warning"]')) \
        .to_contain_text("baseline, unverified")
    page.screenshot(path=str(SHOTS / "g4_visa_degraded.png"))

    # (b) stale citations -> visible stale warning before any booking
    install_orch(fetcher=_stale_fetcher())
    set_passport_via_api("MM")
    page.goto(BASE)
    page.click('[data-testid="nav-trip"]')
    start_goal(page, HAPPY_GOAL)
    expect(page.locator('[data-testid="visa-stale-warning"]')) \
        .to_be_visible(timeout=25000)
    expect(page.locator('[data-testid="visa-stale-warning"]')) \
        .to_contain_text("stale")
    page.screenshot(path=str(SHOTS / "g4_visa_stale.png"))


# --- XSS probe: hostile goal renders as inert text ------------------------------------


def test_xss_goal_payload_renders_inert(tracked_page, install_orch):
    install_orch()
    page = tracked_page
    goto_trip(page)

    start_goal(page, XSS_GOAL)
    chat = page.locator('[data-testid="trip-chat"]')
    expect(chat).to_contain_text("<script>window.__xss=1</script>",
                                 timeout=20000)
    expect(chat).to_contain_text('onerror="window.__xss2=1"')
    # nothing executed, nothing injected as markup
    assert page.evaluate("window.__xss === undefined")
    assert page.evaluate("window.__xss2 === undefined")
    assert page.locator("#trip-chat script").count() == 0
    assert page.locator("#trip-chat img").count() == 0


# --- mobile 375px: trip view without horizontal overflow ------------------------------


def test_mobile_375_trip_view_no_overflow(app_server, ui_browser):
    errors = []
    context = ui_browser.new_context(viewport={"width": 375, "height": 812})
    m = context.new_page()
    m.on("console", lambda msg: errors.append(msg.text)
         if msg.type == "error" and not _THIRD_PARTY_FONT.search(msg.text)
         else None)
    m.on("pageerror", lambda exc: errors.append(str(exc)))
    try:
        m.goto(BASE)
        m.click('[data-testid="mnav-trip"]')
        m.wait_for_selector("#view-trip.active", timeout=10000)
        m.wait_for_selector('[data-testid="trip-goal-form"]', state="visible",
                            timeout=10000)
        assert not m.evaluate(
            "document.documentElement.scrollWidth > window.innerWidth + 1"), \
            "horizontal overflow on 375px trip view"
        expect(m.locator("#bottom-nav")).to_be_visible()
        expect(m.locator('[data-testid="mnav-trip"]')).to_be_visible()
        m.screenshot(path=str(SHOTS / "g4_mobile_375_trip.png"))
    finally:
        context.close()
    assert not errors, f"browser console errors detected: {errors}"


# --- UI completeness sweep (§8): every interactive element carries a testid ----------


def test_ui_completeness_sweep_testids(tracked_page, install_orch):
    """Every static interactive element must carry a data-testid; coverage
    per element is recorded in PLAN.md's G4 sweep table."""
    install_orch()
    page = tracked_page
    page.goto(BASE)
    selectors = ("button, input, select, textarea, a[href], summary, "
                 ".nav-icon, .bottom-nav-item")
    elements = page.query_selector_all(selectors)
    assert elements, "no interactive elements found — sweep broken"
    missing = []
    for element in elements:
        if not element.get_attribute("data-testid"):
            tag = element.evaluate("e => e.tagName")
            ident = (element.get_attribute("id")
                     or element.get_attribute("class") or "")
            missing.append(f"{tag}#{ident}")
    assert not missing, f"interactive elements without data-testid: {missing}"
