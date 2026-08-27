"""G4 UI Gate + G4.5 ATLAS JOURNEY regressions — Playwright browser suites.

Boot pattern: the G3 in-process app is served on 127.0.0.1:8050 by a
session-scoped uvicorn thread; each test installs a fresh
ProfileStore + TripOrchestrator (G3 harness pattern) so fakes keep the
UI suites deterministic — FakeAtlas for the sandbox plumbing, fake
web-intel fetchers for fresh/stale/offline visa states, stubbed LLM so
goal_intake uses its deterministic extractor.

G4.5 note: the trip view is now the ATLAS JOURNEY shell (spec
2026-08-27-atlas-journey-trip-ux-redesign.md). B1–B6 INTENTS are
preserved 1:1 (same API calls, same ordering guarantees) but the moved
surfaces are reached through the AJ IA: options live behind the step-2
Edit pill, the visa panel behind step-3 Edit, the DAG behind the "How
this plan was made" disclosure, the profile editor inside the drawer.
AJ01–AJ13 are the 13 spec §10.3 regressions.

Honesty: no screenshot or assertion is fabricated; every flow captures
browser console messages and fails on ANY console error/pageerror.
Screenshots land in screenshots/ (gitignored, created locally).
"""

import hashlib
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
INVALID_DATE_GOAL = "Fly on February 30 2026"   # deterministic 422 trigger

# G4.5 / R2 sanitized static/app.js pin: zero injection sinks.
APP_JS_SHA256 = ("ecfe79839b726b7da61b38c91eced2a53a670d6a411c7f6bf3f9ba712de8d3"
                 "12")


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


class ManyAtlas(FakeAtlas):
    """5 offers so 'Show more' (>3 cap, spec §5.2) is exercisable."""

    async def search_flights(self, origin, destination, date_, passengers=1,
                             **kwargs):
        rows = []
        for i, (code, name, dep, arr, dur, price) in enumerate([
            ("SQ", "Singapore Airlines", "09:30", "11:00", 150, 210.0),
            ("TR", "Scoot", "13:10", "14:45", 155, 118.0),
            ("MI", "SilkAir", "07:05", "08:40", 155, 192.0),
            ("3K", "Jetstar Asia", "17:40", "19:20", 160, 139.0),
            ("TG", "Thai Airways", "21:15", "22:55", 160, 245.0),
        ]):
            rows.append({
                "offer_id": f"off_ui_{code.lower()}_{i}",
                "airline_code": code, "airline": name,
                "flight_number": f"{code}71{i}",
                "origin": origin, "destination": destination,
                "departure_time": f"{date_} {dep}",
                "arrival_time": f"{date_} {arr}",
                "duration_minutes": dur, "price_usd": price,
                "currency": "USD",
            })
        return rows


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
    """Chromium engine owned by THIS module (see G4 note on teardown)."""
    with sync_playwright() as engine:
        browser = engine.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def tracked_page(app_server, ui_browser):
    errors = []

    def on_console(msg):
        loc = msg.location or {}
        if msg.type == "error" and not _THIRD_PARTY_FONT.search(msg.text):
            errors.append(msg.text + (f" @ {loc.get('url')}:{loc.get('lineNumber')}"
                                      if loc.get("url") else ""))

    context = ui_browser.new_context()
    page = context.new_page()
    page.on("console", on_console)
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.set_default_timeout(15000)
    yield page
    context.close()
    assert not errors, f"browser console errors detected: {errors}"


def lenient_page(ui_browser):
    """Context for flows that INTENTIONALLY trigger HTTP errors (422/500/
    410) — Chromium's network-layer 'Failed to load resource' messages are
    expected there; every other console error still fails the flow."""
    errors = []
    context = ui_browser.new_context()
    page = context.new_page()

    def on_console(msg):
        if msg.type == "error" \
                and not _THIRD_PARTY_FONT.search(msg.text) \
                and "Failed to load resource" not in msg.text:
            errors.append(msg.text)

    page.on("console", on_console)
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.set_default_timeout(15000)
    return context, page, errors


# --- helpers ---------------------------------------------------------------------


def goto_trip(page):
    page.goto(BASE)
    page.click('[data-testid="nav-trip"]')
    expect(page.locator("#view-trip")).to_be_visible()


def start_goal(page, goal):
    page.fill('[data-testid="trip-goal-input"]', goal)
    page.click('[data-testid="trip-goal-submit"]')


def set_profile_field(field, value, user="victor"):
    resp = httpx.put(f"{BASE}/api/profile/{user}/{field}",
                     json={"value": value, "source": "user"}, timeout=10.0)
    assert resp.status_code == 200, resp.text


def set_passport_via_api(value="MM"):
    set_profile_field("passport_country", value)


def preset_passport_home():
    set_profile_field("passport_country", "MM")
    set_profile_field("home_city", "Bangkok")


def answer_chip(page, field, value, saved_text=None):
    """Answer the currently-shown one-at-a-time question card for `field`.

    AJ semantics: a confirmed card is replaced on the next render (answered
    questions never re-ask), so the DURABLE confirmation signals are the
    confirmed fact in the facts summary and the card clearing the way.
    """
    page.fill(f'[data-testid="chip-input-{field}"]', value)
    page.click(f'[data-testid="chip-confirm-{field}"]')
    # durable: the answer becomes an editable confirmed fact
    expect(page.locator(f'[data-testid="aj-fact-{field}"]')) \
        .to_contain_text(value, timeout=15000)
    expect(page.locator(f'[data-testid="aj-fact-{field}"]')) \
        .not_to_contain_text("answer needed")
    # durable: the card disappears — the flow moves to the next question
    expect(page.locator(f'[data-testid="chip-input-{field}"]')) \
        .to_be_hidden(timeout=15000)


def answer_date_then_scope(page, date_value="Sep 29-30"):
    """With passport/home pre-set, the only outstanding question is the
    date — answering it surfaces the 3-choice scope card."""
    expect(page.locator('[data-testid="chip-input-date_window"]')) \
        .to_be_visible(timeout=20000)
    answer_chip(page, "date_window", date_value, "\u2713 added to trip")
    expect(page.locator('[data-testid="scope-choice-flight_only"]')) \
        .to_be_visible(timeout=20000)


def open_trace(page):
    page.click('[data-testid="aj-disclosure-trace"]')
    expect(page.locator("#aj-trace-body")).to_be_visible()


def open_step(page, n):
    body = page.locator(f"#aj-step-{n}-body")
    if body.is_visible():
        return  # already the expanded step (its Edit is hidden by design)
    btn = page.locator(f'[data-testid="aj-step-{n}-edit"]')
    for _ in range(2):
        if btn.is_visible():
            break
        # a previously reopened step pins the rail (forceStep); returning to
        # the destination clears the pin, then re-render (the watcher may
        # already be stopped on terminal trips)
        page.click('[data-testid="aj-nav-plan"]')
        page.evaluate("if (window.__tripState) "
                      "window.__tripRender(window.__tripState);")
        page.wait_for_timeout(300)
        if body.is_visible():
            return  # the re-render expanded this step directly
    expect(btn).to_be_visible(timeout=10000)
    btn.click()
    expect(body).to_be_visible()


def book_happy_trip(page):
    """Shared happy path: goal → options → approval modal → booked PNR."""
    set_passport_via_api("MM")
    goto_trip(page)
    start_goal(page, HAPPY_GOAL)
    expect(page.locator('[data-testid="approval-open"]')) \
        .to_be_visible(timeout=25000)
    page.click('[data-testid="approval-open"]')
    expect(page.locator('[data-testid="trip-approval-overlay"]')) \
        .to_be_visible()
    page.click('[data-testid="approval-approve"]')
    expect(page.locator('[data-testid="pnr-code"]')) \
        .to_have_text("ATLAS-UI7Q2Z", timeout=20000)


# --- B1: landing → goal submit → clarify questions (one at a time) → confirm ------


