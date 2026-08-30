import pytest
import asyncio
from typing import Dict, Any, List, Optional
from models.schemas import RequestedServices, TripGoal, TripIntent, ConversationTurn
from services.conversation_controller import project_conversation_turn
from services.skills.itinerary import ItinerarySkill
from services.skills.clarify_loop import ClarifyLoopSkill
from services.skills.goal_intake import GoalIntakeSkill
from services.profile_store import ProfileStore
from routers.v1.trip import get_trip_orchestrator, TripOrchestrator


def _run(coro):
    return asyncio.run(coro)


def test_complete_trip_with_missing_route_stays_in_clarification():
    """A complete-trip request with missing route facts must stay in normal
    clarification without failing on flight_search."""
    orch = TripOrchestrator()
    trip_id = _run(orch.start("Plan my complete trip to Singapore.", "user_p1"))
    state = orch.state(trip_id)

    # Must stay in clarification / intake, never fail with missing_route error
    assert state["status"] in ("clarification", "awaiting_approval", "in_progress", "clarifying")
    assert state.get("error") is None or state["error"].get("code") != "missing_route"
    
    # Zero provider search calls before route/facts are confirmed
    nodes = state.get("nodes") or []
    executed_names = [n["name"] for n in nodes if n.get("status") in ("COMPLETED", "FAILED")]
    assert "flight_search" not in executed_names
    assert "hotel_research" not in executed_names
    assert "itinerary" not in executed_names
    assert "approve_booking" not in executed_names


def test_no_provider_calls_before_readiness():
    """Before readiness is satisfied, provider calls must be zero."""
    orch = TripOrchestrator()
    trip_id = _run(orch.start("Fly from Bangkok to Singapore.", "user_p2"))
    state = orch.state(trip_id)

    # Date and passengers are missing -> readiness false -> 0 provider calls
    nodes = state.get("nodes") or []
    executed = [n["name"] for n in nodes if n.get("status") in ("COMPLETED", "RUNNING")]
    assert "flight_search" not in executed
    assert "visa_check" not in executed


def test_confirming_route_and_dates_insufficient_when_passengers_or_passport_required():
    """Confirming origin, dest, dates is not enough if passenger count or passport country is still needed."""
    orch = TripOrchestrator()
    trip_id = _run(orch.start("I need a complete trip from Bangkok to Singapore on Sep 29-30.", "user_p3"))
    state = orch.state(trip_id)
    
    # Missing passengers / passport for complete trip -> must not run search yet
    nodes = state.get("nodes") or []
    executed = [n["name"] for n in nodes if n.get("status") in ("COMPLETED", "RUNNING")]
    assert "flight_search" not in executed
    assert "hotel_research" not in executed


def test_flight_only_does_not_request_passport_unnecessarily(tmp_path):
    """Flight-only search must not ask for passport country."""
    store = ProfileStore(root=tmp_path)
    skill = ClarifyLoopSkill(store)
    rs = RequestedServices(
        flight_search="requested",
        flight_booking="not_requested",
        visa_check="not_requested",
        hotel="not_requested",
        activities="not_requested",
        local_transport="not_requested",
    )
    goal = {"origin_city": "BKK", "dest_city": "SIN", "date_window": {"start": "2026-09-29", "end": "2026-09-30"}, "passengers": 1, "passengers_explicit": True}
    out = _run(skill.run({"goal": goal, "user_id": "u_flight_only", "requested_services": rs.model_dump()}))
    q_fields = [q["field"] for q in (out.get("questions") or [])]
    assert "passport_country" not in q_fields


def test_booking_or_visa_scope_requires_passport_country(tmp_path):
    """International booking or complete trip scope requires passport country."""
    store = ProfileStore(root=tmp_path)
    skill = ClarifyLoopSkill(store)
    rs = RequestedServices(
        flight_search="requested",
        flight_booking="requested",
        visa_check="requested",
        hotel="requested",
        activities="requested",
        local_transport="requested",
    )
    goal = {"origin_city": "BKK", "dest_city": "SIN", "date_window": {"start": "2026-09-29", "end": "2026-09-30"}, "passengers": 1, "passengers_explicit": True}
    out = _run(skill.run({"goal": goal, "user_id": "u_intl_booking", "requested_services": rs.model_dump()}))
    q_fields = [q["field"] for q in (out.get("questions") or [])]
    assert "passport_country" in q_fields


def test_no_booking_approval_while_any_blocking_fact_unresolved():
    """No booking approval may exist while any required fact or confirmation is pending."""
    orch = TripOrchestrator()
    trip_id = _run(orch.start("Plan my complete trip from Bangkok to Singapore.", "user_p4"))
    state = orch.state(trip_id)
    approvals = state.get("pending_approvals") or []
    booking_approvals = [a for a in approvals if a.get("node_name") in ("approve_booking", "flight_book")]
    assert len(booking_approvals) == 0


