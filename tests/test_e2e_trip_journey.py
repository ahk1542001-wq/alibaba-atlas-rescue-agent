"""G3 E2E journey tests — §8 test plan (trip/profile/skills API integration).

Scope (task #4 contracts):
- happy full-trip path: no personal data; LLM stubbed for clarify; LIVE Atlas
  sandbox for search/book with provenance assertions. If the sandbox is
  unreachable the test records it honestly in BLOCKERS.md and runs the
  documented curated fallback (provenance stays 'sandbox') — never fakes.
- flight-only intent: hotel/activities/local-transport are NOT executed.
- ambiguous scope: pauses with exactly three clarification choices.
- visa-block reroute: block surfaced in state; booking never completes on a
  blocked route; the reroute back to flight_search is visible in the trace.
- stale/unverified visa data blocks booking recoverably (offline + stale).
- disruption path: simulate-disruption requires ?allow_sim=1 and validates
  trip_id; the frozen DisruptionRecoveryDAG mounts as a subgraph.
- visa baseline <=50ms timing assertion + honest offline degrade.
- adversarial mappings: unknown trip/approval -> 404, already_resolved -> 409,
  approval_expired -> 410 recoverable, concurrent approvals -> single winner,
  provider failures degrade (never fabricate), start-validation guards.
"""

import asyncio
import json
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport

from main import app
from routers.v1.profile import set_profile_store
from routers.v1.trip import TripOrchestrator, set_trip_orchestrator
from services.profile_store import ProfileStore
from services.skills.visa_check import VisaCheckSkill
from services.trip_graph import SCOPE_CHOICES, GraphApprovalError
from services.web_intel_client import WebIntelClient

HAPPY_GOAL = ("I need to get to WiT Singapore, Marina Bay Sands, Sep 29-30 "
              "— plan my whole trip from Bangkok.")
AMBIGUOUS_GOAL = "I need to get to Singapore from Bangkok."
BOOK_GOAL = "I need to book a flight from Bangkok to Singapore on 2026-09-29."
BLOCKED_GOAL = "Book a flight from Yangon to Frankfurt on 2026-09-28."

CANNED_OFFER_IDS = {"off_atlas_sq_711", "off_atlas_scoot_302",
                    "off_atlas_mai_801", "off_atlas_airasia_502",
                    "off_atlas_thai_903", "off_atlas_bangkokair_104"}
_BLOCKER_MARKER = "G3-E2E atlas sandbox unreachable"


def _run(coro):
    return asyncio.run(coro)


async def _no_llm(*args, **kwargs):
    """Stubbed LLM: goal_intake falls back to its deterministic extractor."""
    return None


# --- fakes ----------------------------------------------------------------------


class FakeAtlas:
    """Deterministic Atlas stand-in; records every call for assertions."""

    def __init__(self, fail_search: bool = False) -> None:
        self.calls = []
        self.fail_search = fail_search

    async def search_flights(self, origin, destination, date_, passengers=1,
                             **kwargs):
        self.calls.append(("search", origin, destination))
        if self.fail_search:
            raise ConnectionError("atlas sandbox outage (simulated)")
        return [{
            "offer_id": "off_fake_1", "airline_code": "SQ",
            "airline": "Singapore Airlines", "flight_number": "SQ712",
            "origin": origin, "destination": destination,
            "departure_time": f"{date_} 09:30",
            "arrival_time": f"{date_} 11:00",
            "duration_minutes": 150, "price_usd": 210.0, "currency": "USD",
        }]

    async def verify_fare(self, offer_id):
        self.calls.append(("verify", offer_id))
        return {"verified": True, "offer_id": offer_id,
                "verified_at": datetime.now(timezone.utc).isoformat()}

    async def create_booking_order(self, offer_id, passenger, **kwargs):
        self.calls.append(("create", offer_id))
        return {"order_id": "ORD-E2E1", "pnr": "ATLAS-E2E9ZZ",
                "status": "CONFIRMED", "offer_id": offer_id,
                "booking_timestamp": datetime.now(timezone.utc).isoformat()}