def test_b1_goal_chat_clarify_chips_confirm(tracked_page, install_orch):
    install_orch()
    page = tracked_page
    goto_trip(page)

    # empty states before any trip: options/itinerary live inside collapsed
    # future steps (reachable once the flow reaches them); the DAG empty
    # state lives behind the "How this plan was made" disclosure
    expect(page.locator('[data-testid="trip-options-empty"]')) \
        .to_be_attached()
    expect(page.locator('[data-testid="trip-itinerary-empty"]')) \
        .to_be_attached()
    open_trace(page)
    expect(page.locator('[data-testid="trip-dag-empty"]')).to_be_visible()

    # ambiguous goal → ONE question card at a time; date comes first
    start_goal(page, AMBIGUOUS_GOAL)
    expect(page.locator('[data-testid="chip-input-date_window"]')) \
        .to_be_visible(timeout=20000)
    assert page.locator(".aj-question-card").count() == 1, \
        "exactly one question card may be shown at a time"

    # keyboard-reachable submit path: focus the button, press Enter
    page.locator('[data-testid="trip-goal-submit"]').focus()

    # confirm the date (trip fact) → persisted into the trip goal
    answer_chip(page, "date_window", "Sep 29-30", "\u2713 added to trip")

    # next card is the passport question → saved to profile server-side
    expect(page.locator('[data-testid="chip-input-passport_country"]')) \
        .to_be_visible(timeout=20000)
    answer_chip(page, "passport_country", "MM", "\u2713 saved to profile")
    prof = httpx.get(f"{BASE}/api/profile/victor", timeout=10.0).json()
    assert prof["identity"]["passport_country"] == "MM"

    # the goal echo rendered verbatim as inert text (chat disclosure)
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

    # B2: options render inside step 2; once approve_booking pauses the
    # graph, step 2 is a completed step reachable through its Edit pill
    expect(page.locator('[data-testid="approval-open"]')) \
        .to_be_visible(timeout=25000)
    open_step(page, 2)
    first_card = page.locator('[data-testid="trip-option-card"]').first
    expect(first_card).to_be_visible(timeout=25000)
    carriers = page.locator('[data-testid="trip-option-card"]')
    all_text = " ".join(
        carriers.nth(i).inner_text() for i in range(carriers.count()))
    assert "Singapore Airlines" in all_text, all_text
    assert "Scoot" in all_text, all_text
    expect(page.locator('[data-testid="sandbox-provenance"]').first) \
        .to_have_text("Atlas Sandbox data")
    # honest currency display (G4-DA-fix F6): the option's ACTUAL currency
    # renders natively; USD carries a labeled indicative SGD estimate and no
    # misleading \u0e3f pairing
    assert "$210.00" in all_text, all_text
    assert "\u2248 S$" in all_text, all_text
    assert "\u0e3f" not in all_text, all_text
    # visa panel with fresh citations lives behind step-3 Edit
    open_step(page, 3)
    expect(page.locator('[data-testid="trip-visa-panel"]')).to_be_visible()
    expect(page.locator('[data-testid="visa-fresh-chip"]')).to_be_visible()
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

    # itinerary renders honesty chips (researched-mock hotels/activities);
    # booking auto-switches to My trip where step 5 lives
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
    preset_passport_home()
    goto_trip(page)

    start_goal(page, AMBIGUOUS_GOAL)
    open_trace(page)
    nodes = page.locator('[data-testid="trip-dag-node"]')
    expect(nodes.first).to_be_visible(timeout=20000)
    # scope pause: goal_intake + clarify_loop + scope_clarification recorded
    answer_date_then_scope(page)
    expect(page.locator('[data-testid="trip-dag-node"]')) \
        .to_have_count(3, timeout=10000)

    # resolving scope resumes the graph; the DAG must reflect the new nodes
    # within ~1s polling cadence
    page.click('[data-testid="scope-choice-flight_only"]')
    t0 = time.monotonic()
    expect(nodes).not_to_have_count(3, timeout=3000)
    elapsed = time.monotonic() - t0
    assert elapsed <= 1.6, f"DAG growth took {elapsed:.2f}s (> 1s cadence + slack)"
    # status strip carries latency telemetry (inside the trace disclosure)
    expect(page.locator('[data-testid="trip-latency"]')) \
        .to_contain_text("ms total")
    page.screenshot(path=str(SHOTS / "g4_b4_dag_panel.png"))


# --- B5: profile editor — edit, save, masked passport display ----------------------


def test_b5_profile_editor_and_safe_fields(tracked_page, install_orch):
    install_orch()
    page = tracked_page
    goto_trip(page)

    # AJ: the profile surface opens as a drawer from the top bar
    page.click('[data-testid="aj-profile-open"]')
    expect(page.locator('[data-testid="aj-profile-drawer"]')).to_be_visible()

    # edit home_city
    page.click('[data-testid="profile-edit-home_city"]')
    page.fill('[data-testid="profile-input-home_city"]', "Bangkok")
    page.click('[data-testid="profile-save-home_city"]')
    expect(page.locator('[data-testid="profile-value-home_city"]')) \
        .to_have_text("Bangkok")

    # edit passport_country (safe field only)
    page.click('[data-testid="profile-edit-passport_country"]')
    page.fill('[data-testid="profile-input-passport_country"]', "MM")
    page.click('[data-testid="profile-save-passport_country"]')
    expect(page.locator('[data-testid="profile-value-passport_country"]')) \
        .to_have_text("MM")

    # canonical F17: no passport number field or row exists in the UI
    assert page.locator('[data-testid="profile-row-passport_no"]').count() == 0
    assert page.locator('[data-testid="profile-input-passport_no"]').count() == 0

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

    # run 1: teach the agent the home city (drawer editor)
    page.click('[data-testid="aj-profile-open"]')
    expect(page.locator('[data-testid="aj-profile-drawer"]')).to_be_visible()
    page.click('[data-testid="profile-edit-home_city"]')
    page.fill('[data-testid="profile-input-home_city"]', "Bangkok")
    page.click('[data-testid="profile-save-home_city"]')
    expect(page.locator('[data-testid="profile-value-home_city"]')) \
        .to_have_text("Bangkok")

    # run 2: fresh page load — remembered city surfaces as a confirmed fact
    # and the greeting switches to 'Welcome back.' (D6: the city never leaks
    # into prose; it lives as an editable confirmed fact)
    page.reload()
    page.click('[data-testid="nav-trip"]')
    expect(page.locator('[data-testid="aj-greeting"]')) \
        .to_contain_text("Welcome back")
    expect(page.locator('[data-testid="trip-greeting"]')) \
        .to_contain_text("Welcome back")
    expect(page.locator('[data-testid="aj-facts-summary"]')) \
        .to_contain_text("Bangkok")
    page.screenshot(path=str(SHOTS / "g4_b6_remembered_greeting.png"))


# --- scope clarification: exactly three choices, flight-only intent -----------------


def test_scope_three_choice_flow_and_flight_only(tracked_page, install_orch):
    install_orch()
    page = tracked_page
    preset_passport_home()
    goto_trip(page)

    start_goal(page, AMBIGUOUS_GOAL)
    answer_date_then_scope(page)
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
    open_step(page, 2)
    expect(page.locator('[data-testid="trip-option-card"]').first).to_be_visible()
    # itinerary stays in its empty state; the DAG ran no leisure/booking nodes
    expect(page.locator('[data-testid="trip-itinerary-empty"]')) \
        .to_be_attached()
    open_trace(page)
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
    #     (AJ: surfaced behind the step-3 Edit pill, never deleted)
    install_orch(fetcher=_offline_fetch)
    page = tracked_page
    set_passport_via_api("MM")
    goto_trip(page)
    start_goal(page, HAPPY_GOAL)
    expect(page.locator('[data-testid="approval-open"]')) \
        .to_be_visible(timeout=25000)
    open_step(page, 3)
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
    expect(page.locator('[data-testid="approval-open"]')) \
        .to_be_visible(timeout=25000)
    open_step(page, 3)
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


def test_hostile_provider_and_api_payloads_render_inert(tracked_page, install_orch):
    """R2: Hostile search/radar/chat/package payloads render safely as plain text."""
    install_orch()
    page = tracked_page
    page.goto(BASE)

    # 1. Test search results rendering hostile HTML
    page.evaluate("""() => {
        renderSearchResults([{
            airline: '<script>window.__xss_air=1</script>EvilAir',
            flight_number: 'EV666<img src=x onerror="window.__xss_fn=1">',
            origin: 'BKK<script>window.__xss_org=1</script>',
            destination: 'SIN',
            departure_time: '2026-09-29 10:00',
            arrival_time: '2026-09-29 13:00',
            price_usd: 120,
            seats_available: 5
        }]);
    }""")
    assert page.evaluate("window.__xss_air === undefined")
    assert page.evaluate("window.__xss_fn === undefined")
    assert page.evaluate("window.__xss_org === undefined")
    assert page.locator("#search-results script").count() == 0
    assert page.locator("#search-results img").count() == 0

    # 2. Test radar flights & alerts rendering hostile HTML
    page.evaluate("""() => {
        renderRadar({
            alerts: [{
                id: 'alert-xss',
                flight_number: 'TG999<script>window.__xss_rad=1</script>',
                status: 'CANCELLED<img src=x onerror="window.__xss_rad2=1">',
                reason: 'Hostile <script>window.__xss_rad3=1</script>'
            }],
            last_scan: {
                flights: [{
                    flight_number: 'TG888<script>window.__xss_rf=1</script>',
                    status: 'DELAYED',
                    reason: 'Storm<img src=x onerror="window.__xss_rf2=1">',
                    disrupted: true
                }]
            }
        });
    }""")
    assert page.evaluate("window.__xss_rad === undefined")
    assert page.evaluate("window.__xss_rad2 === undefined")
    assert page.evaluate("window.__xss_rad3 === undefined")
    assert page.evaluate("window.__xss_rf === undefined")
    assert page.evaluate("window.__xss_rf2 === undefined")
    assert page.locator("#radar-alerts script").count() == 0
    assert page.locator("#radar-alerts img").count() == 0
    assert page.locator("#radar-flights script").count() == 0
    assert page.locator("#radar-flights img").count() == 0

    # 3. Test package rendering hostile HTML
    page.evaluate("""() => {
        renderPackages([{
            package_type: 'FASTEST_RECOVERY',
            airline: 'Singapore Airlines<script>window.__xss_pkg=1</script>',
            flight_number: 'SQ123',
            origin: 'BKK',
            destination: 'SIN',
            departure_time: '2026-09-29 11:00',
            arrival_time: '2026-09-29 14:00',
            price_usd: 250,
            currency_symbol: '$',
            visa_status: 'CLEAR',
            agent_recommendation_reason: 'Fastest<img src=x onerror="window.__xss_pkg2=1">'
        }]);
    }""")
    assert page.evaluate("window.__xss_pkg === undefined")
    assert page.evaluate("window.__xss_pkg2 === undefined")
    assert page.locator("#rescue-packages script").count() == 0
    assert page.locator("#rescue-packages img").count() == 0


