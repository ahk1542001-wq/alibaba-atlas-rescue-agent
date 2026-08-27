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
from services.trip_graph import (SCOPE_CHOICES, GraphApprovalError,
                                 GraphCapabilityViolation)
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
        self.calls.append(("search", origin, destination, date_))
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
            # canonical F17: no passport-number field exists anywhere
            assert "passport_no_masked" not in prof["identity"]
            assert "passport_no" not in json.dumps(prof)

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
                      "value": {"option_id": option_ids[0]}},
                headers={"Idempotency-Key": "happy-booking-001"})
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
                      "value": {"option_id": gate["options"][0]["id"]}},
                headers={"Idempotency-Key": f"stale-booking-{mode}"})
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


def test_profile_api_contract_refuses_passport_and_enforces_source(harness):
    """Canonical R1 contract: NO passport number is ever requested,
    accepted, masked, or stored — forbidden shapes get a recoverable §6
    refusal; safe fields carry enforced source tags."""
    orch = harness()
    store_root = Path(orch.store.root)
    raw_passport = "MD1234567"

    async def flow():
        async with _client() as client:
            # empty-by-default profile; no passport-number field exists
            first = (await client.get("/api/profile/priv_user")).json()
            assert "passport_no_masked" not in first["identity"]

            # passport-number shape is REFUSED at the boundary (never
            # accepted, masked, or stored); the value is never echoed
            put = await client.put(
                "/api/profile/priv_user/passport_no",
                json={"value": raw_passport, "source": "ai_inferred"})
            assert put.status_code == 400
            err = put.json()["error"]
            assert err["code"] == "forbidden_profile_field"
            assert err["recoverable"] is True
            assert raw_passport not in put.text
            for alias in ("passport_number", "expiry"):
                refused = await client.put(
                    f"/api/profile/priv_user/{alias}",
                    json={"value": raw_passport, "source": "user"})
                assert refused.status_code == 400
                assert refused.json()["error"]["code"] == \
                    "forbidden_profile_field"

            # laundered source on a SAFE field is enforced to "user"
            put = await client.put(
                "/api/profile/priv_user/home_city",
                json={"value": "Bangkok", "source": "ai_inferred"})
            assert put.status_code == 200
            assert put.json()["source"] == "user"

            # consent gate: nothing on disk without store_local
            assert not list(store_root.glob("priv_user.json"))

            # consent + safe persistence; the canary never reaches disk
            consent = await client.post("/api/profile/priv_user/consent",
                                        json={"store_local": True})
            assert consent.status_code == 200
            await client.put("/api/profile/priv_user/home_city",
                             json={"value": "Bangkok", "source": "user"})
            disk = list(store_root.glob("priv_user.json"))
            assert disk, "consented profile must persist"
            blob = disk[0].read_text(encoding="utf-8")
            assert raw_passport not in blob

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
            assert body["count"] == len(body["skills"]) == 14
            names = {s["name"] for s in body["skills"]}
            assert {"goal_intake", "visa_check", "flight_book", "location_resolve", "recovery_plan"} <= names
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


# --- G3 Devil's Advocate remediation regressions (findings 1-7) -------------------


def test_put_values_are_validated_before_assignment_and_persist(harness):
    """F1: PUT must rebuild the pydantic models before assigning, so hostile
    values (int cabin, non-list airlines_like) are refused with the §6 envelope and
    can never corrupt the profile on disk."""
    orch = harness()
    store_root = Path(orch.store.root)

    async def flow():
        async with _client() as client:
            bad_cabin = await client.put("/api/profile/val_user/cabin",
                                         json={"value": 123})
            assert bad_cabin.status_code == 400
            err = bad_cabin.json()["error"]
            assert err["code"] == "invalid_profile_request"
            assert err["recoverable"] is True

            bad_airlines = await client.put("/api/profile/val_user/airlines_like",
                                            json={"value": "not-a-list"})
            assert bad_airlines.status_code == 400
            assert bad_airlines.json()["error"]["code"] == \
                "invalid_profile_request"

            # valid values keep working
            ok = await client.put("/api/profile/val_user/cabin",
                                  json={"value": "business"})
            assert ok.status_code == 200
            ok2 = await client.put("/api/profile/val_user/passport_country",
                                   json={"value": "MM"})
            assert ok2.status_code == 200

            # corruption must be impossible: consent + persist, attempt an
            # invalid write, then a FRESH store must load without error
            await client.post("/api/profile/val_user/consent",
                              json={"store_local": True})
            await client.put("/api/profile/val_user/diet",
                             json={"value": "vegetarian"})
            refused = await client.put("/api/profile/val_user/cabin",
                                       json={"value": 123})
            assert refused.status_code == 400
            fresh = ProfileStore(root=store_root)
            profile = fresh.get_or_create("val_user")  # raises if corrupt
            assert profile.prefs.cabin == "business"
            assert profile.prefs.diet == "vegetarian"
            assert profile.identity.passport_country == "MM"

    _run(flow())


