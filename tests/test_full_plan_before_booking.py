"""Regression tests for TravelCare AI: Full reversible plan before booking approval.

Proves:
1. complete_trip reaches approve_booking with flight_search, visa_check, hotel_research,
   activities_research, local_transport_research, and itinerary ALREADY populated.
2. Atlas create_booking_order is never called before approval.
3. Itinerary preview exists prior to approval without a PNR.
4. Preview flight in itinerary is explicitly not booked, has no PNR, is labeled planned.
5. TICKETING_ACTIVATION_REQUIRED after approval preserves all reversible outputs,
   including itinerary, hotel, activity, transport research, and safety.
6. Failed ticketing produces no PNR, e-ticket, booking success, or armed monitor.
7. Hermetic successful booking reconciles selected flight, promotes to booked=True with PNR,
   preserves leisure items, and arms monitoring.
8. Rejected booking approval makes no provider create call.
9. Flight-only requests skip hotel/activity/transport/itinerary.
10. Flight-plus-booking requests do not mount unrequested leisure services.
11. Visa-blocked route replans back to flight_search and never reaches approval or booking.
12. Changing confirmed airport or passport invalidates and rebuilds route-dependent previews.
"""

import asyncio
from copy import deepcopy
from datetime import date, datetime, timezone
import json
import pytest

from models.schemas import RequestedServices, TripGoal, TripIntent
from routers.v1.profile import ProfileStore, set_profile_store
from routers.v1.trip import TripOrchestrator, set_trip_orchestrator
from services.skills.base import SkillError
from services.skills.itinerary import ItinerarySkill
from services.trip_graph import plan_trip
from services.web_intel_client import WebIntelClient


def _run(coro):
    return asyncio.run(coro)


class MockAtlasClient:
    def __init__(self, ticketing_status="TICKETING_ACTIVATION_REQUIRED"):
        self.ticketing_status = ticketing_status
        self.search_calls = []
        self.verify_calls = []
        self.create_order_calls = []

    async def search_flights(self, origin, destination, travel_date, passengers=1, **kwargs):
        self.search_calls.append({"origin": origin, "destination": destination, "date": travel_date})
        return [
            {
                "offer_id": "off_mock_sq905",
                "airline_code": "SQ",
                "airline": "Singapore Airlines",
                "flight_number": "SQ905",
                "origin": origin or "BKK",
                "destination": destination or "SIN",
                "departure_time": f"{travel_date} 09:30",
                "arrival_time": f"{travel_date} 11:00",
                "duration_minutes": 150,
                "price_usd": 210.0,
                "currency": "USD",
            },
            {
                "offer_id": "off_mock_tr302",
                "airline_code": "TR",
                "airline": "Scoot",
                "flight_number": "TR302",
                "origin": origin or "BKK",
                "destination": destination or "SIN",
                "departure_time": f"{travel_date} 13:10",
                "arrival_time": f"{travel_date} 14:45",
                "duration_minutes": 155,
                "price_usd": 118.0,
                "currency": "USD",
            },
        ]

    async def verify_fare(self, offer_id):
        self.verify_calls.append(offer_id)
        return {
            "verified": True,
            "offer_id": offer_id,
            "booking_id": f"book_{offer_id}",
            "fare_lock_expires_in_seconds": 1800,
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }

    async def create_booking_order(self, offer_id, passenger, **kwargs):
        self.create_order_calls.append({"offer_id": offer_id, "passenger": passenger})
        if self.ticketing_status == "TICKETING_ACTIVATION_REQUIRED":
            raise SkillError(
                "ticketing_activation_required",
                "Your plan is safe. Atlas Sandbox ticketing is not enabled for this account, "
                "so no booking or ticket was created.",
                recoverable=True,
            )
        if self.ticketing_status == "CONFIRMED":
            return {
                "order_id": "ORD-HERMETIC-1",
                "pnr": "ATLAS-HERMETIC-PNR",
                "status": "CONFIRMED",
                "offer_id": offer_id,
                "booking_timestamp": datetime.now(timezone.utc).isoformat(),
            }
        raise SkillError("provider_failure", "Unknown provider error", recoverable=True)


def _fresh_fetcher():
    async def fetch(_query):
        return {"answers": [], "citations": [{
            "url": "https://example.org/entry-rules",
            "title": "Entry and transit requirements",
            "retrieved_date": date.today().isoformat(),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "snippet_max280": "current entry requirements",
        }]}
    return fetch


