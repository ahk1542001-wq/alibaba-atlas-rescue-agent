"""Tests for Gate G7: API Integration of ConversationTurn in /api/trip/{id}/state."""

import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_api_trip_state_includes_conversation_turn(client):
    # Create trip
    payload = {
        "goal_text": "Plan a complete trip from BKK to SIN on 2026-09-28 to 2026-09-30 for 1 person with budget 500 USD",
        "user_id": "test_user_g7",
    }
    resp = client.post("/api/trip/start", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    trip_id = data["trip_id"]

    # Fetch state
    state_resp = client.get(f"/api/trip/{trip_id}/state")
    assert state_resp.status_code == 200
    state = state_resp.json()

    # Verify conversation object exists and is valid
    assert "conversation" in state
    conv = state["conversation"]
    assert "phase" in conv
    assert "assistant_message" in conv
    assert "actions" in conv

    # Verify backward compatibility
    assert "outputs" in state
    assert "nodes" in state
    assert "pending_approvals" in state
    assert "confirmation_chips" in state or "missing_fields" in state