def test_normal_missing_info_never_creates_red_provider_error():
    """A missing route/fact during clarification must not create a provider error."""
    orch = TripOrchestrator()
    trip_id = _run(orch.start("I want to travel somewhere nice.", "user_p5"))
    state = orch.state(trip_id)
    assert state["status"] != "failed"
    assert state.get("error") is None


def test_conversation_controller_emits_clarification_before_downstream_status():
    """Conversation controller must prioritize unanswered clarification questions before booking approval or downstream reviews."""
    synthetic_state = {
        "status": "awaiting_approval",
        "pending_approvals": [{"approval_id": "app_123", "node_name": "approve_booking", "purpose": "initial_booking"}],
        "outputs": {
            "clarify": {
                "questions": [{"field": "passengers", "prompt": "How many passengers are traveling?"}],
                "complete": False,
            }
        },
        "error": None,
    }
    turn = project_conversation_turn(synthetic_state)
    assert turn.phase == "clarification"
    assert turn.question is not None
    assert turn.question.field == "passengers"


def test_runtime_leisure_research_never_returns_researched_mock():
    """Runtime leisure research must not fall back to researched_mock."""
    skill = ItinerarySkill()
    providers_tried = []
    # Running enrich with no live providers configured
    out = _run(skill._enrich(providers_tried, requested_domains=["hotel", "activities"]))
    assert "researched_mock" not in providers_tried
    for item in out:
        assert item.get("source") != "researched_mock"


def test_concierge_shares_active_trip_state():
    """Concierge endpoint must read the active trip when one exists for that user."""
    from routers.v1.concierge import chat_concierge
    from models.schemas import ConciergeQuery
    orch = get_trip_orchestrator()
    trip_id = _run(orch.start("I need to fly from Bangkok to Singapore on 2026-09-29 for 1 person.", "victor"))
    req = ConciergeQuery(query="What is my destination?", trip_id=trip_id, user_id="victor")
    resp = _run(chat_concierge(req))
    import json
    data = json.loads(resp.body)
    assert "Singapore" in data.get("reply", "") or data.get("trip_id") == trip_id


def test_concierge_without_trip_or_user_id_returns_no_active_session():
    """Concierge without trip_id/user_id must return a calm no-active-trip response without exposing any trip context."""
    from routers.v1.concierge import chat_concierge
    from models.schemas import ConciergeQuery
    orch = get_trip_orchestrator()
    # Populate a trip belonging to someone else
    _run(orch.start("I need to fly from Bangkok to Singapore on 2026-09-29 for 1 person.", "alice"))
    
    # Query with no trip_id or user_id
    req = ConciergeQuery(query="What is my destination?")
    resp = _run(chat_concierge(req))
    import json
    data = json.loads(resp.body)
    assert data.get("action_taken") == "NO_ACTIVE_SESSION"
    assert "Singapore" not in data.get("reply", "")
    assert data.get("trip_id") is None


def test_concierge_rejects_foreign_user_trip():
    """A trip_id belonging to User A must not be accessible to User B in Concierge."""
    from routers.v1.concierge import chat_concierge
    from models.schemas import ConciergeQuery
    orch = get_trip_orchestrator()
    trip_id = _run(orch.start("Fly from Bangkok to Singapore on 2026-09-29 for 1 person.", "alice"))
    
    req = ConciergeQuery(query="What is my destination?", trip_id=trip_id, user_id="bob")
    resp = _run(chat_concierge(req))
    import json
    data = json.loads(resp.body)
    assert data.get("action_taken") == "NO_ACTIVE_SESSION"
    assert "Singapore" not in data.get("reply", "")


def test_rescue_engine_missing_pnr_never_claims_confirmed():
    """Booking context without confirmed PNR must describe pending/unconfirmed status and never fabricate CONFIRMED."""
    from services.rescue_engine import _build_concierge_prompt, RescueEngine
    from services.atlas_client import AtlasClient

    engine = RescueEngine(AtlasClient())
    context_no_pnr = {
        "flight_book": {
            "booking": {"status": "PENDING"}
        }
    }
    prompt = _build_concierge_prompt(context_no_pnr)
    assert "Confirmed Sandbox Booking PNR: CONFIRMED" not in prompt
    assert "no confirmed PNR" in prompt

    rule_resp = _run(engine._rule_based_concierge("is my flight booked?", context=context_no_pnr))
    assert "not confirmed" in rule_resp["reply"]
    assert rule_resp["action_taken"] == "BOOKING_STATUS_UNCONFIRMED"