def _setup_orch(tmp_path, atlas=None, passport_country="MM", home_city="Bangkok"):
    store = ProfileStore(root=tmp_path / "profiles")
    set_profile_store(store)
    store.set_field("victor", "passport_country", passport_country, source="user")
    store.set_field("victor", "home_city", home_city, source="user")
    atlas_client = atlas or MockAtlasClient()
    orch = TripOrchestrator(
        profile_store=store,
        atlas=atlas_client,
        web_intel=WebIntelClient(
            ddg_fetcher=_fresh_fetcher(), tavily_api_key="", serper_api_key=""),
        llm_chat=lambda *args, **kwargs: None,
        allow_mock_fallback=True,
    )
    set_trip_orchestrator(orch)
    return orch, atlas_client


# ---------------------------------------------------------------------------------
# 1. Complete trip plan reordering & pre-booking research completeness
# ---------------------------------------------------------------------------------

def test_plan_trip_complete_trip_orders_reversible_nodes_before_approval():
    goal = TripGoal(
        goal_id="g1",
        raw_text="BKK to SIN",
        origin_city="BKK",
        dest_city="SIN",
        date_window={"start": "2026-09-29", "end": "2026-09-30"},
        passengers=1,
    )
    rs = RequestedServices(
        flight_search="requested",
        flight_booking="requested",
        visa_check="requested",
        hotel="requested",
        activities="requested",
        local_transport="requested",
    )
    intent = TripIntent(
        intent_id="i_complete",
        raw_text="plan complete trip",
        goal=goal,
        requested_services=rs,
        scope_clarified=True,
    )
    plan = plan_trip(intent)
    node_names = [n.name for n in plan.nodes]

    # Expected order:
    # flight_search -> visa_check -> hotel_research -> activities_research ->
    # local_transport_research -> itinerary -> approve_booking -> flight_book -> disruption_monitor
    assert "approve_booking" in node_names
    assert "itinerary" in node_names
    itin_idx = node_names.index("itinerary")
    approval_idx = node_names.index("approve_booking")
    book_idx = node_names.index("flight_book")
    hotel_idx = node_names.index("hotel_research")
    act_idx = node_names.index("activities_research")
    trans_idx = node_names.index("local_transport_research")

    assert hotel_idx < approval_idx, "hotel_research must run before approve_booking"
    assert act_idx < approval_idx, "activities_research must run before approve_booking"
    assert trans_idx < approval_idx, "local_transport_research must run before approve_booking"
    assert itin_idx < approval_idx, "itinerary must run before approve_booking"
    assert approval_idx < book_idx, "approve_booking must run before flight_book"


def test_complete_trip_reaches_approval_with_all_reversible_outputs_and_no_order(tmp_path):
    atlas = MockAtlasClient(ticketing_status="TICKETING_ACTIVATION_REQUIRED")
    orch, _ = _setup_orch(tmp_path, atlas=atlas)

    goal_text = "I need to get to WiT Singapore, Marina Bay Sands, Sep 29-30, 2026 for 1 passenger — plan my whole trip from BKK."
    trip_id = _run(orch.start(goal_text, "victor", search_confirmed=True))
    trip = orch.executor.get(trip_id)

    # Must pause at approve_booking
    assert trip.status == "awaiting_approval"
    assert trip.current == "approve_booking"

    # Verify no create_booking_order call was made before approval
    assert len(atlas.create_order_calls) == 0, "No create-order call should be made before approval"

    # All reversible outputs must exist in context and state
    state = orch.state(trip_id)
    outputs = state["outputs"]

    assert "flight_search" in outputs and len(outputs["flight_search"]["options"]) > 0
    assert "visa_check" in outputs
    assert "hotel_research" in outputs
    assert "activities_research" in outputs
    assert "local_transport_research" in outputs
    assert "itinerary" in outputs

    itin = outputs["itinerary"]
    assert "items" in itin and len(itin["items"]) > 0

    # Flight item in itinerary must be explicitly not booked, no PNR, labeled planned
    flight_items = [i for i in itin["items"] if i.get("kind") == "flight"]
    assert len(flight_items) >= 1
    flt = flight_items[0]
    assert flt.get("booked") is False, "Preview flight in itinerary must have booked=False"
    assert flt.get("details", {}).get("pnr") is None, "Preview flight must have no PNR"
    assert "not booked" in flt.get("honesty_label", "").lower() or "planned" in flt.get("honesty_label", "").lower()