def _fresh_fetcher():
    """ddg-lite stand-in returning a real-clock fresh citation."""
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
    """Citation whose REAL fetch instant is days old -> freshness 'stale'.

    The post-fix web-intel client stamps its own real fetch time onto
    undated payloads, so a genuinely stale result must carry an old
    fetched_at — mirroring a cached/archived retrieval."""
    old_dt = datetime.now(timezone.utc) - timedelta(days=days)
    old_iso = old_dt.isoformat()

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


# --- live sandbox probe (honest evidence; never faked) ---------------------------

_LIVE: bool | None = None


def live_sandbox_available() -> bool:
    """Probe the official atlas-flight CLI once (BKK->SIN, future date)."""
    global _LIVE
    if _LIVE is None:
        async def probe():
            from services.atlas_client import AtlasClient
            depart = (date.today() + timedelta(days=30)).isoformat()
            offers = await AtlasClient().cli_search_flights(
                "BKK", "SIN", depart, 1, "USD")
            return bool(offers)
        try:
            _LIVE = asyncio.run(probe())
        except Exception:  # noqa: BLE001 — unreachable == not live
            _LIVE = False
    return _LIVE


def _record_sandbox_blocker(detail: str) -> None:
    path = Path(__file__).resolve().parent.parent / "BLOCKERS.md"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if _BLOCKER_MARKER in text:
        return
    entry = (f"\n- [{date.today().isoformat()}] {_BLOCKER_MARKER}: {detail} "
             "— happy-path E2E ran on the documented curated fallback "
             "(provenance 'sandbox'); nothing was fabricated.\n")
    path.write_text(text.rstrip() + "\n" + entry, encoding="utf-8")


# --- harness ----------------------------------------------------------------------


@pytest.fixture
def harness(tmp_path):
    store = ProfileStore(root=tmp_path / "profiles")
    set_profile_store(store)

    def build(atlas=None, fetcher=None, live_atlas: bool = False):
        from services.atlas_client import AtlasClient
        if atlas is None:
            atlas = AtlasClient() if live_atlas else FakeAtlas()
        web = WebIntelClient(ddg_fetcher=fetcher if fetcher is not None
                             else _fresh_fetcher(),
                             tavily_api_key="", serper_api_key="")
        orch = TripOrchestrator(profile_store=store, atlas=atlas,
                                web_intel=web, llm_chat=_no_llm)
        set_trip_orchestrator(orch)
        return orch

    yield build
    set_trip_orchestrator(None)
    set_profile_store(None)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app),
                             base_url="http://testserver")


async def _start(client, goal, user_id="g3_user"):
    resp = await client.post("/api/trip/start",
                             json={"goal_text": goal, "user_id": user_id})
    assert resp.status_code == 200, resp.text
    return resp.json()["trip_id"]


async def _resolve_scope_if_paused(client, trip_id, choice):
    state = (await client.get(f"/api/trip/{trip_id}/state")).json()
    if state["status"] != "awaiting_approval":
        return state
    approvals = (await client.get(
        f"/api/trip/{trip_id}/approvals")).json()["approvals"]
    scope = next(a for a in approvals if a["node_name"] == "scope_clarification")
    resp = await client.post(
        f"/api/trip/{trip_id}/approvals/{scope['approval_id']}",
        json={"decision": choice, "value": {"choice": choice}})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _trace_names(state) -> list:
    return [n["name"] for n in state["nodes"]]


# --- journeys ------------------------------------------------------------------------