# --- narrow viewports: no horizontal overflow at 375 AND 360 --------------------------


def _assert_no_overflow(m, shot_name):
    m.wait_for_selector("#view-trip.active", timeout=10000)
    m.wait_for_selector('[data-testid="trip-goal-form"]', state="visible",
                        timeout=10000)
    assert not m.evaluate(
        "document.documentElement.scrollWidth > window.innerWidth + 1"), \
        "horizontal overflow on the trip view"
    expect(m.locator("#bottom-nav")).to_be_visible()
    expect(m.locator('[data-testid="mnav-trip"]')).to_be_visible()
    m.screenshot(path=str(SHOTS / shot_name))


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
        _assert_no_overflow(m, "g4_mobile_375_trip.png")
    finally:
        context.close()
    assert not errors, f"browser console errors detected: {errors}"


def test_mobile_360_trip_view_no_overflow(app_server, ui_browser):
    """Spec §9.9: 360px worst case must not overflow horizontally — the AJ
    top-bar profile button wraps to its own row instead of widening the
    frozen legacy topbar."""
    errors = []
    context = ui_browser.new_context(viewport={"width": 360, "height": 800})
    m = context.new_page()
    m.on("console", lambda msg: errors.append(msg.text)
         if msg.type == "error" and not _THIRD_PARTY_FONT.search(msg.text)
         else None)
    m.on("pageerror", lambda exc: errors.append(str(exc)))
    try:
        m.goto(BASE)
        m.click('[data-testid="mnav-trip"]')
        _assert_no_overflow(m, "g45_mobile_360_trip.png")
        # profile button stays reachable + ≥44px touch target at 360
        box = m.locator('[data-testid="aj-profile-open"]').bounding_box()
        assert box and box["width"] >= 44 and box["height"] >= 44, box
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


# --- G4 Devil's Advocate + live-browser remediation regressions ---------------------


def _wait_poll_pause(page, seconds=2.5):
    """Fail early if /state polling keeps firing; return True once the
    poll counter stays static for ~seconds (polling genuinely stopped)."""
    prev = page.evaluate("window.__statePolls")
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        time.sleep(0.25)
        cur = page.evaluate("window.__statePolls")
        if cur != prev:
            return False
    return True


def test_f1_polling_stops_on_terminal_and_view_exit(tracked_page, install_orch):
    """G4-DA-fix F1: the 1s DAG polling must stop once the trip reaches a
    terminal status AND when the user leaves the trip view."""
    install_orch()
    page = tracked_page
    preset_passport_home()
    goto_trip(page)
    page.evaluate("""() => {
        window.__statePolls = 0;
        const orig = window.fetch;
        window.fetch = function (input, opts) {
            const url = typeof input === 'string' ? input : String(input.url);
            if (url.indexOf('/state') !== -1) window.__statePolls += 1;
            return orig.apply(this, arguments);
        };
    }""")

    start_goal(page, AMBIGUOUS_GOAL)
    # answer the one outstanding question (date) so the scope card surfaces
    answer_date_then_scope(page)
    page.click('[data-testid="scope-choice-flight_only"]')
    expect(page.locator('[data-testid="trip-status-pill"]')) \
        .to_have_text("completed", timeout=25000)
    # terminal status: polling stops (SSE closes alone is not enough)
    assert _wait_poll_pause(page), "polling kept firing after terminal status"

    # leaving the trip view also halts any residual watcher
    page.evaluate("window.__statePolls = 0;")
    page.click('[data-testid="nav-rescue"]')
    expect(page.locator("#view-trip")).not_to_have_class(re.compile(r"\bactive\b"))
    assert _wait_poll_pause(page), "polling kept firing after leaving trip view"


def test_f2_stale_poll_cannot_resurrect_resolved_scope(tracked_page,
                                                       install_orch):
    """G4-DA-fix F2: an in-flight /state response captured BEFORE a scope
    resolution must never re-apply its stale snapshot (resurrecting the
    scope block / regressing the status pill) once released."""
    install_orch()
    page = tracked_page
    preset_passport_home()
    goto_trip(page)
    page.evaluate("""() => {
        window.__hold = null;
        window.__release = null;
        const orig = window.fetch;
        window.fetch = function (input, opts) {
            const url = typeof input === 'string' ? input : String(input.url);
            if (url.indexOf('/state') !== -1 && window.__hold === null) {
                const p = new Promise((resolve) => { window.__release = resolve; });
                window.__hold = p;
                return p;
            }
            return orig.apply(this, arguments);
        };
    }""")

    start_goal(page, AMBIGUOUS_GOAL)
    open_trace(page)
    expect(page.locator('[data-testid="trip-dag-node"]')) \
        .to_have_count(3, timeout=20000)
    answer_date_then_scope(page)
    page.click('[data-testid="scope-choice-flight_only"]')
    expect(page.locator('[data-testid="trip-status-pill"]')) \
        .to_have_text("completed", timeout=25000)

    # craft the held response into a stale pre-resolution snapshot
    page.evaluate("""() => {
        const stale = JSON.parse(JSON.stringify(window.__tripState));
        stale.status = 'awaiting_approval';
        stale.pending_approvals = [{
            approval_id: 'stale_appr', node_name: 'scope_clarification',
            options: [
                {choice: 'flight_only', label: 'Search flights only'},
                {choice: 'flight_plus_booking', label: 'Book'},
                {choice: 'complete_trip', label: 'Complete trip'}
            ]
        }];
        window.__release({
            ok: true,
            json: () => Promise.resolve(stale)
        });
    }""")
    time.sleep(1.0)
    # the stale snapshot must be dropped, never rendered
    expect(page.locator('[data-testid="trip-status-pill"]')) \
        .to_have_text("completed")
    expect(page.locator("#trip-scope-block")).to_be_hidden()


def test_f3_error_banner_clears_on_recovery(app_server, ui_browser,
                                            install_orch):
    """G4-DA-fix F3: the error banner must clear on the next successful
    render — a transient 500 on /state never gets a banner stuck."""
    install_orch()
    errors = []
    context = ui_browser.new_context()
    page = context.new_page()

    def on_console(msg):
        if msg.type == "error" \
                and not _THIRD_PARTY_FONT.search(msg.text) \
                and "Failed to load resource" not in msg.text:
            errors.append(msg.text)

    page.on("console", on_console)
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.set_default_timeout(15000)
    try:
        page.goto(BASE)
        page.click('[data-testid="nav-trip"]')
        expect(page.locator("#view-trip")).to_be_visible()
        # deterministic ordering: HOLD the immediate first poll, let the next
        # poll fail with 500 (banner appears), then HOLD every further poll
        # so nothing can hide the banner until the test releases one REAL
        # response — the recovery is what clears it.
        page.evaluate("""() => {
            window.__origFetch = window.fetch.bind(window);
            window.__f3phase = 0;
            window.fetch = function (input, opts) {
                const url = typeof input === 'string' ? input : String(input.url);
                if (url.indexOf('/state') === -1) {
                    return window.__origFetch(input, opts);
                }
                if (window.__f3phase === 0) {
                    window.__f3phase = 1;
                    return new Promise(() => {}); // held forever
                }
                if (window.__f3phase === 1) {
                    window.__f3phase = 2;
                    return Promise.resolve(new Response('boom', {status: 500}));
                }
                return new Promise((resolve) => { window.__f3rel = resolve; });
            };
        }""")
        start_goal(page, AMBIGUOUS_GOAL)
        expect(page.locator("#trip-error")).to_be_visible(timeout=20000)
        # release one REAL /state response — the recovery render clears it
        page.evaluate("""async () => {
            const res = await window.__origFetch(
                '/api/trip/' + window.__tripId + '/state');
            window.__f3rel(res);
        }""")
        # the successful poll recovers — banner hides
        expect(page.locator("#trip-error")).to_be_hidden(timeout=15000)
        # AJ: recovery resumes at the FIRST question card (fresh store asks
        # the date first)
        expect(page.locator('[data-testid="chip-input-date_window"]')) \
            .to_be_visible(timeout=20000)
    finally:
        context.close()
    assert not errors, f"browser console errors detected: {errors}"


