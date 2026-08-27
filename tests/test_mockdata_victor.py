"""G7 — Victor mock-data pass ([mockdata] tag; spec §12 / PLAN G7).

Loads data/mock_victor.json (gitignored; values supplied by the owner).
While the fixture is absent or still placeholder, the victor cases SKIP
gracefully with an honest reason (G7 contract: graceful skip + honest
limitation while the owner is absent). The run-path itself is proven
against a synthetic fixture so the suite runs unchanged the day real
values land; a custom fixture path can also be injected via the
MOCKDATA_FIXTURE environment variable (used to prove the path without
committing personal data).

This module commits NO personal data: the real fixture exists only on
local disk; the synthetic one uses the established test vectors.
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
from models.schemas import mask_passport
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
VICTOR_PATH = REPO_ROOT / "data" / "mock_victor.json"
BASE = "http://127.0.0.1:8050"
_PLACEHOLDER = re.compile(r"<[^<>]+>")

SYNTHETIC_FIXTURE = {
    "user_id": "victor",
    "identity": {"passport_country": "MM", "passport_no": "MD1234567",
                 "expiry": "2030-01-01", "home_city": "Bangkok"},
    "prefs": {"budget_range": "1000-3000 THB", "cabin": "economy"},
    "trip": {"goal": "Fly Bangkok to Singapore September 29 to 30",
             "window": {"start": "2026-09-28", "end": "2026-09-30"}},
}


def _fixture_path() -> Path:
    override = os.environ.get("MOCKDATA_FIXTURE")
    return Path(override) if override else VICTOR_PATH


def _load(path: Path):
    """(fixture, None) when real values exist, else (None, honest reason)."""
    if not path.exists():
        return None, f"fixture missing ({path.name}) — owner has not supplied it"
    raw = path.read_text(encoding="utf-8")
    if _PLACEHOLDER.search(raw):
        return None, "fixture still carries placeholder values — owner absent"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"fixture is invalid JSON: {exc}"
    if not (data.get("trip") or {}).get("goal"):
        return None, "fixture incomplete (trip.goal missing)"
    return data, None


# --- API journey ---------------------------------------------------------------


async def _seed_profile(client, user_id: str, fixture: dict) -> None:
    ident = fixture.get("identity") or {}
    prefs = fixture.get("prefs") or {}
    r = await client.post(f"/api/profile/{user_id}/consent",
                          json={"store_local": True})
    assert r.status_code == 200, r.text
    for field, value in (("passport_country", ident.get("passport_country")),
                         ("passport_no", ident.get("passport_no")),
                         ("expiry", ident.get("expiry")),
                         ("home_city", ident.get("home_city")),
                         ("cabin", prefs.get("cabin"))):
        if value:
            r = await client.put(f"/api/profile/{user_id}/{field}",
                                 json={"value": value})
            assert r.status_code == 200, (field, r.text)


_API_CLARIFY_FIELDS = ("origin_city", "dest_city", "date_window")


async def _answer_clarify_loop(client, trip_id: str, fixture: dict) -> None:
    """API mirror of the UI one-at-a-time clarify loop: answer outstanding
    trip-goal questions from the fixture facts; the orchestrator resumes a
    trip that failed on the now-complete route (G4-DA-fix F4 semantics)."""
    ident = fixture.get("identity") or {}
    window = (fixture.get("trip") or {}).get("window") or {}
    defaults = {
        "origin_city": ident.get("home_city") or "Bangkok",
        "dest_city": "Singapore",
        "date_window": f"{window.get('start') or '2026-09-28'} - "
                       f"{window.get('end') or '2026-09-30'}",
    }
    for _ in range(3):
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
                json={"field": q["field"], "value": defaults[q["field"]]})
            assert r.status_code == 200, (q["field"], r.text)


async def _journey(fixture: dict, tmp_path) -> dict:
    """G3 happy path WITH opt-in personal data: seed the profile through
    the §6 API (consent first), prove masked-only display, run the trip to
    booking completion. Safety pipeline stays out of scope here (it has
    its own hermetic suites); this mirrors the G3 harness."""
    user_id = str(fixture.get("user_id") or "victor")
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
            await _seed_profile(client, user_id, fixture)

            prof = (await client.get(f"/api/profile/{user_id}")).json()
            raw_passport = (fixture.get("identity") or {}).get("passport_no")
            blob = json.dumps(prof)
            if raw_passport:
                assert raw_passport not in blob, "raw passport surfaced"
                assert mask_passport(raw_passport) in blob

            trip_id = await _start(client, fixture["trip"]["goal"], user_id)
            await _resolve_scope_if_paused(client, trip_id, "complete_trip")
            await _answer_clarify_loop(client, trip_id, fixture)
            state = (await client.get(
                f"/api/trip/{trip_id}/state")).json()
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
                      "value": {"option_id": option_ids[0]}})
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["status"] == "completed"
            assert re.fullmatch(r"ATLAS-[0-9A-Z]{6}", body["booking"]["pnr"])

            # remembered fields stay masked AFTER booking too
            prof = (await client.get(f"/api/profile/{user_id}")).json()
            if raw_passport:
                assert raw_passport not in json.dumps(prof)
            return body
    finally:
        set_trip_orchestrator(None)
        set_profile_store(None)


def test_mockdata_loader_contract(tmp_path):
    real, reason = _load(_fixture_path())
    if real is None:
        assert reason  # the skip reason is always honest and non-empty
    # synthetic real-values fixture loads
    p = tmp_path / "victor.json"
    p.write_text(json.dumps(SYNTHETIC_FIXTURE), encoding="utf-8")
    data, why = _load(p)
    assert why is None and data["user_id"] == "victor"
    # placeholder fixture refuses honestly
    p2 = tmp_path / "placeholder.json"
    p2.write_text(json.dumps({"trip": {"goal": "<REAL_GOAL>"}}),
                  encoding="utf-8")
    assert _load(p2)[0] is None
    # invalid JSON refuses honestly
    p3 = tmp_path / "broken.json"
    p3.write_text("{not json", encoding="utf-8")
    assert "invalid JSON" in _load(p3)[1]


def test_mockdata_journey_run_path_synthetic(tmp_path):
    """The [mockdata] journey machinery, proven WITHOUT owner data."""
    _run(_journey(SYNTHETIC_FIXTURE, tmp_path))


def test_mockdata_victor_journey_or_honest_skip(tmp_path):
    fixture, reason = _load(_fixture_path())
    if fixture is None:
        pytest.skip(f"G7 owner absent: {reason}")
    _run(_journey(fixture, tmp_path))


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
                     "home_city": "Bangkok"}


def _browser_goal_to_options(fixture: dict, store) -> None:
    from playwright.sync_api import expect, sync_playwright

    from tests.test_ui_trip import answer_chip, goto_trip, start_goal
    user_id = str(fixture.get("user_id") or "victor")
    ident = fixture.get("identity") or {}
    store.set_consent(user_id, True)
    ident_kwargs = {k: v for k, v in (
        ("passport_country", ident.get("passport_country")),
        ("passport_no", ident.get("passport_no"))) if v}
    if ident_kwargs:
        store.set_identity(user_id, **ident_kwargs)
    if ident.get("home_city"):
        store.set_field(user_id, "home_city", ident["home_city"],
                        source="user")
    with sync_playwright() as engine:
        browser = engine.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        console_errors = []
        page.on("console", lambda msg: console_errors.append(msg.text)
                if msg.type == "error" else None)
        page.on("pageerror", lambda exc: console_errors.append(str(exc)))
        goto_trip(page)
        start_goal(page, fixture["trip"]["goal"])

        # interleaved bounded loop: scope choice + one-at-a-time clarify
        # cards can appear in either order depending on the goal shape
        for _ in range(12):
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

        # the journey paused at the booking gate: the approval banner (AJ)
        # is the durable visible signal; option cards live in collapsed
        # steps and stay hidden by design
        expect(page.locator('[data-testid="approval-open"]')
               ).to_be_visible(timeout=30000)
        assert page.locator('[data-testid="trip-option-card"]').count() >= 1
        page.screenshot(path="screenshots/g7_mockdata_browser.png")
        real_errors = [e for e in console_errors
                       if not _FONT_NOISE.search(e)]
        assert real_errors == [], real_errors
        browser.close()


def test_mockdata_browser_run_path_synthetic(victor_server):
    """The [mockdata] browser flow, proven WITHOUT owner data."""
    _browser_goal_to_options(SYNTHETIC_FIXTURE, victor_server)


def test_mockdata_browser_victor_or_honest_skip(victor_server):
    fixture, reason = _load(_fixture_path())
    if fixture is None:
        pytest.skip(f"G7 owner absent: {reason}")
    _browser_goal_to_options(fixture, victor_server)