def test_happy_full_trip_no_personal_data_live_sandbox(harness):
    """Complete trip end-to-end: empty profile -> goal -> search -> visa ->
    approval gate -> booking -> monitor -> leisure research -> itinerary."""
    live = live_sandbox_available()
    harness(live_atlas=True, fetcher=_fresh_fetcher())

    async def flow():
        async with _client() as client:
            # (a) new users start EMPTY — the demo fixture never auto-loads
            prof = (await client.get("/api/profile/g3_user")).json()
            assert prof["identity"]["passport_country"] in (None, "")
            assert prof["identity"]["passport_no_masked"] in (None, "")

            # generic passport country only — NO personal data anywhere
            put = await client.put("/api/profile/g3_user/passport_country",
                                   json={"value": "MM", "source": "user"})
            assert put.status_code == 200

            trip_id = await _start(client, HAPPY_GOAL, "g3_user")

            # pauses at the booking approval gate, visa check already ran
            state = (await client.get(f"/api/trip/{trip_id}/state")).json()
            assert state["status"] == "awaiting_approval"
            names = _trace_names(state)
            assert "goal_intake" in names and "clarify_loop" in names
            assert names.index("visa_check") < names.index("approve_booking")
            visa = state["outputs"]["visa_check"]
            assert visa["degraded"] is False
            assert visa["freshness_state"] == "fresh"
            assert visa["visa_blocked"] is False

            # approvals expose exactly the search options
            approvals = (await client.get(
                f"/api/trip/{trip_id}/approvals")).json()["approvals"]
            gate = next(a for a in approvals if a["node_name"] == "approve_booking")
            option_ids = [o["id"] for o in gate["options"]]
            search_ids = [o["id"] for o in
                          state["outputs"]["flight_search"]["options"]]
            assert option_ids == search_ids and option_ids

            # provenance: live sandbox offers must not be canned ids
            if live:
                assert not set(option_ids) & CANNED_OFFER_IDS, (
                    "live sandbox returned canned offer ids — results must "
                    "come from the real Atlas sandbox")
            else:
                _record_sandbox_blocker(
                    "live CLI probe returned no offers for BKK->SIN at "
                    "test time")
            assert state["outputs"]["flight_search"]["provenance"] == "sandbox"

            # approve -> book -> complete
            resp = await client.post(
                f"/api/trip/{trip_id}/approvals/{gate['approval_id']}",
                json={"decision": "approve",
                      "value": {"option_id": option_ids[0]}})
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["status"] == "completed"
            assert re.fullmatch(r"ATLAS-[0-9A-Z]{6}", body["booking"]["pnr"])

            state = (await client.get(f"/api/trip/{trip_id}/state")).json()
            names = _trace_names(state)
            assert state["status"] == "completed"
            assert state["total_latency_ms"] > 0
            for expected in ("flight_book", "disruption_monitor",
                             "hotel_research", "activities_research",
                             "local_transport_research", "itinerary"):
                assert expected in names, f"missing node {expected}"

            # SSE replay: node events + terminal status
            events = ""
            async with client.stream(
                    "GET", f"/api/trip/{trip_id}/stream") as stream:
                assert stream.status_code == 200
                async for chunk in stream.aiter_text():
                    events += chunk
            assert "event: node" in events
            assert '"status": "completed"' in events or \
                '{"status": "completed"}' in events

            # disruption hook: disabled by default, opt-in validated
            denied = await client.get(
                f"/api/trip/{trip_id}/simulate-disruption")
            assert denied.status_code == 403
            assert denied.json()["error"]["code"] == "simulation_disabled"
            sim = await client.get(
                f"/api/trip/{trip_id}/simulate-disruption?allow_sim=1")
            assert sim.status_code == 200, sim.text
            payload = sim.json()
            assert payload["mounted"] is True
            assert payload["trip_id"] == trip_id
            assert payload["subgraph"]["nodes"]

    _run(flow())


def test_visa_baseline_under_50ms_and_offline_degrades_visibly(harness):
    skill = VisaCheckSkill(web_intel=WebIntelClient(
        ddg_fetcher=_offline_fetch, tavily_api_key="", serper_api_key=""))

    t0 = time.perf_counter()
    baseline = skill._baseline("MM", ["BKK", "SIN"])
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms <= 50.0, f"visa baseline took {elapsed_ms:.1f}ms"
    assert baseline["requirements"], "baseline must carry KG/visa_guard rules"

    async def flow():
        out = await skill.run({"passport_country": "MM",
                               "route": ["BKK", "SIN"]}, {})
        assert out["baseline_only"] is True
        assert out["degraded"] is True
        assert out["freshness_state"] == "unknown"  # never 'fresh' offline
        assert out["citations"], "degrade is labeled, not silent"

    _run(flow())