def test_corrupt_on_disk_profile_degrades_to_recoverable_envelope(harness):
    """F1: a profile file that cannot parse must degrade to a recoverable
    §6 envelope — never a bare 500, never a mislabeled invalid_user_id."""
    orch = harness()
    root = Path(orch.store.root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "corrupt_user.json").write_text(
        json.dumps({"user_id": "corrupt_user", "prefs": {"cabin": 123}}),
        encoding="utf-8")

    async def flow():
        async with _client() as client:
            resp = await client.get("/api/profile/corrupt_user")
            assert resp.status_code == 400
            err = resp.json()["error"]
            assert err["code"] == "profile_unreadable"
            assert err["recoverable"] is True
            assert err.get("hint")
            # the same degradation applies on the trip boundary
            start = await client.post(
                "/api/trip/start",
                json={"goal_text": AMBIGUOUS_GOAL,
                      "user_id": "corrupt_user"})
            assert start.status_code == 400
            assert start.json()["error"]["code"] == "profile_unreadable"

    _run(flow())


def test_put_passport_no_non_string_refused_with_envelope(harness):
    """F2 / R1: passport_no shape is refused at boundary with forbidden_profile_field;
    safe identity fields reject non-string values with invalid_profile_request."""
    harness()

    async def flow():
        async with _client() as client:
            resp = await client.put("/api/profile/pass_user/passport_no",
                                    json={"value": 12345678})
            assert resp.status_code == 400
            err = resp.json()["error"]
            assert err["code"] == "forbidden_profile_field"
            assert err["recoverable"] is True
            # same guard covers the safe identity-shaped fields for non-string values
            for field, value in (("passport_country", 99),
                                 ("home_city", ["Bangkok"])):
                bad = await client.put(f"/api/profile/pass_user/{field}",
                                       json={"value": value})
                assert bad.status_code == 400, field
                assert bad.json()["error"]["code"] == "invalid_profile_request"

    _run(flow())


def test_hostile_goal_maps_to_invalid_goal_not_user_id(harness):
    """F3: goal-construction failures return 422 invalid_goal with a
    sanitized message; invalid_user_id is reserved for the user_id check and
    runs first."""
    harness()

    async def flow():
        async with _client() as client:
            resp = await client.post(
                "/api/trip/start",
                json={"goal_text": "fly BKK to Singapore Sep 31",
                      "user_id": "hostile_user"})
            assert resp.status_code == 422
            err = resp.json()["error"]
            assert err["code"] == "invalid_goal"
            assert err["recoverable"] is True
            blob = json.dumps(err).lower()
            assert "pydantic" not in blob
            assert "errors.pydantic.dev" not in blob

            bad_user = await client.post(
                "/api/trip/start",
                json={"goal_text": AMBIGUOUS_GOAL, "user_id": "bad user!"})
            assert bad_user.status_code == 400
            assert bad_user.json()["error"]["code"] == "invalid_user_id"

    _run(flow())


def test_malformed_request_bodies_use_section6_envelope(harness):
    """F4: malformed/missing bodies on the trip/profile/skills surface return
    the §6 envelope (code invalid_request), while legacy routes outside the
    scope keep FastAPI's default detail shape."""
    harness()

    async def flow():
        async with _client() as client:
            missing = await client.post("/api/trip/start",
                                        json={"goal_text": "trip please"})
            assert missing.status_code == 422
            err = missing.json()["error"]
            assert err["code"] == "invalid_request"
            assert err["recoverable"] is True
            assert "user_id" in err["message"]
            assert "loc" not in json.dumps(missing.json())

            wrong_type = await client.post(
                "/api/profile/env_user/consent",
                json={"store_local": "maybe"})
            assert wrong_type.status_code == 422
            assert wrong_type.json()["error"]["code"] == "invalid_request"

            bad_json = await client.post(
                "/api/trip/start", content=b"{not json",
                headers={"Content-Type": "application/json"})
            assert bad_json.status_code in (400, 422)
            assert bad_json.json()["error"]["code"] == "invalid_request"

            # out-of-scope legacy route: default FastAPI detail preserved
            legacy = await client.post("/api/rescue/book", json={})
            assert legacy.status_code == 422
            assert "detail" in legacy.json()
            assert "error" not in legacy.json()

    _run(flow())