def test_f4_origin_city_chip_persists_and_trip_resumes(tracked_page,
                                                       install_orch):
    """G4-DA-fix F4: confirming a NON-profile clarify answer (origin_city)
    must persist into the trip goal server-side and let the trip resume —
    previously the confirm was a silent no-op."""
    install_orch()
    page = tracked_page
    goto_trip(page)
    start_goal(page, "I need to get to Singapore on 2026-09-29.")
    # AJ one-at-a-time: origin is the first unanswered FIELD_ORDER field
    expect(page.locator('[data-testid="chip-input-origin_city"]')) \
        .to_be_visible(timeout=20000)
    answer_chip(page, "origin_city", "Bangkok")
    # F4 intent: the answer persisted server-side into the trip goal
    expect(page.locator('[data-testid="aj-fact-origin_city"]')) \
        .to_contain_text("Bangkok")

    # remaining profile questions (passport, home) then the scope card
    answer_chip(page, "passport_country", "MM", "\u2713 saved to profile")
    answer_chip(page, "home_city", "Bangkok", "\u2713 saved to profile")
    expect(page.locator('[data-testid="scope-choice-flight_only"]')) \
        .to_be_visible(timeout=20000)
    page.click('[data-testid="scope-choice-flight_only"]')
    expect(page.locator('[data-testid="trip-status-pill"]')) \
        .to_have_text("completed", timeout=25000)
    open_step(page, 2)
    expect(page.locator('[data-testid="trip-option-card"]').first) \
        .to_be_visible(timeout=15000)
    routes = page.locator('[data-testid="trip-option-card"] '
                          '.trip-option-route .trip-option-code').first
    expect(routes).to_have_text("BKK")


def test_f6_option_currency_rendered_honestly(tracked_page, install_orch):
    """G4-DA-fix F6: a THB-priced offer renders its native currency; the
    UI never pairs a non-THB fare with a \u0e3f conversion."""

    class ThbAtlas(FakeAtlas):
        async def search_flights(self, origin, destination, date_,
                                 passengers=1, **kwargs):
            offers = await super().search_flights(origin, destination, date_,
                                                  passengers, **kwargs)
            offers[0]["price_usd"] = 7400.0
            offers[0]["currency"] = "THB"
            return offers[:1]

    install_orch(atlas=ThbAtlas())
    page = tracked_page
    set_passport_via_api("MM")
    goto_trip(page)
    start_goal(page, HAPPY_GOAL)
    expect(page.locator('[data-testid="approval-open"]')) \
        .to_be_visible(timeout=25000)
    open_step(page, 2)
    card = page.locator('[data-testid="trip-option-card"]').first
    expect(card).to_be_visible(timeout=25000)
    text = card.inner_text()
    assert "\u0e3f" in text, text
    assert "$" not in text, text


def test_f8_unknown_itinerary_source_falls_back_to_honesty_label(
        tracked_page, install_orch):
    """G4-DA-fix F8: items whose source is none of the known provider
    labels fall back to their honesty_label instead of the blanket
    '\U0001f4a1 suggestion only' chip."""
    install_orch()
    page = tracked_page
    goto_trip(page)
    start_goal(page, AMBIGUOUS_GOAL)
    open_trace(page)
    expect(page.locator('[data-testid="trip-dag-node"]').first) \
        .to_be_visible(timeout=20000)
    page.evaluate("""() => {
        const crafted = JSON.parse(JSON.stringify(window.__tripState));
        crafted.outputs.itinerary = {items: [{
            name: 'Gardens by the Bay', kind: 'activity',
            source: 'organizer', honesty_label: 'live data',
            price_range_sgd: [28, 53],
            provenance: {researched_as_of: null}, details: {}
        }]};
        window.__tripRender(crafted);
        // keep background polls on the crafted snapshot so the row is not
        // wiped by a real-state re-render (poll race). Switched off via a
        // flag — NEVER re-assign window.fetch back: re-assignment triggers
        // a Chromium fetch(null) probe that logs a spurious /null 404.
        const origF8 = window.fetch.bind(window);
        window.__f8Off = false;
        window.fetch = function (input, opts) {
            const url = typeof input === 'string' ? input
                : (input ? String(input.url) : String(input));
            if (!window.__f8Off && url.indexOf('/state') !== -1) {
                return Promise.resolve(new Response(JSON.stringify(crafted),
                    {status: 200,
                     headers: {'Content-Type': 'application/json'}}));
            }
            return origF8(input, opts);
        };
    }""")
    # AJ: the itinerary lives in the My trip destination
    page.click('[data-testid="aj-nav-mytrip"]')
    expect(page.locator('[data-testid="itin-chip-llm"]')).to_be_visible()
    expect(page.locator('[data-testid="itin-chip-llm"]')) \
        .to_have_text("live data")
    page.evaluate("window.__f8Off = true;")
    page.wait_for_timeout(200)


def test_f9_hostile_field_name_does_not_throw(tracked_page, install_orch):
    """G4-DA-fix F9: a clarify question carrying a quote-heavy field name
    must render its question card without a SyntaxError (attribute scan,
    never selector construction from server field names)."""
    install_orch()
    page = tracked_page
    goto_trip(page)
    start_goal(page, AMBIGUOUS_GOAL)
    open_trace(page)
    expect(page.locator('[data-testid="trip-dag-node"]').first) \
        .to_be_visible(timeout=20000)
    page.evaluate("""() => {
        const crafted = JSON.parse(JSON.stringify(window.__tripState));
        crafted.outputs.clarify.questions = [{
            field: 'na"ughty\\"x]',
            question: 'Confirm the hostile field name renders safely'
        }];
        window.__tripRender(crafted);
    }""")
    card = page.locator('#trip-clarify-chips .aj-question-card').last
    expect(card).to_contain_text("hostile field name renders safely")
    assert page.evaluate("window.__xss === undefined")


def test_f10_new_trip_clears_stale_panels(tracked_page, install_orch):
    """G4-DA-fix (leader defect e): starting a new trip must clear the
    previous trip's option cards, itinerary, PNR screen and DAG — nothing
    from trip A may leak into trip B before B's own outputs exist."""
    install_orch()
    page = tracked_page
    set_passport_via_api("MM")
    goto_trip(page)

    # trip A: full happy flow -> option cards + booked PNR
    start_goal(page, HAPPY_GOAL)
    expect(page.locator('[data-testid="approval-open"]')) \
        .to_be_visible(timeout=25000)
    page.click('[data-testid="approval-open"]')
    page.click('[data-testid="approval-approve"]')
    expect(page.locator('[data-testid="pnr-code"]')) \
        .to_have_text("ATLAS-UI7Q2Z", timeout=20000)
    expect(page.locator('[data-testid="trip-itin-item"]').first) \
        .to_be_visible(timeout=20000)

    # trip B: paused at clarification — flight_search never ran. Wait for
    # B's own echo in the chat (chat is cleared on new-trip start, so this
    # also proves the per-trip reset ran). The booking auto-switched to
    # My trip, so returning to Plan and reopening step 1 is the beginner
    # path to start another trip.
    page.click('[data-testid="aj-nav-plan"]')
    open_step(page, 1)
    page.fill('[data-testid="trip-goal-input"]', AMBIGUOUS_GOAL)
    page.click('[data-testid="trip-goal-submit"]')
    expect(page.locator('[data-testid="trip-chat"]')) \
        .to_contain_text(AMBIGUOUS_GOAL, timeout=20000)
    open_trace(page)
    expect(page.locator('[data-testid="trip-dag-node"]').first) \
        .to_be_visible(timeout=20000)
    # stale option cards cleared — empty placeholder restored (inside the
    # collapsed future step, hence attached not visible)
    expect(page.locator('[data-testid="trip-option-card"]')) \
        .to_have_count(0, timeout=10000)
    expect(page.locator('[data-testid="trip-options-empty"]')) \
        .to_be_attached()
    expect(page.locator('[data-testid="trip-itinerary-empty"]')) \
        .to_be_attached()
    expect(page.locator("#trip-pnr-block")).to_be_hidden()
    expect(page.locator("#trip-approval-overlay")).to_be_hidden()



# --- G4.5 ATLAS JOURNEY regressions (spec §10.3: AJ01–AJ13) --------------------------


def test_AJ01_ia_three_destinations(tracked_page, install_orch):
    """Exactly 3 AJ destinations; no engineering dashboard by default."""
    install_orch()
    page = tracked_page
    goto_trip(page)
    nav = page.locator(".aj-nav-btn")
    assert nav.count() == 3, "AJ IA is exactly Plan a trip / My trip / Help"
    for tid_name in ("aj-nav-plan", "aj-nav-mytrip", "aj-nav-help"):
        expect(page.locator(f'[data-testid="{tid_name}"]')).to_be_visible()
    # the DAG dashboard is collapsed behind a disclosure by default
    trace_btn = page.locator('[data-testid="aj-disclosure-trace"]')
    expect(trace_btn).to_have_attribute("aria-expanded", "false")
    expect(page.locator("#aj-trace-body")).to_be_hidden()
    expect(page.locator('[data-testid="trip-dag-list"]')).to_be_hidden()