def test_ambiguous_scope_pauses_with_three_choices(harness):
    harness()

    async def flow():
        async with _client() as client:
            trip_id = await _start(client, AMBIGUOUS_GOAL, "scope_user")
            state = (await client.get(f"/api/trip/{trip_id}/state")).json()
            assert state["status"] == "awaiting_approval"
            approvals = (await client.get(
                f"/api/trip/{trip_id}/approvals")).json()["approvals"]
            assert len(approvals) == 1
            scope = approvals[0]
            assert scope["node_name"] == "scope_clarification"
            choices = [o["choice"] for o in scope["options"]]
            assert choices == list(SCOPE_CHOICES) and len(choices) == 3

            # hostile choice -> 422 with the three valid options in the hint
            bad = await client.post(
                f"/api/trip/{trip_id}/approvals/{scope['approval_id']}",
                json={"decision": "approve", "value": {"choice": "deluxe"}})
            assert bad.status_code == 422
            err = bad.json()["error"]
            assert err["code"] == "invalid_scope_choice"
            assert "flight_only" in err["hint"]

    _run(flow())


def test_flight_only_intent_skips_leisure_researchers(harness):
    atlas = FakeAtlas()
    harness(atlas=atlas)

    async def flow():
        async with _client() as client:
            trip_id = await _start(client, AMBIGUOUS_GOAL, "flyonly_user")
            result = await _resolve_scope_if_paused(client, trip_id,
                                                    "flight_only")
            assert result["status"] == "completed"
            state = (await client.get(f"/api/trip/{trip_id}/state")).json()
            names = set(_trace_names(state))
            forbidden = {"visa_check", "approve_booking", "flight_book",
                         "hotel_research", "activities_research",
                         "local_transport_research", "itinerary"}
            assert not (names & forbidden), f"executed {names & forbidden}"
            assert "flight_search" in names
            kinds = [c[0] for c in atlas.calls]
            assert kinds.count("search") == 1
            assert "create" not in kinds  # never books on flight-only

    _run(flow())


def test_visa_block_route_never_silently_books(harness):
    """MM passport via FRA (BLOCKED_RISK): the block surfaces in state, the
    reroute back to flight_search is visible, and booking is impossible —
    no user override exists."""
    atlas = FakeAtlas()
    harness(atlas=atlas)

    async def flow():
        async with _client() as client:
            await client.put("/api/profile/block_user/passport_country",
                             json={"value": "MM", "source": "user"})
            trip_id = await _start(client, BLOCKED_GOAL, "block_user")
            result = await _resolve_scope_if_paused(client, trip_id,
                                                    "flight_plus_booking")
            assert result["status"] == "failed"
            err = result["error"]
            assert err["code"] == "visa_route_blocked"
            assert err["recoverable"] is True

            state = (await client.get(f"/api/trip/{trip_id}/state")).json()
            # (1) the block is surfaced in trip state
            visa = state["outputs"]["visa_check"]
            assert visa["visa_blocked"] is True
            assert any(r["risk_level"] == "block"
                       for r in visa["requirements"])
            # (2) the reroute is visible: flight_search ran again
            names = _trace_names(state)
            assert names.count("flight_search") >= 2
            # (3) booking never completes on the blocked route
            assert "flight_book" not in names
            assert "approve_booking" not in names
            assert "create" not in [c[0] for c in atlas.calls]
            failed = [n for n in state["nodes"] if n["status"] == "FAILED"]
            assert failed and failed[-1]["name"] == "visa_check"
            assert failed[-1]["details"]["error_code"] == "visa_route_blocked"

    _run(flow())