def test_complete_facts_without_search_confirmation_makes_zero_provider_calls():
    """A trip with all facts provided but without explicit search confirmation must not run search providers."""
    orch = TripOrchestrator()
    trip_id = _run(orch.start("Fly from Bangkok to Singapore on 2026-09-29 for 1 passenger, flights only.", "charlie"))
    state = orch.state(trip_id)
    
    # Must be paused before search execution with search confirmation required
    readiness = state.get("readiness") or {}
    assert readiness.get("ready_for_search") is True
    assert readiness.get("requires_search_confirmation") is True
    
    nodes = state.get("nodes") or []
    executed = [n["name"] for n in nodes if n.get("status") in ("COMPLETED", "RUNNING")]
    assert "flight_search" not in executed


def test_trips_plan_endpoint_blocked_before_readiness_and_search_confirmation():
    """POST /api/trips/{trip_id}/plan must not execute providers if facts are missing."""
    from routers.v1.trip import trips_plan
    orch = get_trip_orchestrator()
    trip_id = _run(orch.start("I want to go to Tokyo.", "dave"))
    
    resp = _run(trips_plan(trip_id))
    import json
    data = json.loads(resp.body)
    assert data["status"] in ("clarifying", "in_progress", "awaiting_approval")
    
    state = orch.state(trip_id)
    nodes = state.get("nodes") or []
    executed = [n["name"] for n in nodes if n.get("status") in ("COMPLETED", "RUNNING")]
    assert "flight_search" not in executed


def test_flight_only_missing_passengers_stays_in_clarification(tmp_path):
    """Flight-only goal without passenger count must ask for passengers and not silently assume 1."""
    store = ProfileStore(root=tmp_path)
    skill = ClarifyLoopSkill(store)
    rs = RequestedServices(
        flight_search="requested",
        flight_booking="not_requested",
        visa_check="not_requested",
        hotel="not_requested",
        activities="not_requested",
        local_transport="not_requested",
    )
    goal = {"origin_city": "BKK", "dest_city": "SIN", "date_window": {"start": "2026-09-29", "end": "2026-09-30"}}
    out = _run(skill.run({"goal": goal, "user_id": "u_flight_nopax", "requested_services": rs.model_dump()}))
    q_fields = [q["field"] for q in (out.get("questions") or [])]
    assert "passengers" in q_fields


def test_chat_passenger_change_proposal_updates_and_requires_new_search_confirmation():
    """Chatting a passenger count change creates a structured proposal; confirming it invalidates previous search and requires new search confirmation."""
    from routers.v1.concierge import chat_concierge
    from models.schemas import ConciergeQuery
    orch = get_trip_orchestrator()
    trip_id = _run(orch.start("Fly from Bangkok to Singapore on 2026-09-29 for 1 passenger, flights only.", "eve"))
    
    # 1. Ask in concierge to change passenger count
    req = ConciergeQuery(query="We are two passengers traveling together", trip_id=trip_id, user_id="eve")
    resp = _run(chat_concierge(req))
    import json
    data = json.loads(resp.body)
    assert data.get("action_taken") == "PASSENGER_COUNT_PROPOSAL"
    proposal = data.get("proposal") or {}
    assert proposal.get("proposed_value") == 2
    chips = proposal.get("confirmation_chips") or []
    pax_chip = next((c for c in chips if c.get("field") == "passengers"), None)
    assert pax_chip is not None
    
    # 2. Confirm the passenger confirmation chip
    chip_id = pax_chip["chip_id"]
    conf_res = _run(orch.resolve_confirmation(trip_id, chip_id, "confirm"))
    assert conf_res["status"] == "confirmed"
    
    # 3. Verify passenger count in goal is updated and search is reset
    state = orch.state(trip_id)
    goal = (orch._seeds.get(trip_id) or {}).get("goal") or {}
    assert goal.get("passengers") == 2
    assert goal.get("search_confirmed") is False
    assert state["readiness"]["requires_search_confirmation"] is True


def test_radar_status_badge_unknown_never_shows_on_time():
    """Radar UI code in static/app.js must not pair UNKNOWN flight status with On Time badge."""
    with open("static/app.js", "r", encoding="utf-8") as f:
        content = f.read()
    
    # Ensure rawStatus check exists and non ON_TIME/SCHEDULED/ACTIVE statuses do not render 'On Time'
    assert "ON_TIME" in content
    assert "MONITORING" in content
    # Flag logic must check for explicit on time / scheduled states
    assert "rawStatus === 'ON_TIME' || rawStatus === 'SCHEDULED'" in content


def test_frontend_concierge_sends_trip_id_and_user_id():
    """static/app.js concierge fetch must pass trip_id and user_id."""
    with open("static/app.js", "r", encoding="utf-8") as f:
        content = f.read()
    assert "payload.trip_id = tripId;" in content
    assert "payload.user_id = userId;" in content