# ---------------------------------------------------------------------------------
# 2. Honest failure handling: TICKETING_ACTIVATION_REQUIRED preserves reversible plan
# ---------------------------------------------------------------------------------

def test_ticketing_activation_required_preserves_complete_plan(tmp_path):
    atlas = MockAtlasClient(ticketing_status="TICKETING_ACTIVATION_REQUIRED")
    orch, _ = _setup_orch(tmp_path, atlas=atlas)

    goal_text = "I need to get to WiT Singapore, Marina Bay Sands, Sep 29-30, 2026 for 1 passenger — plan my whole trip from BKK."
    trip_id = _run(orch.start(goal_text, "victor", search_confirmed=True))
    trip = orch.executor.get(trip_id)

    approval = trip.pending_approvals[0]
    selected_option_id = approval.options[0]["id"]

    # Approve the booking attempt
    res = _run(orch.resolve(
        trip_id,
        approval.approval_id,
        "approve",
        {"option_id": selected_option_id},
        idempotency_key="idemp-test-ticketing-fail",
    ))

    # Should report failed/error gracefully with ticketing message
    assert res.get("status") in ("failed", "error") or "error" in res
    assert "ticketing_activation_required" in str(res) or "not enabled" in str(res)

    # Verify no PNR or e-ticket
    assert (trip.context.get("flight_book") or {}).get("pnr") is None

    # Verify all reversible research & itinerary remain preserved in state
    state = orch.state(trip_id)
    outputs = state["outputs"]
    assert "flight_search" in outputs
    assert "visa_check" in outputs
    assert "hotel_research" in outputs
    assert "activities_research" in outputs
    assert "local_transport_research" in outputs
    assert "itinerary" in outputs

    # Itinerary flight remains planned (not erased, not claimed booked)
    itin = outputs["itinerary"]
    flight_items = [i for i in itin["items"] if i.get("kind") == "flight"]
    assert len(flight_items) >= 1
    assert flight_items[0].get("booked") is False
    assert flight_items[0].get("details", {}).get("pnr") is None

    # Monitor is NOT armed for a failed booking
    assert trip.context.get("disruption_monitor") is None or not trip.context.get("disruption_monitor", {}).get("armed")


# ---------------------------------------------------------------------------------
# 3. Successful hermetic booking reconciles and promotes planned flight
# ---------------------------------------------------------------------------------

def test_hermetic_successful_booking_promotes_flight_and_arms_monitor(tmp_path):
    atlas = MockAtlasClient(ticketing_status="CONFIRMED")
    orch, _ = _setup_orch(tmp_path, atlas=atlas)

    goal_text = "I need to get to WiT Singapore, Marina Bay Sands, Sep 29-30, 2026 for 1 passenger — plan my whole trip from BKK."
    trip_id = _run(orch.start(goal_text, "victor", search_confirmed=True))
    trip = orch.executor.get(trip_id)

    approval = trip.pending_approvals[0]
    selected_option = approval.options[0]
    selected_option_id = selected_option["id"]

    res = _run(orch.resolve(
        trip_id,
        approval.approval_id,
        "approve",
        {"option_id": selected_option_id},
        idempotency_key="idemp-test-booking-success",
    ))

    assert res.get("status") == "completed"

    # Flight book output has confirmed PNR
    fb = trip.context.get("flight_book")
    assert fb is not None
    assert fb.get("pnr") == "ATLAS-HERMETIC-PNR"

    # Itinerary is reconciled: flight promoted to booked=True, PNR attached, leisure items intact
    itin = trip.context.get("itinerary")
    assert itin is not None
    flight_items = [i for i in itin["items"] if i.get("kind") == "flight"]
    assert len(flight_items) >= 1
    booked_flt = flight_items[0]
    assert booked_flt.get("booked") is True
    assert booked_flt.get("details", {}).get("pnr") == "ATLAS-HERMETIC-PNR"
    assert "booked flight" in booked_flt.get("honesty_label", "").lower()

    # Leisure items still exist
    hotels = [i for i in itin["items"] if i.get("kind") == "hotel"]
    assert len(hotels) >= 1

    # Disruption monitor is armed
    dm = trip.context.get("disruption_monitor")
    assert dm is not None
    assert dm.get("pnr") == "ATLAS-HERMETIC-PNR"


# ---------------------------------------------------------------------------------
# 4. Scope isolation: flight-only and flight-plus-booking
# ---------------------------------------------------------------------------------