def test_oversize_goal_text_rejected_with_envelope(harness):
    """F6: goal_text is bounded (max 4000 chars); oversize payloads are
    refused at the boundary with the §6 envelope."""
    harness()

    async def flow():
        async with _client() as client:
            resp = await client.post("/api/trip/start",
                                     json={"goal_text": "x" * 4001,
                                           "user_id": "size_user"})
            assert resp.status_code == 422
            err = resp.json()["error"]
            assert err["code"] == "invalid_request"
            assert err["recoverable"] is True

    _run(flow())


def test_production_executor_is_fail_closed_with_documented_exemption(harness):
    """F5: the production executor is constructed fail-closed; the three
    research adapters are registered as explicitly capability-empty manifest
    entries (documented exemption), and a boot assertion refuses any
    unmanifested skill that declares write capabilities."""
    from routers.v1.trip import _assert_manifest_governance

    orch = harness()
    ex = orch.executor
    assert ex._allow_unmanifested_skills is False
    for domain in ("hotel", "activities", "local_transport"):
        entry = ex._registry_by_name[f"{domain}_research"]
        assert entry["allowed_tools"] == []  # capability-empty exemption

    # every write/network-capable registered skill must be manifested
    _assert_manifest_governance(ex._skills, ex._registry_by_name)

    class RogueSkill:
        capabilities = frozenset({"profile_write"})

    with pytest.raises(RuntimeError):
        _assert_manifest_governance({"rogue": RogueSkill()},
                                    ex._registry_by_name)

    class EmptyHelper:
        capabilities = frozenset()

    # capability-empty helpers are the documented exemption
    _assert_manifest_governance({"helper": EmptyHelper()},
                                ex._registry_by_name)


def test_stage1_skills_run_through_capability_enforcement(harness):
    """F5: stage-1 goal_intake/clarify_loop must not bypass capability
    enforcement — stripping a manifest entry refuses execution fail-closed."""
    orch = harness()

    async def flow():
        orch.executor._registry_by_name.pop("goal_intake")
        with pytest.raises(GraphCapabilityViolation):
            await orch.start(AMBIGUOUS_GOAL, "cap_user")

    _run(flow())


# --- G4 Devil's Advocate + live-browser remediation regressions --------------------

NO_ORIGIN_GOAL = "I need to get to Singapore on 2026-09-29."


def test_date_window_is_forwarded_to_atlas_search(harness):
    """G4-DA-fix F5: the goal's date_window.start must reach the Atlas
    search call unmodified; the search output honestly reports the
    requested date and labels any near-term substitution instead of
    silently presenting other dates as the requested window."""
    atlas = FakeAtlas()
    harness(atlas=atlas)

    async def flow():
        async with _client() as client:
            await client.put("/api/profile/date_user/passport_country",
                             json={"value": "MM", "source": "user"})
            trip_id = await _start(client, BOOK_GOAL, "date_user")
            await _resolve_scope_if_paused(client, trip_id,
                                           "flight_plus_booking")
            search = [c for c in atlas.calls if c[0] == "search"]
            assert search, "flight_search never queried the sandbox"
            assert len(search) == 1
            assert search[0][1:] == ("BKK", "SIN", "2026-09-29"), search

            state = (await client.get(
                f"/api/trip/{trip_id}/state")).json()
            out = state["outputs"]["flight_search"]
            assert out["requested_date"] == "2026-09-29"
            # honored window: no substitution note; every option dated in it
            assert not out.get("date_note")
            assert all(o["dep"]["time"].startswith("2026-09-29")
                       for o in out["options"])

    _run(flow())


class ClampedAtlas(FakeAtlas):
    """Simulates the live sandbox's near-term clamp: any requested date on
    or before today is silently replaced by tomorrow — the substitution the
    skill must label, never hide."""

    async def search_flights(self, origin, destination, date_, passengers=1,
                             **kwargs):
        from datetime import timedelta
        clamped = date.today() + timedelta(days=1)
        return await super().search_flights(origin, destination,
                                            clamped.isoformat(),
                                            passengers, **kwargs)