@pytest.mark.parametrize("mode", ["offline_degraded", "stale_citations"])
def test_stale_visa_blocks_booking_recoverably(harness, mode):
    """Stale or unverified visa data pauses at the gate, then refuses the
    booking recoverably with an actionable hint — and never creates an order."""
    fetcher = _offline_fetch if mode == "offline_degraded" else _stale_fetcher()
    atlas = FakeAtlas()
    harness(atlas=atlas, fetcher=fetcher)

    async def flow():
        async with _client() as client:
            await client.put("/api/profile/stale_user/passport_country",
                             json={"value": "MM", "source": "user"})
            trip_id = await _start(client, BOOK_GOAL, "stale_user")
            await _resolve_scope_if_paused(client, trip_id,
                                           "flight_plus_booking")
            state = (await client.get(f"/api/trip/{trip_id}/state")).json()
            assert state["status"] == "awaiting_approval"
            visa = state["outputs"]["visa_check"]
            if mode == "offline_degraded":
                assert visa["baseline_only"] is True
                assert visa["degraded"] is True
                assert visa["freshness_state"] == "unknown"
            else:
                assert visa["freshness_state"] == "stale"

            approvals = (await client.get(
                f"/api/trip/{trip_id}/approvals")).json()["approvals"]
            gate = next(a for a in approvals if a["node_name"] == "approve_booking")
            resp = await client.post(
                f"/api/trip/{trip_id}/approvals/{gate['approval_id']}",
                json={"decision": "approve",
                      "value": {"option_id": gate["options"][0]["id"]}})
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["status"] == "failed"
            err = body["error"]
            assert err["code"] == "visa_data_stale_or_unverified"
            assert err["recoverable"] is True
            assert err["hint"]
            assert "create" not in [c[0] for c in atlas.calls]

    _run(flow())


def test_disruption_simulation_validates_trip_id(harness):
    atlas = FakeAtlas()
    harness(atlas=atlas)

    async def flow():
        async with _client() as client:
            unknown = await client.get(
                "/api/trip/trip_nope/simulate-disruption?allow_sim=1")
            assert unknown.status_code == 404
            assert unknown.json()["error"]["code"] == "unknown_trip"

    _run(flow())


def test_adversarial_unknown_ids_and_cross_trip_isolation(harness):
    harness()

    async def flow():
        async with _client() as client:
            # unknown trip -> 404 everywhere
            for path in ("/api/trip/trip_ghost/state",
                         "/api/trip/trip_ghost/approvals",
                         "/api/trip/trip_ghost/simulate-disruption?allow_sim=1",
                         "/api/trip/trip_ghost/stream"):
                resp = await client.get(path)
                assert resp.status_code == 404, path
                assert resp.json()["error"]["code"] == "unknown_trip"

            # two paused trips: foreign approval ids are rejected
            trip_a = await _start(client, AMBIGUOUS_GOAL, "iso_a")
            trip_b = await _start(client, AMBIGUOUS_GOAL, "iso_b")
            approvals_b = (await client.get(
                f"/api/trip/{trip_b}/approvals")).json()["approvals"]
            foreign_id = approvals_b[0]["approval_id"]
            resp = await client.post(
                f"/api/trip/{trip_a}/approvals/{foreign_id}",
                json={"decision": "flight_only"})
            assert resp.status_code == 404
            assert resp.json()["error"]["code"] == "unknown_approval"

    _run(flow())


def test_double_resolve_and_concurrent_single_winner(harness):
    atlas = FakeAtlas()
    harness(atlas=atlas)

    async def flow():
        async with _client() as client:
            trip_id = await _start(client, AMBIGUOUS_GOAL, "double_user")
            approvals = (await client.get(
                f"/api/trip/{trip_id}/approvals")).json()["approvals"]
            approval_id = approvals[0]["approval_id"]

            first = await client.post(
                f"/api/trip/{trip_id}/approvals/{approval_id}",
                json={"decision": "flight_only"})
            assert first.status_code == 200
            second = await client.post(
                f"/api/trip/{trip_id}/approvals/{approval_id}",
                json={"decision": "flight_only"})
            assert second.status_code == 409
            assert second.json()["error"]["code"] == "already_resolved"

            # concurrent race: exactly one winner
            trip_id2 = await _start(client, AMBIGUOUS_GOAL, "race_user")
            approvals = (await client.get(
                f"/api/trip/{trip_id2}/approvals")).json()["approvals"]
            approval_id2 = approvals[0]["approval_id"]

            async def post():
                return await client.post(
                    f"/api/trip/{trip_id2}/approvals/{approval_id2}",
                    json={"decision": "flight_only"})

            r1, r2 = await asyncio.gather(post(), post())
            assert sorted((r1.status_code, r2.status_code)) == [200, 409]

    _run(flow())


def test_expired_approval_maps_to_410_recoverable(harness):
    orch = harness()
    err = orch._graph_error(GraphApprovalError(
        "approval_expired", "approval expired"))
    assert err.status_code == 410
    assert err.recoverable is True
    assert err.code == "approval_expired"
    assert err.hint