def test_AJ02_starter_choices_services(tracked_page, install_orch):
    """3 starters initialize RequestedServices; nothing auto-added."""
    install_orch()
    page = tracked_page
    goto_trip(page)
    svc = page.locator('[data-testid="aj-requested-services"]')

    page.click('[data-testid="aj-starter-flight-only"]')
    expect(svc).to_be_visible(timeout=5000)
    text = svc.inner_text()
    assert "Find flights" in text, text
    for absent in ("Hotel", "Activities", "transport", "Monitor", "Notif"):
        assert absent not in text, (absent, text)

    page.click('[data-testid="aj-starter-flight-booking"]')
    text = svc.inner_text()
    assert "Book flights" in text, text
    assert "Hotel" not in text, text

    page.click('[data-testid="aj-starter-complete"]')
    text = svc.inner_text()
    assert "Hotel" in text and "Activities" in text, text
    assert "Local transport" in text, text
    # never auto-added: monitoring/notifications are not services
    assert "Monitor" not in text and "Notif" not in text, text
    # the starter pre-fills an EDITABLE goal composer
    goal_val = page.input_value('[data-testid="trip-goal-input"]')
    assert "complete trip" in goal_val, goal_val


def test_AJ03_one_question_at_a_time(tracked_page, install_orch):
    """One aj-question-card; Back preserves input; facts summary updates."""
    install_orch()
    page = tracked_page
    goto_trip(page)
    start_goal(page, AMBIGUOUS_GOAL)
    expect(page.locator('[data-testid="chip-input-date_window"]')) \
        .to_be_visible(timeout=20000)
    assert page.locator(".aj-question-card").count() == 1

    # Back defers: the value is preserved; a pending fact chip appears
    page.fill('[data-testid="chip-input-date_window"]', "Sep 2")
    page.click('[data-testid="aj-question-back"]')
    expect(page.locator('[data-testid="chip-input-date_window"]')) \
        .to_be_hidden()
    expect(page.locator('[data-testid="aj-fact-date_window"]')) \
        .to_contain_text("answer needed")

    # the next question takes over (exactly one card at any time)
    expect(page.locator('[data-testid="chip-input-passport_country"]')) \
        .to_be_visible(timeout=20000)
    assert page.locator(".aj-question-card").count() == 1
    answer_chip(page, "passport_country", "MM", "\u2713 saved to profile")
    answer_chip(page, "home_city", "Bangkok", "\u2713 saved to profile")

    # reopen the deferred question — input value preserved
    page.click('[data-testid="aj-fact-edit-date_window"]')
    expect(page.locator('[data-testid="chip-input-date_window"]')) \
        .to_be_visible()
    assert page.input_value('[data-testid="chip-input-date_window"]') == "Sep 2"
    answer_chip(page, "date_window", "Sep 2", "\u2713 added to trip")
    # confirmed-facts compact summary updated
    expect(page.locator('[data-testid="aj-fact-date_window"]')) \
        .to_contain_text("Sep 2")


def test_AJ04_max_three_options_show_more(tracked_page, install_orch):
    """≤3 ranked options initially; Show more reveals the rest; every card
    carries a ranking reason + fare + sandbox provenance."""
    install_orch(atlas=ManyAtlas())
    page = tracked_page
    set_passport_via_api("MM")
    goto_trip(page)
    start_goal(page, HAPPY_GOAL)
    expect(page.locator('[data-testid="approval-open"]')) \
        .to_be_visible(timeout=25000)
    open_step(page, 2)
    visible_cards = page.locator('[data-testid="trip-option-card"]:visible')
    expect(visible_cards.first).to_be_visible(timeout=20000)
    assert visible_cards.count() == 3, \
        f"max 3 options initially, got {visible_cards.count()}"
    # each visible card: rank + reason + fare
    for i in (1, 2, 3):
        reason = page.locator(f'[data-testid="aj-option-reason-{i}"]')
        expect(reason).to_be_visible()
        assert reason.inner_text().strip(), f"option {i} lacks a reason"
    card1 = page.locator('[data-testid-aj="aj-option-card-1"]').inner_text()
    assert "$" in card1, card1
    expect(page.locator('[data-testid="sandbox-provenance"]').first) \
        .to_have_text("Atlas Sandbox data")
    # Show more reveals all 5
    page.click('[data-testid="aj-show-more-options"]')
    expect(page.locator('[data-testid="trip-option-card"]:visible')) \
        .to_have_count(5, timeout=10000)


def test_AJ05_vocabulary(tracked_page, install_orch):
    """Beginner language: no PNR/DAG/Submit/Proceed jargon in visible text;
    Booking reference + What happens next present."""
    install_orch()
    page = tracked_page
    book_happy_trip(page)
    # booking auto-switched to My trip. NB: inner_text reflects CSS
    # text-transform (small-caps labels), so vocabulary is matched
    # case-insensitively against the rendered text.
    mytrip_text = page.locator("#aj-shell").inner_text()
    lowered = mytrip_text.lower()
    for jargon in ("pnr", "dag", "submit", "proceed"):
        assert jargon not in lowered, (jargon, mytrip_text[:300])
    assert "booking reference" in lowered, mytrip_text[:400]
    assert "what happens next" in lowered, mytrip_text[:400]
    # even with the engineering trace expanded, no DAG jargon leaks
    open_trace(page)
    trace_text = page.locator("#aj-trace-body").inner_text()
    assert "dag" not in trace_text.lower(), trace_text[:200]


def test_AJ06_honesty_never_hidden(tracked_page, install_orch):
    """Sandbox one-liner at review AND confirm; degraded visa stays visible;
    date_note wraps instead of overflowing."""
    install_orch()
    page = tracked_page
    book_happy_trip(page)
    open_step(page, 3)
    expect(page.locator('[data-testid="aj-review-sandbox-note"]')) \
        .to_contain_text("Atlas Sandbox")
    open_step(page, 4)
    expect(page.locator('[data-testid="aj-confirm-sandbox-note"]')) \
        .to_contain_text("Atlas Sandbox")

    # degraded visa: offline web-intel flow — warning reachable, never removed
    install_orch(fetcher=_offline_fetch)
    set_passport_via_api("MM")
    page.goto(BASE)
    page.click('[data-testid="nav-trip"]')
    start_goal(page, HAPPY_GOAL)
    expect(page.locator('[data-testid="approval-open"]')) \
        .to_be_visible(timeout=25000)
    open_step(page, 3)
    expect(page.locator('[data-testid="visa-degraded-warning"]')) \
        .to_be_visible(timeout=25000)

    # the honesty CSS contract: date notes wrap (overflow-wrap:anywhere)
    rule_ok = page.evaluate("""() => {
        for (const sheet of document.styleSheets) {
            let rules; try { rules = sheet.cssRules; } catch (e) { continue; }
            for (const r of rules) {
                if (r.selectorText && r.selectorText.indexOf('.trip-date-note') !== -1
                        && r.style && r.style.overflowWrap === 'anywhere') return true;
            }
        }
        return false;
    }""")
    assert rule_ok, ".trip-date-note must carry overflow-wrap:anywhere"


def test_AJ07_journey_line_states(tracked_page, install_orch):
    """data-state transitions empty→(drawing)→confirmed (one pulse) and
    disrupted with the coral original + recovery branch."""
    install_orch()
    page = tracked_page
    set_passport_via_api("MM")
    goto_trip(page)
    line = page.locator('[data-testid="aj-journey-line"]')
    expect(line).to_have_attribute("data-state", "empty")

    page.evaluate("""() => {
        window.__lineRec = { states: [], pulses: 0 };
        const obs = new MutationObserver((muts) => {
            for (const m of muts) {
                if (m.attributeName === 'data-state') {
                    window.__lineRec.states.push(
                        m.target.getAttribute('data-state'));
                }
                if (m.attributeName === 'class'
                        && m.target.classList.contains('aj-pulse')) {
                    window.__lineRec.pulses += 1;
                }
            }
        });
        obs.observe(document.querySelector('#aj-journey-line'),
                    { attributes: true, subtree: true });
    }""")

    start_goal(page, HAPPY_GOAL)
    expect(page.locator('[data-testid="approval-open"]')) \
        .to_be_visible(timeout=25000)
    page.click('[data-testid="approval-open"]')
    page.click('[data-testid="approval-approve"]')
    expect(page.locator('[data-testid="pnr-code"]')) \
        .to_have_text("ATLAS-UI7Q2Z", timeout=20000)
    expect(line).to_have_attribute("data-state", "confirmed", timeout=10000)

    rec = page.evaluate("window.__lineRec")
    assert "confirmed" in rec["states"], rec
    assert rec["pulses"] >= 1, "confirmation pulse never applied"
    assert rec["pulses"] <= 2, "pulse must be restrained (one-shot)"

    # disruption branch
    page.evaluate("window.simulateDisruption()")
    expect(page.locator('[data-testid="aj-recovery-panel"]')) \
        .to_be_visible(timeout=25000)
    expect(line).to_have_attribute("data-state", "disrupted", timeout=10000)
    # branch path is part of the disrupted state (muted-coral original +
    # teal recovery branch)
    branch = page.locator('[data-testid="aj-line-branch"]')
    assert branch.count() == 1
    page.screenshot(path=str(SHOTS / "g45_aj07_journey_line.png"))