def test_date_window_substitution_is_labeled_not_silent(harness):
    """G4-DA-fix F5: when the sandbox cannot honor the requested date
    (same-day/past window), the substitution must be labeled in the search
    output — never silently presented as the requested window."""
    atlas = ClampedAtlas()
    harness(atlas=atlas)
    today = date.today().isoformat()

    async def flow():
        async with _client() as client:
            trip_id = await _start(
                client, f"Book a flight from Bangkok to Singapore on {today}.",
                "today_user")
            result = await _resolve_scope_if_paused(client, trip_id,
                                                    "flight_only")
            assert result["status"] == "completed"
            state = (await client.get(
                f"/api/trip/{trip_id}/state")).json()
            out = state["outputs"]["flight_search"]
            assert out["requested_date"] == today
            assert out["date_note"], \
                "a substituted travel date must carry an honest note"
            assert today in out["date_note"]

    _run(flow())


def test_clarify_answer_feeds_trip_goal_and_resumes(harness):
    """G4-DA-fix F4: confirming a NON-profile clarify answer (origin_city,
    dest_city, date_window) must persist into the paused/failed trip's goal
    and resume it — previously the chip confirm was a silent no-op and the
    next run failed missing_route."""
    atlas = FakeAtlas()
    harness(atlas=atlas)

    async def flow():
        async with _client() as client:
            trip_id = await _start(client, NO_ORIGIN_GOAL, "chip_user")
            result = await _resolve_scope_if_paused(client, trip_id,
                                                    "flight_only")
            assert result["status"] == "failed"
            assert result["error"]["code"] == "missing_route"

            resp = await client.post(
                f"/api/trip/{trip_id}/clarify-answers",
                json={"field": "origin_city", "value": "Bangkok"})
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["status"] == "completed"
            assert body["clarify"]["field"] == "origin_city"
            assert body["clarify"]["value"] == "BKK"  # alias -> IATA

            state = (await client.get(
                f"/api/trip/{trip_id}/state")).json()
            options = state["outputs"]["flight_search"]["options"]
            assert options and all(o["dep"]["airport"] == "BKK"
                                   for o in options)
            # the answered question no longer appears in clarify output
            questions = [q["field"] for q in
                         state["outputs"]["clarify"]["questions"]]
            assert "origin_city" not in questions

    _run(flow())


def test_clarify_answer_date_window_parses_and_rejects_garbage(harness):
    """G4-DA-fix F4: date_window answers parse into a real window; hostile
    or unknown payloads get the §6 envelope, never a silent 200."""
    harness()

    async def flow():
        async with _client() as client:
            trip_id = await _start(client, NO_ORIGIN_GOAL, "datechip_user")
            await _resolve_scope_if_paused(client, trip_id, "flight_only")

            bad_date = await client.post(
                f"/api/trip/{trip_id}/clarify-answers",
                json={"field": "date_window", "value": "sometime soon"})
            assert bad_date.status_code == 422
            assert bad_date.json()["error"]["code"] == \
                "invalid_clarify_answer"

            ok_date = await client.post(
                f"/api/trip/{trip_id}/clarify-answers",
                json={"field": "date_window", "value": "Sep 29-30"})
            assert ok_date.status_code == 200, ok_date.text
            assert ok_date.json()["clarify"]["value"] == \
                {"start": "2026-09-29", "end": "2026-09-30"}

            bad_field = await client.post(
                f"/api/trip/{trip_id}/clarify-answers",
                json={"field": "passport_no", "value": "MD123"})
            assert bad_field.status_code == 422
            assert bad_field.json()["error"]["code"] == \
                "invalid_clarify_field"

            unknown = await client.post(
                "/api/trip/trip_ghost/clarify-answers",
                json={"field": "origin_city", "value": "BKK"})
            assert unknown.status_code == 404
            assert unknown.json()["error"]["code"] == "unknown_trip"

    _run(flow())


def test_stream_terminates_on_idle_timeout_for_unresolved_trip(
        harness, monkeypatch):
    """F7: a trip whose approval is never resolved must not keep the SSE
    stream open forever — it emits a final status event and terminates; the
    trip itself stays paused."""
    import routers.v1.trip as trip_mod
    monkeypatch.setattr(trip_mod, "STREAM_IDLE_TIMEOUT_SECONDS", 0.6)
    monkeypatch.setattr(trip_mod, "STREAM_MAX_LIFETIME_SECONDS", 5.0)
    harness()

    async def flow():
        async with _client() as client:
            trip_id = await _start(client, AMBIGUOUS_GOAL, "sse_user")
            events = ""
            t0 = time.perf_counter()
            async with client.stream(
                    "GET", f"/api/trip/{trip_id}/stream") as stream:
                assert stream.status_code == 200
                async for chunk in stream.aiter_text():
                    events += chunk
            elapsed = time.perf_counter() - t0
            assert elapsed < 4.5, f"stream kept open {elapsed:.1f}s"
            assert "event: status" in events
            assert "stream_timeout" in events
            # the stream gave up; the trip did not
            state = (await client.get(
                f"/api/trip/{trip_id}/state")).json()
            assert state["status"] == "awaiting_approval"

    _run(flow())


