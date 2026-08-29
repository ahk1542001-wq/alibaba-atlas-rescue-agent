"""Failing tests for Gate G3: Conditional Clarification Policy."""

import pytest
from models.schemas import RequestedServices, TripGoal
from services.profile_store import ProfileStore
from services.skills.clarify_loop import ClarifyLoopSkill
from services.skills.goal_intake import GoalIntakeSkill, _extract_passengers
from services.conversation_controller import project_conversation_turn


def test_missing_origin_asks_origin_only_in_controller():
    state = {
        "status": "in_progress",
        "current_state": "clarify_loop",
        "pending_approvals": [],
        "outputs": {
            "clarify": {
                "questions": [
                    {"field": "origin_city", "prompt": "Where does your trip start?"},
                    {"field": "dest_city", "prompt": "Where do you want to go?"},
                    {"field": "date_window", "prompt": "Which dates?"},
                ],
                "complete": False,
            }
        },
    }
    turn = project_conversation_turn(state)
    assert turn.question is not None
    assert turn.question.field == "origin_city"


def test_after_origin_confirmed_destination_becomes_next():
    state = {
        "status": "in_progress",
        "current_state": "clarify_loop",
        "pending_approvals": [],
        "outputs": {
            "clarify": {
                "questions": [
                    {"field": "dest_city", "prompt": "Where do you want to go?"},
                    {"field": "date_window", "prompt": "Which dates?"},
                ],
                "complete": False,
            }
        },
    }
    turn = project_conversation_turn(state)
    assert turn.question is not None
    assert turn.question.field == "dest_city"


def test_passenger_count_tracked_explicit_vs_defaulted():
    # Explicit mention
    assert _extract_passengers("Flight for 3 passengers from BKK to SIN") == 3
    # Defaulted mention
    # We should have goal_intake track passengers_explicit: bool
    skill = GoalIntakeSkill(llm_chat=None)
    import asyncio
    out1 = asyncio.run(skill.run({"free_text": "Fly from BKK to SIN on Sep 29"}))
    assert out1["goal"]["passengers_explicit"] is False
    assert out1["goal"]["passengers"] == 1

    out2 = asyncio.run(skill.run({"free_text": "Fly from BKK to SIN on Sep 29 for 2 people"}))
    assert out2["goal"]["passengers_explicit"] is True
    assert out2["goal"]["passengers"] == 2


def test_passenger_count_tracked_in_conversation_controller():
    # If clarify has passengers question, controller asks it
    state = {
        "status": "in_progress",
        "current_state": "clarify_loop",
        "pending_approvals": [],
        "outputs": {
            "clarify": {
                "questions": [
                    {"field": "passengers", "prompt": "How many passengers are traveling?"}
                ],
                "complete": False,
            }
        },
    }
    turn = project_conversation_turn(state)
    assert turn.question is not None
    assert turn.question.field == "passengers"
    assert turn.question.input_kind == "number"


def test_passport_country_reason_in_conversation_controller():
    state = {
        "status": "in_progress",
        "current_state": "clarify_loop",
        "pending_approvals": [],
        "outputs": {
            "clarify": {
                "questions": [
                    {"field": "passport_country", "prompt": "Which country issued your passport?"}
                ],
                "complete": False,
            }
        },
    }
    turn = project_conversation_turn(state)
    assert turn.question is not None
    assert turn.question.field == "passport_country"
    assert "entry and transit" in turn.question.reason


def test_clarify_loop_asks_passengers_when_not_explicit(tmp_path):
    store = ProfileStore(root=tmp_path)
    skill = ClarifyLoopSkill(profile_store=store)
    goal = TripGoal(
        goal_id="g1", raw_text="BKK to SIN on Sep 29", origin_city="BKK", dest_city="SIN",
        date_window={"start": "2026-09-29", "end": "2026-09-29"},
        passengers=1,
        passengers_explicit=False,
    ).model_dump(mode="json")
    rs = RequestedServices().model_dump()
    import asyncio
    out = asyncio.run(skill.run({"goal": goal, "user_id": "victor", "requested_services": rs}))
    fields = [q["field"] for q in out["questions"]]
    assert "passengers" in fields