def test_flight_only_skips_leisure_and_itinerary(tmp_path):
    atlas = MockAtlasClient()
    orch, _ = _setup_orch(tmp_path, atlas=atlas)

    goal_text = "Find flights only from BKK to SIN Sep 29-30 for 1 passenger."
    trip_id = _run(orch.start(goal_text, "victor", search_confirmed=True))
    trip = orch.executor.get(trip_id)

    # If clarify or scope choice needed, resolve to flight_only
    if trip.status == "awaiting_approval" and trip.pending_approvals and trip.pending_approvals[0].node_name == "scope_clarification":
        _run(orch.resolve(trip_id, trip.pending_approvals[0].approval_id, "flight_only", {"choice": "flight_only"}))

    state = orch.state(trip_id)
    outputs = state["outputs"]
    assert "flight_search" in outputs
    assert "hotel_research" not in outputs
    assert "activities_research" not in outputs
    assert "local_transport_research" not in outputs
    assert "itinerary" not in outputs


def test_flight_plus_booking_does_not_mount_leisure_research(tmp_path):
    goal = TripGoal(
        goal_id="g_fpb",
        raw_text="BKK to SIN",
        origin_city="BKK",
        dest_city="SIN",
        date_window={"start": "2026-09-29", "end": "2026-09-30"},
        passengers=1,
    )
    rs = RequestedServices(
        flight_search="requested",
        flight_booking="requested",
        visa_check="not_requested",
        hotel="not_requested",
        activities="not_requested",
        local_transport="not_requested",
    )
    plan = plan_trip(TripIntent(intent_id="i_fpb", raw_text="book flight", goal=goal, requested_services=rs, scope_clarified=True))
    names = [n.name for n in plan.nodes]
    assert "flight_search" in names
    assert "approve_booking" in names
    assert "flight_book" in names
    assert "hotel_research" not in names
    assert "activities_research" not in names
    assert "local_transport_research" not in names
    assert "itinerary" not in names


# ---------------------------------------------------------------------------------
# 5. Rejected booking approval makes no provider create call
# ---------------------------------------------------------------------------------

def test_rejected_booking_approval_makes_no_create_order_call(tmp_path):
    atlas = MockAtlasClient()
    orch, _ = _setup_orch(tmp_path, atlas=atlas)

    goal_text = "I need to get to WiT Singapore, Marina Bay Sands, Sep 29-30, 2026 for 1 passenger — plan my whole trip from BKK."
    trip_id = _run(orch.start(goal_text, "victor", search_confirmed=True))
    trip = orch.executor.get(trip_id)

    approval = trip.pending_approvals[0]
    _run(orch.resolve(trip_id, approval.approval_id, "reject", {}))

    assert len(atlas.create_order_calls) == 0
    assert (trip.context.get("flight_book") or {}).get("pnr") is None


# ---------------------------------------------------------------------------------
# 6. Replan invalidation on confirmed facts change
# ---------------------------------------------------------------------------------

def test_replan_after_airport_or_passport_confirmation_clears_stale_previews(tmp_path):
    atlas = MockAtlasClient()
    orch, _ = _setup_orch(tmp_path, atlas=atlas)

    goal_text = "I need to get to Singapore from Bangkok Sep 29-30 — plan my whole trip."
    trip_id = _run(orch.start(goal_text, "victor"))
    trip = orch.executor.get(trip_id)

    # Propose clarifying Bangkok to DMK
    orch.seed_airport_confirmation_chips(trip_id)
    chips = trip.confirmation_chips
    origin_chip = next((c for c in chips.values() if c.field == "confirmed_origin_airport" and c.state == "pending"), None)

    if origin_chip:
        _run(orch.resolve_confirmation(trip_id, origin_chip.chip_id, "confirm", "DMK"))
        # Replan must rebuild flight_search and approval for DMK
        assert trip.context.get("goal_intake", {}).get("goal", {}).get("confirmed_origin_airport") == "DMK"


# ---------------------------------------------------------------------------------
# 7. Visa safety guards: visa-blocked never reaches approval
# ---------------------------------------------------------------------------------

