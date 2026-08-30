import json
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from main import app

from services.qwen_brain.tools.flight import FlightSearchTool
from services.qwen_brain.tools.visa import VisaCheckTool
from services.qwen_brain.tools.rights import RightsCheckTool
from services.qwen_brain.tools.safety import SafetyCheckTool


@pytest.mark.anyio
async def test_flight_search_tool_happy_path(monkeypatch):
    from services.atlas_client import AtlasClient
    dummy_offers = [
        {
            "offer_id": "off_test_1",
            "flight_number": "TG401",
            "airline": "Thai Airways",
            "airline_code": "TG",
            "origin": "BKK",
            "destination": "SIN",
            "departure_time": "2026-09-28T08:00:00",
            "arrival_time": "2026-09-28T11:25:00",
            "duration_minutes": 145,
            "stops": 0,
            "via": [],
            "cabin_class": "economy",
            "price_usd": 150.0,
            "seats_available": 5,
        }
    ]
    monkeypatch.setattr(AtlasClient, "search_flights", AsyncMock(return_value=dummy_offers))

    tool = FlightSearchTool()
    res_str = tool.call(json.dumps({"origin": "BKK", "destination": "SIN", "date": "2026-09-28"}))
    data = json.loads(res_str)

    assert data["source"] == "atlas_sandbox"
    assert data["provenance"] == "atlas_sandbox"
    assert data["offer_count"] == 1
    assert len(data["offers"]) == 1
    assert data["offers"][0]["offer_id"] == "off_test_1"


def test_flight_search_tool_resilience():
    tool = FlightSearchTool()
    res_str = tool.call("invalid-json")
    data = json.loads(res_str)
    assert data["status"] == "failed"
    assert "error" in data


def test_visa_check_tool_happy_path():
    tool = VisaCheckTool()
    res_str = tool.call(json.dumps({"passport": "MM", "origin": "BKK", "destination": "SIN"}))
    data = json.loads(res_str)

    assert data["passport"] == "MM"
    assert data["passport_name"] == "Myanmar"
    assert "destination_rule" in data
    assert "route_assessment" in data


def test_visa_check_tool_resilience():
    tool = VisaCheckTool()
    res_str = tool.call("malformed-json")
    data = json.loads(res_str)
    assert data["status"] == "failed"
    assert "error" in data


def test_rights_check_tool_happy_path():
    tool = RightsCheckTool()
    res_str = tool.call(json.dumps({"origin": "FRA", "destination": "JFK"}))
    data = json.loads(res_str)

    assert data["origin_country"] == "DE"
    assert data["destination_country"] == "US"
    assert "EU261" in data["applicable_jurisdictions"]
    assert len(data["entitlements"]) >= 1


def test_rights_check_tool_none_regime():
    tool = RightsCheckTool()
    res_str = tool.call(json.dumps({"origin": "BKK", "destination": "RGN"}))
    data = json.loads(res_str)

    assert data["origin_country"] == "TH"
    assert data["destination_country"] == "MM"
    assert data["applicable_jurisdictions"] == []
    assert "No fixed-cash-compensation regime" in data["note"]


def test_safety_check_tool_happy_path():
    tool = SafetyCheckTool()
    res_str = tool.call(json.dumps({"destination": "SG", "origin": "TH"}))
    data = json.loads(res_str)

    assert "assessment" in data
    assert "overall_status" in data["assessment"]
    assert "provenance_label" in data


def test_safety_check_tool_resilience():
    tool = SafetyCheckTool()
    res_str = tool.call("malformed")
    data = json.loads(res_str)
    assert data["status"] == "failed"
    assert "error" in data


def test_concierge_endpoint_under_both_brains(monkeypatch):
    client = TestClient(app)

    # 1. Legacy brain concierge call
    monkeypatch.setenv("TRAVELCARE_BRAIN", "legacy")
    res_legacy = client.post("/api/chat/concierge", json={
        "query": "Hello concierge, can you help me?",
        "user_id": "concierge_user_1",
    })
    assert res_legacy.status_code == 200
    legacy_data = res_legacy.json()
    assert "reply" in legacy_data
    assert "action_taken" in legacy_data

    # 2. Qwen agent brain concierge call
    monkeypatch.setenv("TRAVELCARE_BRAIN", "qwen_agent")
    res_qwen = client.post("/api/chat/concierge", json={
        "query": "Hello concierge, can you help me?",
        "user_id": "concierge_user_2",
    })
    assert res_qwen.status_code == 200
    qwen_data = res_qwen.json()
    assert "reply" in qwen_data
    assert "action_taken" in qwen_data