def test_clarify_loop_does_not_ask_passport_for_flight_only(tmp_path):
    store = ProfileStore(root=tmp_path)
    skill = ClarifyLoopSkill(profile_store=store)
    goal = TripGoal(
        goal_id="g1", raw_text="Find flights from BKK to SIN", origin_city="BKK", dest_city="SIN",
        date_window={"start": "2026-09-29", "end": "2026-09-29"},
        passengers=1,
        passengers_explicit=True,
    ).model_dump(mode="json")
    # Scope: flight-only
    rs = RequestedServices(flight_search="requested", flight_booking="not_requested",
                           visa_check="not_requested", hotel="not_requested",
                           activities="not_requested", local_transport="not_requested").model_dump()
    import asyncio
    out = asyncio.run(skill.run({"goal": goal, "user_id": "victor", "requested_services": rs}))
    fields = [q["field"] for q in out["questions"]]
    assert "passport_country" not in fields


def test_clarify_loop_does_not_ask_home_city_when_origin_known(tmp_path):
    store = ProfileStore(root=tmp_path)
    skill = ClarifyLoopSkill(profile_store=store)
    goal = TripGoal(
        goal_id="g1", raw_text="BKK to SIN", origin_city="BKK", dest_city="SIN",
        date_window={"start": "2026-09-29", "end": "2026-09-29"},
        passengers=1,
        passengers_explicit=True,
    ).model_dump(mode="json")
    rs = RequestedServices().model_dump()
    import asyncio
    out = asyncio.run(skill.run({"goal": goal, "user_id": "victor", "requested_services": rs}))
    fields = [q["field"] for q in out["questions"]]
    assert "home_city" not in fields


def test_clarify_loop_asks_empty_profile_identity(tmp_path):
    store = ProfileStore(root=tmp_path)
    skill = ClarifyLoopSkill(profile_store=store)
    goal = TripGoal(
        goal_id="g1", raw_text="BKK to SIN", origin_city="BKK", dest_city="SIN",
        date_window={"start": "2026-09-28", "end": "2026-09-30"},
        passengers=1,
        passengers_explicit=True,
    ).model_dump(mode="json")
    rs = RequestedServices(flight_search="requested", flight_booking="requested",
                           visa_check="requested", hotel="requested",
                           activities="requested", local_transport="requested").model_dump()
    import asyncio
    out = asyncio.run(skill.run({"goal": goal, "user_id": "victor", "requested_services": rs}))
    fields = [q["field"] for q in out["questions"]]
    assert "passport_country" in fields


def test_explicit_complete_trip_does_not_ask_redundant_scope(tmp_path):
    store = ProfileStore(root=tmp_path)
    skill = ClarifyLoopSkill(profile_store=store)
    goal = TripGoal(
        goal_id="g1", raw_text="Plan my complete trip BKK to SIN", origin_city="BKK", dest_city="SIN",
        date_window={"start": "2026-09-28", "end": "2026-09-30"},
        passengers=1,
        passengers_explicit=True,
    ).model_dump(mode="json")
    rs = RequestedServices(flight_search="requested", flight_booking="requested",
                           visa_check="requested", hotel="requested",
                           activities="requested", local_transport="requested").model_dump()
    import asyncio
    out = asyncio.run(skill.run({"goal": goal, "user_id": "victor", "requested_services": rs}))
    assert out["scope_clarification"] is None


def test_ambiguous_request_uses_exactly_three_scope_choices(tmp_path):
    store = ProfileStore(root=tmp_path)
    skill = ClarifyLoopSkill(profile_store=store)
    goal = TripGoal(
        goal_id="g1", raw_text="BKK to SIN", origin_city="BKK", dest_city="SIN",
        date_window={"start": "2026-09-28", "end": "2026-09-30"},
        passengers=1,
        passengers_explicit=True,
    ).model_dump(mode="json")
    rs = RequestedServices().model_dump()
    import asyncio
    out = asyncio.run(skill.run({"goal": goal, "user_id": "victor", "requested_services": rs}))
    assert out["scope_clarification"] is not None
    assert out["scope_clarification"]["choices"] == ["flight_only", "flight_plus_booking", "complete_trip"]