# ==============================================================================
# §6 CANONICAL PLURAL ROUTE & IDEMPOTENCY-KEY TESTS (R4)
# ==============================================================================

def test_api_skills_thirteen_skills(harness):
    """GET /api/skills returns all 13 validated runnable skills."""
    harness()

    async def flow():
        async with _client() as client:
            resp = await client.get("/api/skills")
            assert resp.status_code == 200
            data = resp.json()
            assert data["count"] == 14
            names = {s["name"] for s in data["skills"]}
            assert "location_resolve" in names
            assert "recovery_plan" in names

    _run(flow())


def test_plural_api_trips_endpoints_and_idempotency_key(harness):
    """§6 Plural /api/trips/* endpoints and Idempotency-Key replay / conflict behavior."""
    harness()

    async def flow():
        async with _client() as client:
            # 1. POST /api/trips
            start_resp = await client.post(
                "/api/trips",
                json={"goal_text": AMBIGUOUS_GOAL, "user_id": "victor-idemp"})
            assert start_resp.status_code == 200
            trip_id = start_resp.json()["trip_id"]

            # 2. GET /api/trips/{trip_id} summary
            sum_resp = await client.get(f"/api/trips/{trip_id}")
            assert sum_resp.status_code == 200
            assert sum_resp.json()["trip_id"] == trip_id

            # 3. GET /api/trips/{trip_id}/state
            state_resp = await client.get(f"/api/trips/{trip_id}/state")
            assert state_resp.status_code == 200
            assert state_resp.json()["trip_id"] == trip_id

            # 4. GET /api/trips/{trip_id}/approvals
            appr_resp = await client.get(f"/api/trips/{trip_id}/approvals")
            assert appr_resp.status_code == 200
            approvals = appr_resp.json()["approvals"]
            assert len(approvals) >= 1
            aid = approvals[0]["approval_id"]

            # 5. POST /api/trips/{id}/approvals/{aid} with Idempotency-Key
            idemp_header = {"Idempotency-Key": "idemp-test-key-001"}
            body1 = {"decision": "flight_only"}

            # First execution
            res1 = await client.post(
                f"/api/trips/{trip_id}/approvals/{aid}",
                json=body1,
                headers=idemp_header)
            assert res1.status_code == 200
            data1 = res1.json()

            # Identical replay: returns stored receipt / response
            res2 = await client.post(
                f"/api/trips/{trip_id}/approvals/{aid}",
                json=body1,
                headers=idemp_header)
            assert res2.status_code == 200
            data2 = res2.json()
            assert data1 == data2

            # Changed payload with same key: HTTP 409 conflict
            body_conflict = {"decision": "full_package"}
            res3 = await client.post(
                f"/api/trips/{trip_id}/approvals/{aid}",
                json=body_conflict,
                headers=idemp_header)
            assert res3.status_code == 409
            assert res3.json()["error"]["code"] == "idempotency_conflict"

            # 6. POST /api/trips/{trip_id}/clarifications
            clarif_resp = await client.post(
                f"/api/trips/{trip_id}/clarifications",
                json={"answers": {"date_window": "2026-09-29 to 2026-09-30"}})
            assert clarif_resp.status_code == 200
            chips = clarif_resp.json()["confirmation_chips"]
            date_chip = next(c for c in chips if c["field"] == "date_window")

            # 7. POST /api/trips/{trip_id}/confirmations/{chip_id}
            conf_resp = await client.post(
                f"/api/trips/{trip_id}/confirmations/{date_chip['chip_id']}",
                json={"decision": "confirm"})
            assert conf_resp.status_code == 200
            assert conf_resp.json()["status"] == "confirmed"

            # 8. POST /api/trips/{trip_id}/plan
            plan_resp = await client.post(f"/api/trips/{trip_id}/plan")
            assert plan_resp.status_code == 200

            # 9. POST /api/trips/{trip_id}/simulate-disruption
            disrupt_resp = await client.post(
                f"/api/trips/{trip_id}/simulate-disruption",
                json={"scenario": "cancellation", "reason": "Weather test"})
            assert disrupt_resp.status_code == 200

    _run(flow())