def test_AJ08_recovery_separate_approval(tracked_page, install_orch):
    """Original trip preserved, replacements carry suitability reasons,
    and recovery needs its OWN approval."""
    install_orch()
    page = tracked_page
    book_happy_trip(page)
    page.evaluate("window.simulateDisruption()")
    panel = page.locator('[data-testid="aj-recovery-panel"]')
    expect(panel).to_be_visible(timeout=25000)

    # original booking preserved and labeled
    expect(page.locator('[data-testid="aj-recovery-original"]')) \
        .to_be_visible()
    expect(page.locator('[data-testid="aj-recovery-original"]')) \
        .to_contain_text("Your original booking")

    # replacement options with suitability reasons
    cards = page.locator(".aj-recovery-card")
    expect(cards.first).to_be_visible(timeout=15000)
    assert cards.count() >= 1
    reason = page.locator('[data-testid="aj-recovery-reason-1"]')
    expect(reason).to_be_visible()
    assert reason.inner_text().strip(), "replacement lacks a reason"

    # SEPARATE approval: pick a replacement, then approve via the recovery
    # approval action (not the booking approval)
    page.click('[data-testid="aj-recovery-pick-1"]')
    approve_btn = page.locator('[data-testid="aj-recovery-approve"]')
    expect(approve_btn).to_be_visible()
    approve_btn.click()
    outcome = page.locator('[data-testid="aj-recovery-outcome"]')
    expect(outcome).to_be_visible(timeout=20000)
    assert outcome.inner_text().strip()
    expect(page.locator('[data-testid="aj-recovery-original-receipt"]')) \
        .to_be_visible(timeout=20000)
    expect(page.locator('[data-testid="aj-recovery-replacement-receipt"]')) \
        .to_be_visible(timeout=20000)
    expect(page.locator('[data-testid="aj-recovery-rights"]')) \
        .to_contain_text("Passenger rights")
    expect(page.locator('[data-testid="aj-recovery-monitor"]')) \
        .to_contain_text("Monitoring the replacement flight")
    itinerary = page.locator('[data-testid="trip-itinerary"]')
    expect(itinerary).to_contain_text("cancelled/replaced")
    expect(itinerary).to_contain_text("booked replacement flight")
    page.screenshot(path=str(SHOTS / "g45_aj08_recovery.png"))


def test_AJ08b_itinerary_replace_inline(tracked_page, install_orch):
    """A traveler can replace one suggested section in place; the booked
    flight stays immutable and the summary refreshes without a page reset."""
    install_orch()
    page = tracked_page
    book_happy_trip(page)

    summary = page.locator('[data-testid="aj-itinerary-summary"]')
    expect(summary).to_be_visible(timeout=20000)
    expect(summary).to_contain_text("Asia/Singapore")
    expect(summary).to_contain_text("Budget")

    flight = page.locator('.trip-itin-flight').first
    expect(flight).to_be_visible()
    assert flight.locator('[data-testid="aj-itinerary-replace"]').count() == 0

    replace = page.locator('[data-testid="aj-itinerary-replace"]').first
    expect(replace).to_be_visible()
    replace.click()
    editor = page.locator('[data-testid="aj-itinerary-editor"]')
    expect(editor).to_be_visible()
    name = page.locator('[data-testid="aj-itinerary-name"]')
    name.fill("Quiet Garden Hotel")
    page.locator('[data-testid="aj-itinerary-price-low"]').fill("160")
    page.locator('[data-testid="aj-itinerary-price-high"]').fill("220")
    page.click('[data-testid="aj-itinerary-save"]')

    expect(page.locator('[data-testid="trip-itinerary"]')) \
        .to_contain_text("Quiet Garden Hotel", timeout=20000)
    expect(page.locator('[data-testid="aj-itinerary-editor"]')) \
        .to_have_count(0)
    expect(summary).to_contain_text("Plan check")


def test_AJ09_profile_drawer_privacy(tracked_page, install_orch):
    """Drawer opens from the top bar; consent gate first; safe fields
    only; explicit privacy exclusion statement (canonical §5/§19.10)."""
    install_orch()
    page = tracked_page
    goto_trip(page)
    expect(page.locator('[data-testid="aj-profile-drawer"]')).to_be_hidden()
    page.click('[data-testid="aj-profile-open"]')
    drawer = page.locator('[data-testid="aj-profile-drawer"]')
    expect(drawer).to_be_visible()

    # consent statement precedes the data rows (gate first)
    order = page.evaluate("""() => {
        const note = document.querySelector(
            '[data-testid="aj-profile-consent-note"]');
        const rows = document.querySelector('#trip-profile-rows');
        return note.compareDocumentPosition(rows);
    }""")
    assert order & 4, "consent note must precede the profile rows"  # FOLLOWING

    # privacy statement: passport number, payment details, legal identity are NOT stored
    expect(page.locator('[data-testid="aj-profile-privacy-note"]')) \
        .to_contain_text("Passport number, payment details, and legal identity are not stored by this demo")

    # safe fields only: edit & save cabin
    page.click('[data-testid="profile-edit-cabin"]')
    page.fill('[data-testid="profile-input-cabin"]', "economy")
    page.click('[data-testid="profile-save-cabin"]')
    expect(page.locator('[data-testid="profile-value-cabin"]')) \
        .to_have_text("economy")

    # no passport number row or field in the DOM
    assert page.locator('[data-testid="profile-row-passport_no"]').count() == 0
    assert "passport_no" not in page.content()

    # close restores (dialog semantics)
    page.click('[data-testid="aj-profile-close"]')
    expect(drawer).to_be_hidden()
    page.screenshot(path=str(SHOTS / "g45_aj09_drawer.png"))


def test_AJ10_states_matrix(app_server, ui_browser, install_orch):
    """validation(422) / provider / expired(410) / offline states each
    render their aj-state-* box with a recovery action."""
    install_orch()
    context, page, errors = lenient_page(ui_browser)
    try:
        # (a) validation: deterministic 422 invalid_goal (impossible date)
        page.goto(BASE)
        page.click('[data-testid="nav-trip"]')
        start_goal(page, INVALID_DATE_GOAL)
        box = page.locator('[data-testid-aj="aj-state-validation"]')
        expect(box).to_be_visible(timeout=10000)
        assert "where you\u2019re going" in box.inner_text()
        box.locator(".aj-state-action").click()
        assert page.evaluate(
            "document.activeElement.id") == "trip-goal-input"

        # (b) recoverable provider failure on /start
        page.evaluate("""() => {
            window.__origFetch = window.fetch.bind(window);
            window.fetch = function (input, opts) {
                const url = typeof input === 'string' ? input : String(input.url);
                if (url.indexOf('/api/trip/start') !== -1) {
                    return Promise.resolve(new Response(
                        JSON.stringify({error: {code: 'boom',
                            message: 'synthetic outage'}}),
                        {status: 500,
                         headers: {'Content-Type': 'application/json'}}));
                }
                return window.__origFetch(input, opts);
            };
        }""")
        start_goal(page, AMBIGUOUS_GOAL)
        provider = page.locator('[data-testid-aj="aj-state-provider"]')
        expect(provider).to_be_visible(timeout=10000)
        expect(provider.locator(".aj-state-action")) \
            .to_have_text("Try again")
        page.evaluate("window.fetch = window.__origFetch;")

        # (c) expired approval (410) → fresh-approval path
        set_passport_via_api("MM")
        page.goto(BASE)
        page.click('[data-testid="nav-trip"]')
        start_goal(page, HAPPY_GOAL)
        expect(page.locator('[data-testid="approval-open"]')) \
            .to_be_visible(timeout=25000)
        page.click('[data-testid="approval-open"]')
        page.evaluate("""() => {
            window.__origFetch = window.fetch.bind(window);
            window.fetch = function (input, opts) {
                const url = typeof input === 'string' ? input : String(input.url);
                if (url.indexOf('/approvals/') !== -1) {
                    return Promise.resolve(new Response(
                        JSON.stringify({error: {code: 'approval_expired',
                            message: 'expired'}}),
                        {status: 410,
                         headers: {'Content-Type': 'application/json'}}));
                }
                return window.__origFetch(input, opts);
            };
        }""")
        page.click('[data-testid="approval-approve"]')
        expired = page.locator('[data-testid-aj="aj-state-expired"]')
        expect(expired).to_be_visible(timeout=10000)
        expect(expired).to_contain_text("timed out")
        page.evaluate("window.fetch = window.__origFetch;")
        expired.locator(".aj-state-action").click()
        expect(expired).to_be_hidden(timeout=10000)

        # (d) offline: /state network failure surfaces the offline box
        page.evaluate("""() => {
            window.__origFetch = window.fetch.bind(window);
            window.fetch = function (input, opts) {
                const url = typeof input === 'string' ? input : String(input.url);
                if (url.indexOf('/state') !== -1) {
                    return Promise.reject(new TypeError('network down'));
                }
                return window.__origFetch(input, opts);
            };
        }""")
        offline = page.locator('[data-testid-aj="aj-state-offline"]')
        expect(offline).to_be_visible(timeout=10000)
        page.evaluate("window.fetch = window.__origFetch;")
        page.screenshot(path=str(SHOTS / "g45_aj10_states.png"))
    finally:
        context.close()
    assert not errors, f"browser console errors detected: {errors}"