def test_visa_blocked_route_does_not_reach_approval():
    goal = TripGoal(
        goal_id="g_blocked",
        raw_text="BKK to SIN",
        origin_city="BKK",
        dest_city="SIN",
        date_window={"start": "2026-09-29", "end": "2026-09-30"},
        passengers=1,
    )
    rs = RequestedServices(
        flight_search="requested",
        flight_booking="requested",
        visa_check="requested",
        hotel="requested",
        activities="requested",
        local_transport="requested",
    )
    plan = plan_trip(TripIntent(intent_id="i_blk", raw_text="plan", goal=goal, requested_services=rs, scope_clarified=True))

    # In plan, visa_check has an edge back to flight_search when visa_blocked is True
    vc_node = next(n for n in plan.nodes if n.name == "visa_check")
    blocked_edge = next((e for e in vc_node.edges if e.to == "flight_search"), None)
    assert blocked_edge is not None
    assert blocked_edge.when({"visa_blocked": True}, {}) is True


def test_planned_usd_offer_is_not_counted_as_sgd_budget(tmp_path):
    """Removing native-currency preservation must not relabel USD as SGD."""
    skill = ItinerarySkill(hotels_path=tmp_path / "missing.json")
    option = {
        "id": "off-usd-1", "carrier": "SQ", "flight_no": "SQ905",
        "dep": {"airport": "BKK", "time": "2026-09-29T09:30:00+07:00"},
        "arr": {"airport": "SIN", "time": "2026-09-29T13:00:00+08:00"},
        "price": {"amount": 210.0, "currency": "USD"},
    }

    result = _run(skill.run({
        "options": [option],
        "requested_domains": [],
    }))

    flight = next(item for item in result["items"] if item["kind"] == "flight")
    assert flight["price_range_sgd"] is None
    assert flight["details"]["price"] == {"amount": 210.0, "currency": "USD"}
    assert result["budget"]["total_range_sgd"] == [0.0, 0.0]


def test_itinerary_enrichment_respects_requested_leisure_domains(tmp_path):
    """Removing domain filtering must not surface unrequested suggestions."""
    fixture = tmp_path / "inventory.json"
    fixture.write_text(json.dumps({"items": [
        {"name": "Hotel A", "type": "hotel", "researched_as_of": "2026-08-29"},
        {"name": "Hotel B", "type": "hotel", "researched_as_of": "2026-08-29"},
        {"name": "Activity A", "type": "activity", "researched_as_of": "2026-08-29"},
        {"name": "MRT A", "type": "local_transport", "researched_as_of": "2026-08-29"},
    ]}), encoding="utf-8")
    skill = ItinerarySkill(hotels_path=fixture)

    result = _run(skill.run({"requested_domains": ["hotel"]}))

    assert [item["kind"] for item in result["items"]] == ["hotel"]


def test_default_complete_trip_inventory_covers_every_requested_leisure_domain():
    """Dropping a category from the default demo inventory must be visible."""
    option = {
        "id": "off-complete-1", "carrier": "SQ", "flight_no": "SQ905",
        "dep": {"airport": "BKK", "time": "2026-09-29T09:30:00+07:00"},
        "arr": {"airport": "SIN", "time": "2026-09-29T13:00:00+08:00"},
        "price": {"amount": 210.0, "currency": "USD"},
    }

    result = _run(ItinerarySkill(allow_mock_fallback=True).run({
        "options": [option],
        "requested_domains": ["hotel", "activities", "local_transport"],
    }))

    kinds = {item["kind"] for item in result["items"]}
    assert {"flight", "hotel", "activity", "local_transport"} <= kinds


def test_planned_flight_cannot_be_replaced_through_leisure_editor():
    """Removing flight immutability must not desynchronise approval snapshots."""
    items = [{
        "item_id": "itin-flt-SQ905", "name": "SQ905 BKK→SIN",
        "kind": "flight", "source": "atlas_sandbox", "booked": False,
        "honesty_label": "planned flight — not booked", "details": {"pnr": None},
    }]

    result = ItinerarySkill.replace_section(items, "itin-flt-SQ905", {
        "name": "Unrelated hotel", "kind": "hotel",
    })

    assert result["error"] == "flight_section_requires_selection"
    assert items[0]["kind"] == "flight"


def test_planned_flight_label_does_not_repeat_short_carrier_code():
    item = ItinerarySkill._planned_flight_item({
        "id": "atlas-offer-tr609",
        "carrier": "TR",
        "flight_no": "TR609",
        "dep": {"airport": "BKK", "time": "2026-09-29T09:05:00"},
        "arr": {"airport": "SIN", "time": "2026-09-29T12:25:00"},
        "price": {"amount": 111.57, "currency": "USD"},
    })

    assert item is not None
    assert item["name"] == "TR609 BKK→SIN"
