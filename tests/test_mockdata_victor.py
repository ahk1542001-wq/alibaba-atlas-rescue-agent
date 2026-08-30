"""G7/R1 — Victor demo pass ([mockdata] tag; spec §12 / PLAN R1).

Loads tracked fictional fixtures:
- data/demo_profile.json (fictional safe demo profile, user_id "victor-demo")
- data/demo_trip_goal.json (fictional trip goal for WiT Singapore)

Canonical privacy contract (§5/§12/F17):
- NO passport number, expiry, legal identity, or payment data is ever stored,
  requested, masked, or used.
- Demo fixtures are tracked, fictional, and safe.
"""

import json
import os
import re
import socket
import threading
import time
from pathlib import Path

import httpx
import pytest

from main import app
from routers.v1.profile import set_profile_store
from routers.v1.trip import TripOrchestrator, set_trip_orchestrator
from services.profile_store import ProfileStore
from services.web_intel_client import WebIntelClient
from tests.test_e2e_trip_journey import (
    FakeAtlas,
    _client,
    _fresh_fetcher,
    _no_llm,
    _resolve_scope_if_paused,
    _run,
    _start,
    _trace_names,
)

pytestmark = pytest.mark.mockdata

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO_PROFILE_PATH = REPO_ROOT / "data" / "demo_profile.json"
DEMO_TRIP_GOAL_PATH = REPO_ROOT / "data" / "demo_trip_goal.json"
BASE = "http://127.0.0.1:8050"


def _load_demo_profile() -> dict:
    assert DEMO_PROFILE_PATH.exists(), f"missing {DEMO_PROFILE_PATH}"
    return json.loads(DEMO_PROFILE_PATH.read_text(encoding="utf-8"))


def _load_demo_trip_goal() -> dict:
    assert DEMO_TRIP_GOAL_PATH.exists(), f"missing {DEMO_TRIP_GOAL_PATH}"
    return json.loads(DEMO_TRIP_GOAL_PATH.read_text(encoding="utf-8"))


# --- API journey ---------------------------------------------------------------


async def _seed_profile(client, user_id: str, profile_data: dict) -> None:
    r = await client.post(f"/api/profile/{user_id}/consent",
                          json={"store_local": True})
    assert r.status_code == 200, r.text

    # Seed safe fields from demo profile
    for field in ("passport_country", "home_city", "preferred_origin_airport",
                  "cabin", "budget_range", "display_currency"):
        field_entry = profile_data.get(field)
        val = field_entry.get("value") if isinstance(field_entry, dict) else field_entry
        if val:
            r = await client.put(f"/api/profile/{user_id}/{field}",
                                 json={"value": val})
            assert r.status_code == 200, (field, r.text)


_API_CLARIFY_FIELDS = ("origin_city", "dest_city", "date_window", "passport_country")


async def _answer_clarify_loop(client, trip_id: str, goal_data: dict, profile_data: dict) -> None:
    """Answer outstanding trip-goal questions from the demo facts."""
    home = profile_data.get("home_city", {})
    home_val = home.get("value") if isinstance(home, dict) else (home or "Bangkok")
    window = goal_data.get("date_window") or {}
    defaults = {
        "origin_city": goal_data.get("origin_city") or home_val,
        "dest_city": goal_data.get("dest_city") or "Singapore",
        "date_window": f"{window.get('start') or '2026-09-28'} - "
                       f"{window.get('end') or '2026-09-30'}",
        "passport_country": "MM",
    }
    for _ in range(4):
        state = (await client.get(f"/api/trip/{trip_id}/state")).json()
        if state["status"] == "awaiting_approval":
            return
        questions = ((state.get("outputs") or {}).get("clarify") or {}) \
            .get("questions") or []
        pending = [q for q in questions
                   if q.get("field") in _API_CLARIFY_FIELDS]
        if not pending:
            return
        for q in pending:
            r = await client.post(
                f"/api/trip/{trip_id}/clarify-answers",
                json={"field": q["field"], "value": defaults.get(q["field"], "Bangkok")})
            assert r.status_code == 200, (q["field"], r.text)


async def _journey(profile_data: dict, goal_data: dict, tmp_path: Path) -> dict:
    """Full trip journey using tracked fictional demo fixtures."""
    user_id = str(profile_data.get("user_id") or "victor-demo")
    store = ProfileStore(root=tmp_path / "profiles")
    set_profile_store(store)
    orch = TripOrchestrator(
        profile_store=store,
        atlas=FakeAtlas(),
        web_intel=WebIntelClient(ddg_fetcher=_fresh_fetcher(),
                                 tavily_api_key="", serper_api_key=""),
        llm_chat=_no_llm)
    set_trip_orchestrator(orch)
    try:
        async with _client() as client:
            await _seed_profile(client, user_id, profile_data)

            prof = (await client.get(f"/api/profile/{user_id}")).json()
            blob = json.dumps(prof)
            assert "passport_no" not in blob
            assert "passport_no_masked" not in blob
            assert prof["identity"]["passport_country"] == "MM"

            goal_text = goal_data.get("raw_text") or "Fly Bangkok to Singapore Sep 29-30"
            trip_id = await _start(client, goal_text, user_id)
            await _resolve_scope_if_paused(client, trip_id, "complete_trip")
            await _answer_clarify_loop(client, trip_id, goal_data, profile_data)

            state = (await client.get(f"/api/trip/{trip_id}/state")).json()
            assert state["status"] == "awaiting_approval", state["status"]
            names = _trace_names(state)
            assert "goal_intake" in names and "visa_check" in names
            assert names.index("visa_check") < names.index("approve_booking")

            approvals = (await client.get(
                f"/api/trip/{trip_id}/approvals")).json()["approvals"]
            gate = next(a for a in approvals
                        if a["node_name"] == "approve_booking")
            option_ids = [o["id"] for o in gate["options"]]
            assert option_ids

            resp = await client.post(
                f"/api/trip/{trip_id}/approvals/{gate['approval_id']}",
                json={"decision": "approve",
                      "value": {"option_id": option_ids[0]}},
                headers={"Idempotency-Key":
                         "00000000-0000-4000-8000-000000000001"})
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["status"] == "completed"
            assert re.fullmatch(r"ATLAS-[0-9A-Z]{6}", body["booking"]["pnr"])

            # Verify no passport number in final profile or booking
            prof = (await client.get(f"/api/profile/{user_id}")).json()
            assert "passport_no" not in json.dumps(prof)
            assert "passport_number" not in json.dumps(body.get("booking", {}))
            return body
    finally:
        set_trip_orchestrator(None)
        set_profile_store(None)