def _tab_until(page, testid, max_tabs=60):
    for _ in range(max_tabs):
        focused = page.evaluate("""() => {
            const el = document.activeElement;
            return el ? (el.getAttribute('data-testid') || el.id) : '';
        }""")
        if focused == testid:
            return True
        page.keyboard.press("Tab")
    return False


def test_AJ11_a11y_keyboard(tracked_page, install_orch):
    """The flow is completable with Tab/Enter; the approval dialog traps
    focus and restores it; aj-live carries announcements."""
    install_orch()
    page = tracked_page
    set_passport_via_api("MM")
    goto_trip(page)

    # keyboard to the goal composer; Enter inside a textarea adds a
    # newline, so submit via the keyboard-reachable Plan button
    assert _tab_until(page, "trip-goal-input"), "goal input unreachable by Tab"
    page.keyboard.type(HAPPY_GOAL)
    assert _tab_until(page, "trip-goal-submit"), \
        "submit button unreachable by Tab"
    page.keyboard.press("Enter")
    expect(page.locator('[data-testid="approval-open"]')) \
        .to_be_visible(timeout=25000)

    # keyboard to the approval entry point
    assert _tab_until(page, "approval-open"), "approval-open unreachable by Tab"
    page.keyboard.press("Enter")
    overlay = page.locator('[data-testid="trip-approval-overlay"]')
    expect(overlay).to_be_visible()

    # focus trap: Tab cycles INSIDE the dialog
    in_overlay = ("() => document.querySelector('#trip-approval-overlay')"
                  ".contains(document.activeElement)")
    expect(overlay).to_contain_text("Approve")
    assert page.evaluate(in_overlay), "focus did not land inside the dialog"
    for _ in range(8):
        page.keyboard.press("Tab")
        assert page.evaluate(in_overlay), "focus escaped the dialog"

    # approve with the keyboard
    assert _tab_until(page, "approval-approve"), "approve unreachable by Tab"
    page.keyboard.press("Enter")
    expect(page.locator('[data-testid="pnr-code"]')) \
        .to_have_text("ATLAS-UI7Q2Z", timeout=20000)

    # focus restored OUTSIDE the closed dialog
    assert not page.evaluate(in_overlay), "focus not restored after dialog"
    # aj-live announced async results
    assert page.evaluate(
        "document.getElementById('aj-live').textContent.length > 0")


def test_AJ12_reduced_motion(app_server, ui_browser, install_orch):
    """With prefers-reduced-motion: the line still reaches confirmed (no
    meaning loss) but the pulse is never applied."""
    install_orch()
    errors = []
    context = ui_browser.new_context()
    page = context.new_page()
    page.emulate_media(reduced_motion="reduce")
    page.on("console", lambda msg: errors.append(msg.text)
            if msg.type == "error" and not _THIRD_PARTY_FONT.search(msg.text)
            else None)
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.set_default_timeout(15000)
    try:
        set_passport_via_api("MM")
        page.goto(BASE)
        page.click('[data-testid="nav-trip"]')
        assert page.evaluate(
            "matchMedia('(prefers-reduced-motion: reduce)').matches")
        page.evaluate("""() => {
            window.__pulseSeen = false;
            const obs = new MutationObserver((muts) => {
                for (const m of muts) {
                    if (m.attributeName === 'class'
                            && m.target.classList.contains('aj-pulse')) {
                        window.__pulseSeen = true;
                    }
                }
            });
            obs.observe(document.querySelector('#aj-journey-line'),
                        { attributes: true });
        }""")
        start_goal(page, HAPPY_GOAL)
        expect(page.locator('[data-testid="approval-open"]')) \
            .to_be_visible(timeout=25000)
        page.click('[data-testid="approval-open"]')
        page.click('[data-testid="approval-approve"]')
        expect(page.locator('[data-testid="pnr-code"]')) \
            .to_have_text("ATLAS-UI7Q2Z", timeout=20000)
        # meaning preserved without motion
        expect(page.locator('[data-testid="aj-journey-line"]')) \
            .to_have_attribute("data-state", "confirmed", timeout=10000)
        assert not page.evaluate("window.__pulseSeen"), \
            "pulse applied under prefers-reduced-motion"
    finally:
        context.close()
    assert not errors, f"browser console errors detected: {errors}"


def test_AJ13_legacy_canary(tracked_page, install_orch):
    """Frozen canary: every e2e_full_journey.py pinned selector still
    resolves; static/app.js is byte-identical."""
    install_orch()
    page = tracked_page
    page.goto(BASE)
    canary_ids = (
        "add-flight-overlay", "banner-title", "bottom-nav", "btn-add-flight",
        "btn-send", "btn-simulate", "chat-input", "chat-messages",
        "compensation-card", "disruption-banner", "empty-state",
        "health-badge", "input-flight-date", "input-flight-number",
        "input-nationality", "input-passenger-name", "radar-flights",
        "rights-panel", "rights-regime-badge", "rights-sub",
        "search-destination", "search-origin", "search-results",
        "trail-list", "view-concierge", "view-radar", "view-search",
    )
    missing = [cid for cid in canary_ids
               if page.locator(f"#{cid}").count() == 0]
    assert not missing, f"frozen canary ids missing: {missing}"
    for view in ("rescue", "search", "concierge", "radar", "trip"):
        assert page.locator(f"#view-{view}").count() == 1, view
    # byte-frozen legacy engine
    app_js = Path(__file__).resolve().parent.parent / "static" / "app.js"
    digest = hashlib.sha256(app_js.read_bytes()).hexdigest()
    assert digest == APP_JS_SHA256, "static/app.js was modified"


# ======================================================================
# G4.6 SAFETY INTELLIGENCE — UI regressions (additive, hermetic).
# Same boot pattern as above; the safety pipeline runs against an
# injected transport (no live network). Port 8050 must be FREE.
# ======================================================================

from routers.v1.trip import SafetyService  # noqa: E402
from services.skills.safety_monitor import SafetyMonitorSkill  # noqa: E402
from services.skills.safety_research import (  # noqa: E402
    SafetyResearchSkill,
)

_UI_GOV_UK_SG = ("https://www.gov.uk/api/content/"
                 "foreign-travel-advice/singapore")


def _ui_safety_fetch(summary):
    updated = (datetime.now(timezone.utc) - timedelta(minutes=10)) \
        .isoformat().replace("+00:00", "Z")

    async def fetch(url):
        if url != _UI_GOV_UK_SG:
            raise ConnectionError("no route (simulated)")
        return {"status": 200, "final_url": "",
                "json": {"title": "Singapore travel advice",
                         "public_updated_at": updated,
                         "details": {"summary": summary}},
                "text": ""}
    return fetch


@pytest.fixture
def install_safety_orch(tmp_path):
    """G3 harness + the REAL safety pipeline with injected transport."""

    def _install(summary):
        store = ProfileStore(root=tmp_path / "profiles")
        set_profile_store(store)
        orch = TripOrchestrator(
            profile_store=store, atlas=FakeAtlas(),
            web_intel=WebIntelClient(ddg_fetcher=_fresh_fetcher(),
                                     tavily_api_key="", serper_api_key=""),
            llm_chat=_no_llm,
            safety_service=SafetyService(
                research=SafetyResearchSkill(fetch=_ui_safety_fetch(summary)),
                monitor=SafetyMonitorSkill(min_interval_seconds=0)))
        set_trip_orchestrator(orch)
        return orch

    yield _install


def _wait_safety_card(page):
    page.click('[data-testid="aj-nav-mytrip"]')  # My trip screen (step 5)
    expect(page.locator('[data-testid="aj-safety-card"]')) \
        .to_be_visible(timeout=25000)


