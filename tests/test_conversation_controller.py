"""Tests for Conversation Schema and Pure Conversation Controller (Gate G2)."""

import pytest
from models.schemas import (
    ConversationQuestion,
    ConversationAction,
    ConversationTurn,
)
from services.conversation_controller import project_conversation_turn


def test_conversation_schema_validation():
    q = ConversationQuestion(
        field="origin",
        prompt="Where will you be departing from?",
        input_kind="text",
        choices=[],
        optional=False,
        reason=None,
    )
    assert q.field == "origin"
    assert q.optional is False

    a = ConversationAction(
        action_id="approve_booking",
        label="Approve Sandbox booking",
        kind="primary",
        requires_confirmation=True,
        consequence="Approving requests an Atlas Sandbox booking.",
    )
    assert a.action_id == "approve_booking"

    turn = ConversationTurn(
        phase="booking_approval",
        assistant_message="Your complete plan is ready. Review and approve to proceed.",
        question=None,
        actions=[a],
        requires_user_input=False,
        consequence="Approving requests an Atlas Sandbox booking.",
        provenance_label="Atlas Sandbox",
        recoverable=True,
        error_code=None,
    )
    assert turn.phase == "booking_approval"
    assert len(turn.actions) == 1
    assert turn.question is None


def test_controller_emits_exactly_one_question():
    state = {
        "status": "in_progress",
        "current_state": "clarify_loop",
        "pending_approvals": [],
        "outputs": {
            "clarify": {
                "questions": [
                    {"field": "origin", "prompt": "Where are you departing from?"},
                    {"field": "dates", "prompt": "When are you departing?"},
                    {"field": "passengers", "prompt": "How many passengers?"},
                ],
                "complete": False,
            }
        },
    }
    turn = project_conversation_turn(state)
    assert turn.requires_user_input is True
    assert turn.question is not None
    assert turn.question.field == "origin"


def test_controller_is_pure_and_deterministic():
    state = {
        "status": "in_progress",
        "current_state": "clarify_loop",
        "pending_approvals": [],
        "outputs": {
            "clarify": {
                "questions": [
                    {"field": "destination", "prompt": "Where are you going?"}
                ],
                "complete": False,
            }
        },
    }
    turn1 = project_conversation_turn(state)
    turn2 = project_conversation_turn(state)
    assert turn1.model_dump() == turn2.model_dump()


def test_controller_no_question_while_waiting_for_approval():
    state = {
        "status": "awaiting_approval",
        "current_state": "approve_booking",
        "pending_approvals": [
            {
                "approval_id": "app_123",
                "node_name": "approve_booking",
                "prompt": "Approve flight SQ712",
                "options": [{"id": "opt_1", "price": {"amount": 210.0, "currency": "USD"}}],
            }
        ],
        "outputs": {
            "clarify": {
                "questions": [{"field": "notes", "prompt": "Any extra notes?"}],
            }
        },
    }
    turn = project_conversation_turn(state)
    assert turn.phase == "booking_approval"
    assert turn.question is None
    assert any(a.action_id == "approve" for a in turn.actions)


def test_controller_price_increase_reapproval():
    state = {
        "status": "awaiting_approval",
        "current_state": "approve_booking",
        "pending_approvals": [
            {
                "approval_id": "app_reapp_456",
                "node_name": "approve_booking",
                "is_price_increase": True,
                "old_price": {"amount": 210.0, "currency": "USD"},
                "new_price": {"amount": 245.0, "currency": "USD"},
                "consequence": "Fare changed during verification from $210.00 to $245.00.",
            }
        ],
        "outputs": {},
    }
    turn = project_conversation_turn(state)
    assert turn.phase == "price_reapproval"
    assert "210" in turn.assistant_message and "245" in turn.assistant_message
    assert turn.question is None
    assert any(a.action_id == "approve" for a in turn.actions)


def test_controller_ticketing_unavailable_message():
    state = {
        "status": "failed",
        "current_state": "flight_book",
        "pending_approvals": [],
        "error": {
            "code": "ticketing_activation_required",
            "message": "Atlas Sandbox ticketing is not activated",
            "recoverable": True,
        },
        "outputs": {
            "itinerary": {"items": [{"title": "Flight SQ712"}]},
        },
    }
    turn = project_conversation_turn(state)
    assert turn.phase == "ticketing_unavailable"
    assert "Your plan is safe" in turn.assistant_message
    assert any(a.action_id == "back_to_review" or a.action_id == "review" for a in turn.actions)
    assert turn.recoverable is True


def test_controller_safety_blocker_priority():
    state = {
        "status": "in_progress",
        "current_state": "plan_trip",
        "pending_approvals": [],
        "outputs": {
            "safety": {
                "assessment": {
                    "overall_status": "do_not_travel",
                    "trip_policy_status": "do_not_travel",
                    "why_selected": "Official government advice advises against all travel.",
                }
            }
        },
    }
    turn = project_conversation_turn(state)
    assert turn.phase == "safety_blocked"
    assert "do not travel" in turn.assistant_message.lower() or "safety" in turn.assistant_message.lower()


def test_controller_complete_plan_review():
    state = {
        "status": "in_progress",
        "current_state": "itinerary",
        "pending_approvals": [],
        "outputs": {
            "itinerary": {"items": [{"title": "Flight SQ712"}]},
            "hotel_research": {"hotels": [{"name": "Marina Bay Sands"}]},
            "flight_search": {"options": [{"id": "opt_1"}]},
        },
    }
    turn = project_conversation_turn(state)
    assert turn.phase == "full_plan_review"
    assert any(a.action_id == "continue_to_booking" or a.action_id == "book" for a in turn.actions)


def test_controller_recovery_approval():
    state = {
        "status": "awaiting_approval",
        "current_state": "recovery_approval",
        "pending_approvals": [
            {
                "approval_id": "rec_app_789",
                "node_name": "recovery_approval",
                "prompt": "Approve disruption rescue package",
            }
        ],
        "outputs": {
            "recovery": {"status": "PROPOSED"},
        },
    }
    turn = project_conversation_turn(state)
    assert turn.phase == "recovery_approval"
    assert any(a.action_id == "approve" for a in turn.actions)


def test_controller_passport_country_includes_reason():
    state = {
        "status": "in_progress",
        "current_state": "clarify_loop",
        "pending_approvals": [],
        "outputs": {
            "clarify": {
                "questions": [
                    {
                        "field": "passport_country",
                        "prompt": "Which country issued your passport?",
                    }
                ],
                "complete": False,
            }
        },
    }
    turn = project_conversation_turn(state)
    assert turn.question is not None
    assert turn.question.field == "passport_country"
    assert turn.question.reason == "Needed to check entry and transit requirements."


def test_controller_never_requests_pii_or_payment():
    forbidden_fields = {"passport_number", "passport_expiry", "credit_card", "card_number", "cvv", "ssn"}
    state = {
        "status": "in_progress",
        "current_state": "clarify_loop",
        "pending_approvals": [],
        "outputs": {
            "clarify": {
                "questions": [
                    {"field": "passport_number", "prompt": "Enter passport number"},
                    {"field": "origin", "prompt": "Where from?"},
                ],
                "complete": False,
            }
        },
    }
    turn = project_conversation_turn(state)
    # Must drop forbidden PII field and skip to origin
    assert turn.question is not None
    assert turn.question.field not in forbidden_fields