def test_provider_failure_degrades_recoverably(harness):
    atlas = FakeAtlas(fail_search=True)
    harness(atlas=atlas)

    async def flow():
        async with _client() as client:
            trip_id = await _start(client, AMBIGUOUS_GOAL, "fail_user")
            result = await _resolve_scope_if_paused(client, trip_id,
                                                    "flight_only")
            assert result["status"] == "failed"
            err = result["error"]
            assert err["code"] == "provider_failure"
            assert err["recoverable"] is True
            assert err["hint"]
            state = (await client.get(f"/api/trip/{trip_id}/state")).json()
            assert state["status"] == "failed"

    _run(flow())


def test_profile_api_contract_masks_and_enforces_source(harness):
    orch = harness()
    store_root = Path(orch.store.root)
    raw_passport = "MD1234567"

    async def flow():
        async with _client() as client:
            # empty-by-default profile
            first = (await client.get("/api/profile/priv_user")).json()
            assert first["identity"]["passport_no_masked"] in (None, "")

            # laundered source is enforced to "user" server-side
            put = await client.put(
                "/api/profile/priv_user/passport_no",
                json={"value": raw_passport, "source": "ai_inferred"})
            assert put.status_code == 200
            assert put.json()["source"] == "user"
            profile = put.json()["profile"]
            assert profile["identity"]["passport_no_masked"] == "MD*****67"
            assert raw_passport not in json.dumps(profile)

            # consent gate: nothing on disk without store_local
            assert not list(store_root.glob("priv_user.json"))

            # consent + masked persistence; raw bytes never hit disk
            consent = await client.post("/api/profile/priv_user/consent",
                                        json={"store_local": True})
            assert consent.status_code == 200
            await client.put("/api/profile/priv_user/home_city",
                             json={"value": "Bangkok", "source": "user"})
            disk = list(store_root.glob("priv_user.json"))
            assert disk, "consented profile must persist"
            blob = disk[0].read_text(encoding="utf-8")
            assert raw_passport not in blob
            assert "MD*****67" in blob

            # pref field round-trip + delete clears (file survives)
            await client.put("/api/profile/priv_user/diet",
                             json={"value": "vegetarian", "source": "user"})
            deleted = await client.delete("/api/profile/priv_user/diet")
            assert deleted.status_code == 200
            assert deleted.json()["deleted"] is True
            assert (await client.get("/api/profile/priv_user")).json() \
                ["prefs"]["diet"] in (None, "")

            # withdrawal removes the persisted copy
            await client.post("/api/profile/priv_user/consent",
                              json={"store_local": False})
            assert not list(store_root.glob("priv_user.json"))

            # hostile user_id -> 400
            bad = await client.get("/api/profile/bad%20user")
            assert bad.status_code == 400
            assert bad.json()["error"]["code"] == "invalid_user_id"

    _run(flow())


def test_skills_manifest_listing(harness):
    harness()

    async def flow():
        async with _client() as client:
            resp = await client.get("/api/skills")
            assert resp.status_code == 200
            body = resp.json()
            assert body["count"] == len(body["skills"]) == 11
            names = {s["name"] for s in body["skills"]}
            assert {"goal_intake", "visa_check", "flight_book"} <= names
            for skill in body["skills"]:
                assert skill["when_to_use"].strip()

    _run(flow())


def test_start_validation_and_hostile_payloads(harness):
    harness()

    async def flow():
        async with _client() as client:
            empty = await client.post("/api/trip/start",
                                      json={"goal_text": "   ",
                                            "user_id": "valid_user"})
            assert empty.status_code == 422
            assert empty.json()["error"]["code"] == "empty_goal"

            missing = await client.post("/api/trip/start",
                                        json={"goal_text": "trip please"})
            assert missing.status_code == 422  # pydantic contract

            traversal = await client.post(
                "/api/trip/start",
                json={"goal_text": AMBIGUOUS_GOAL, "user_id": "..%2Fevil"})
            # FastAPI decodes the path/body value; the store rejects it
            assert traversal.status_code in (400, 422)

    _run(flow())