def test_ui_safety_card_normal_status_with_sources(tracked_page,
                                                   install_safety_orch):
    install_safety_orch("Exercise normal precautions.")
    page = tracked_page
    set_passport_via_api("MM")
    goto_trip(page)
    start_goal(page, HAPPY_GOAL)
    expect(page.locator('[data-testid="approval-open"]')) \
        .to_be_visible(timeout=25000)
    _wait_safety_card(page)
    expect(page.locator('[data-testid="aj-safety-status"]')) \
        .to_contain_text("Routine precautions")
    expect(page.locator('[data-testid="aj-safety-destination"]')) \
        .to_contain_text("Singapore")
    expect(page.locator('[data-testid="aj-safety-dates"]')) \
        .to_contain_text("2026-09-29")
    expect(page.locator('[data-testid="aj-safety-why"]')).to_be_visible()
    expect(page.locator('[data-testid="aj-safety-confidence"]')) \
        .to_be_visible()
    # foreign-government advice is labeled, never presented as ours
    expect(page.locator('[data-testid="aj-safety-source-0"]')) \
        .to_contain_text("Advice issued for United Kingdom citizens; "
                         "shown as an additional safety signal.")
    expect(page.locator('[data-testid="aj-safety-source-0"]')) \
        .to_contain_text("UK Foreign")
    expect(page.locator('[data-testid="aj-safety-source-0"] '
                        'a[href*="gov.uk"]')).to_be_attached()
    # absolute "safe" language is rejected in every rendered string
    card_text = page.locator('[data-testid="aj-safety-card"]').inner_text()
    assert not re.search(r"\bsafe\b", card_text, re.IGNORECASE), card_text
    # keyboard-accessible primary action
    page.locator('[data-testid="aj-safety-recheck"]').focus()
    assert page.locator('[data-testid="aj-safety-recheck"]') \
        .evaluate("el => el === document.activeElement")
    page.screenshot(path=str(SHOTS / "g46_safety_card_normal.png"),
                    full_page=True)


def test_ui_safety_do_not_travel_blocks_booking(app_server, ui_browser,
                                                install_safety_orch):
    install_safety_orch("Do not travel to Singapore.")
    set_passport_via_api("MM")
    context, page, errors = lenient_page(ui_browser)
    try:
        goto_trip(page)
        start_goal(page, HAPPY_GOAL)
        expect(page.locator('[data-testid="approval-open"]')) \
            .to_be_visible(timeout=25000)
        page.click('[data-testid="approval-open"]')
        expect(page.locator('[data-testid="trip-approval-overlay"]')) \
            .to_be_visible()
        page.click('[data-testid="approval-approve"]')
        err = page.locator("#trip-error")
        expect(err).to_be_visible(timeout=15000)
        expect(err).to_contain_text("do-not-travel")
        expect(err).to_contain_text("does not remove the risk")
        # nothing is booked, and approval never makes the risk go away
        expect(page.locator('[data-testid="pnr-code"]')) \
            .not_to_be_visible()
        # wait for focus to return into the dialog, then close via keyboard
        expect(page.locator('[data-testid="approval-approve"]')) \
            .to_be_focused(timeout=10000)
        page.keyboard.press("Escape")
        expect(page.locator('[data-testid="trip-approval-overlay"]')) \
            .to_be_hidden(timeout=10000)
        _wait_safety_card(page)
        expect(page.locator('[data-testid="aj-safety-status"]')) \
            .to_contain_text("do not travel")
        expect(page.locator('[data-testid="pnr-code"]')) \
            .not_to_be_visible()
    finally:
        context.close()
    assert not errors, f"unexpected console errors: {errors}"


def test_ui_safety_reconsider_requires_acknowledgement(app_server,
                                                       ui_browser,
                                                       install_safety_orch):
    install_safety_orch("Reconsider your need to travel to Singapore.")
    set_passport_via_api("MM")
    context, page, errors = lenient_page(ui_browser)
    try:
        goto_trip(page)
        start_goal(page, HAPPY_GOAL)
        expect(page.locator('[data-testid="approval-open"]')) \
            .to_be_visible(timeout=25000)
        page.click('[data-testid="approval-open"]')
        expect(page.locator('[data-testid="trip-approval-overlay"]')) \
            .to_be_visible()
        # booking is blocked until the SEPARATE acknowledgement exists
        page.click('[data-testid="approval-approve"]')
        expect(page.locator("#trip-error")).to_contain_text(
            "risk acknowledgement", timeout=15000)
        expect(page.locator('[data-testid="pnr-code"]')) \
            .not_to_be_visible()
        # wait for focus to return into the dialog, then close via keyboard
        expect(page.locator('[data-testid="approval-approve"]')) \
            .to_be_focused(timeout=10000)
        page.keyboard.press("Escape")
        expect(page.locator('[data-testid="trip-approval-overlay"]')) \
            .to_be_hidden(timeout=10000)
        _wait_safety_card(page)
        expect(page.locator('[data-testid="aj-safety-status"]')) \
            .to_contain_text("reconsider")
        page.click('[data-testid="aj-safety-acknowledge"]')
        expect(page.locator('[data-testid="aj-safety-ack-badge"]')) \
            .to_be_visible(timeout=15000)
        expect(page.locator('[data-testid="aj-safety-ack-badge"]')) \
            .to_contain_text("does not remove the risk")
        # back to the plan screen: booking may now proceed to approval
        page.click('[data-testid="aj-nav-plan"]')
        expect(page.locator('[data-testid="approval-open"]')) \
            .to_be_visible(timeout=15000)
        page.click('[data-testid="approval-open"]')
        expect(page.locator('[data-testid="trip-approval-overlay"]')) \
            .to_be_visible()
        page.click('[data-testid="approval-approve"]')
        expect(page.locator('[data-testid="pnr-code"]')) \
            .to_have_text("ATLAS-UI7Q2Z", timeout=20000)
    finally:
        context.close()
    assert not errors, f"unexpected console errors: {errors}"


def test_ui_safety_recheck_and_monitor_consent(tracked_page,
                                               install_safety_orch):
    install_safety_orch("Exercise normal precautions.")
    page = tracked_page
    set_passport_via_api("MM")
    goto_trip(page)
    start_goal(page, HAPPY_GOAL)
    expect(page.locator('[data-testid="approval-open"]')) \
        .to_be_visible(timeout=25000)
    _wait_safety_card(page)
    # consent gate: monitoring starts OFF
    expect(page.locator('[data-testid="aj-safety-monitor-line"]')) \
        .to_contain_text("Monitoring is off")
    # Check again announces through the ARIA live region
    page.click('[data-testid="aj-safety-recheck"]')
    expect(page.locator("#aj-live")).to_contain_text(
        "Safety check refreshed", timeout=15000)
    # user-enabled consent flips the monitor on
    page.click('[data-testid="aj-safety-monitor-toggle"]')
    expect(page.locator('[data-testid="aj-safety-monitor-line"]')) \
        .to_contain_text("Monitoring is on", timeout=15000)
    page.screenshot(path=str(SHOTS / "g46_safety_recheck.png"),
                    full_page=True)


def test_ui_safety_card_hidden_when_pipeline_disabled(tracked_page,
                                                      install_orch):
    install_orch()  # frozen-harness shape: no safety pipeline
    page = tracked_page
    set_passport_via_api("MM")
    goto_trip(page)
    start_goal(page, HAPPY_GOAL)
    expect(page.locator('[data-testid="approval-open"]')) \
        .to_be_visible(timeout=25000)
    page.click('[data-testid="aj-nav-mytrip"]')
    page.wait_for_timeout(1200)  # grace: the card must STAY hidden
    expect(page.locator('[data-testid="aj-safety-card"]')).to_be_hidden()


def test_ui_safety_card_mobile_360_no_overflow(app_server, ui_browser,
                                               install_safety_orch):
    install_safety_orch("Do not travel to Singapore.")
    set_passport_via_api("MM")
    context = ui_browser.new_context(viewport={"width": 360,
                                               "height": 740})
    page = context.new_page()
    errors = []
    page.on("console", lambda m: errors.append(m.text)
            if m.type == "error"
            and not _THIRD_PARTY_FONT.search(m.text)
            and "Failed to load resource" not in m.text else None)
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    try:
        page.set_default_timeout(15000)
        page.goto(BASE)
        page.click('[data-testid="mnav-trip"]')  # bottom nav at 360px
        expect(page.locator("#view-trip")).to_be_visible()
        start_goal(page, HAPPY_GOAL)
        expect(page.locator('[data-testid="approval-open"]')) \
            .to_be_visible(timeout=25000)
        _wait_safety_card(page)
        expect(page.locator('[data-testid="aj-safety-status"]')) \
            .to_contain_text("do not travel")
        overflow = page.evaluate(
            "document.documentElement.scrollWidth - "
            "document.documentElement.clientWidth")
        assert overflow <= 1, f"horizontal overflow at 360px: {overflow}px"
        page.screenshot(path=str(SHOTS / "g46_safety_mobile_360.png"),
                        full_page=True)
    finally:
        context.close()
    assert not errors, f"browser console errors detected: {errors}"