def test_demo_fixtures_contract():
    """Verify demo_profile.json and demo_trip_goal.json exist and contain fictional data only."""
    prof = _load_demo_profile()
    goal = _load_demo_trip_goal()

    assert prof["user_id"] == "victor-demo"
    assert prof["passport_country"]["value"] == "MM"
    assert prof["home_city"]["value"] == "Bangkok"
    assert "passport_no" not in prof
    assert "passport_number" not in prof
    assert "expiry" not in prof

    assert goal["goal_id"] == "demo-goal-wit-sg"
    assert "WiT Singapore" in goal["raw_text"]
    assert goal["origin_city"] == "Bangkok"
    assert goal["dest_city"] == "Singapore"


def test_mockdata_journey_run_path_demo_fixtures(tmp_path):
    """The [mockdata] journey machinery proven with tracked fictional fixtures."""
    prof = _load_demo_profile()
    goal = _load_demo_trip_goal()
    _run(_journey(prof, goal, tmp_path))


# --- browser journey -------------------------------------------------------------


@pytest.fixture()
def victor_server(tmp_path):
    """Boot the real app on 127.0.0.1:8050 (G4 app_server pattern)."""
    import uvicorn
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if probe.connect_ex(("127.0.0.1", 8050)) == 0:
            pytest.skip("port 8050 busy — rerun when free")
    store = ProfileStore(root=tmp_path / "profiles")
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
    yield store
    server.should_exit = True
    thread.join(timeout=10)
    set_trip_orchestrator(None)
    set_profile_store(None)


_FONT_NOISE = re.compile(r"fonts\.(googleapis|gstatic)\.com")
_CLARIFY_DEFAULTS = {"date_window": "Sep 29-30", "passport_country": "MM",
                     "origin_city": "Bangkok", "dest_city": "Singapore",
                     "home_city": "Bangkok", "passengers": "1"}


def _browser_goal_to_options(profile_data: dict, goal_data: dict, store) -> None:
    from playwright.sync_api import expect, sync_playwright

    from tests.test_ui_trip import answer_chip, goto_trip, start_goal
    user_id = str(profile_data.get("user_id") or "victor-demo")
    store.set_consent(user_id, True)
    pc = profile_data.get("passport_country")
    pc_val = pc.get("value") if isinstance(pc, dict) else pc
    hc = profile_data.get("home_city")
    hc_val = hc.get("value") if isinstance(hc, dict) else hc
    store.set_identity(user_id, passport_country=pc_val, home_city=hc_val)

    with sync_playwright() as engine:
        browser = engine.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        console_errors = []
        page.on("console", lambda msg: console_errors.append(msg.text)
                if msg.type == "error" else None)
        page.on("pageerror", lambda exc: console_errors.append(str(exc)))
        goto_trip(page)
        start_goal(page, goal_data.get("raw_text", "Fly Bangkok to Singapore Sep 29-30"))

        for _ in range(12):
            search_btn = page.locator('[data-testid="aj-search-now-btn"]')
            if search_btn.count() and search_btn.is_visible():
                search_btn.click()
                page.wait_for_timeout(800)
                continue
            scope_btn = page.locator(
                '[data-testid="scope-choice-complete_trip"]')
            if scope_btn.count() and scope_btn.is_visible():
                scope_btn.click()
                page.wait_for_timeout(800)
                continue
            chip = page.locator("[data-testid^='chip-input-']:visible").first
            if chip.count():
                field = chip.get_attribute("data-testid")[
                    len("chip-input-"):]
                answer_chip(page, field,
                            _CLARIFY_DEFAULTS.get(field, "Bangkok"))
                continue
            if page.locator('[data-testid="approval-open"]').count() \
                    or page.locator(
                        '[data-testid="trip-option-card"]:visible').count():
                break
            page.wait_for_timeout(1000)

        expect(page.locator('[data-testid="approval-open"]')
               ).to_be_visible(timeout=30000)
        assert page.locator('[data-testid="trip-option-card"]').count() >= 1
        page.screenshot(path="screenshots/g7_mockdata_browser.png")
        real_errors = [e for e in console_errors
                       if not _FONT_NOISE.search(e)]
        assert real_errors == [], real_errors
        browser.close()


def test_mockdata_browser_run_path_demo_fixtures(victor_server):
    """The [mockdata] browser flow proven with tracked fictional fixtures."""
    prof = _load_demo_profile()
    goal = _load_demo_trip_goal()
    _browser_goal_to_options(prof, goal, victor_server)
