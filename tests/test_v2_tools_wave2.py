import json
import pytest
from unittest.mock import patch, AsyncMock

from services.qwen_brain.agent import ALL_V2_TOOLS, build_travelcare_agent
from services.qwen_brain.tools.wave2 import (
    LocationResolveTool,
    ItineraryTool,
    FlightBookTool,
    RecoveryPlanTool,
    DisruptionMonitorTool,
    GuardianPushTool,
    ProfileCaptureTool,
    ProfileEditTool,
    WebIntelTool,
    RadarScanTool,
    ResearchBriefTool,
)


def test_all_13_skills_registered():
    expected_skills = [
        "goal_intake",
        "clarify_loop",
        "flight_search",
        "visa_check",
        "rights_check",
        "safety_check",
        "location_resolve",
        "itinerary",
        "flight_book",
        "recovery_plan",
        "disruption_monitor",
        "guardian_push",
        "profile_capture",
        "profile_edit",
        "web_intel",
        "radar_scan",
        "research_brief",
    ]
    for skill in expected_skills:
        assert skill in ALL_V2_TOOLS, f"Skill {skill} missing from ALL_V2_TOOLS"


def test_location_resolve_tool_ambiguous():
    tool = LocationResolveTool()
    res = json.loads(tool.call(json.dumps({"text": "Bangkok"})))
    assert res["ambiguous"] is True
    assert res["confirmation_required"] is True
    assert len(res["candidates"]) == 2
    codes = [c["iata"] for c in res["candidates"]]
    assert "BKK" in codes and "DMK" in codes


def test_location_resolve_tool_unambiguous():
    tool = LocationResolveTool()
    res = json.loads(tool.call(json.dumps({"text": "Singapore"})))
    assert res["ambiguous"] is False
    assert len(res["candidates"]) == 1
    assert res["candidates"][0]["iata"] == "SIN"


def test_itinerary_tool_generation():
    tool = ItineraryTool()
    res = json.loads(tool.call(json.dumps({"trip_goal": {"dest_city": "SIN"}})))
    assert "sections" in res
    assert "provenance_per_section" in res


def test_flight_book_tool_refuses_without_approval():
    tool = FlightBookTool()
    # No approval given
    res = json.loads(tool.call(json.dumps({
        "offer_id": "off_123",
        "trip_id": "trip_test",
        "approval_state": "pending",
    })))
    assert res["status"] == "approval_required"
    assert "refused" in res.get("reason", "").lower() or "approval" in res.get("reason", "").lower()


def test_recovery_plan_tool_generation():
    tool = RecoveryPlanTool()
    res = json.loads(tool.call(json.dumps({"trip_id": "trip_test_rec"})))
    assert res["never_booked_without_approval"] is True
    assert "alternatives" in res
    assert "approval_request" in res


def test_disruption_monitor_tool():
    tool = DisruptionMonitorTool()
    res = json.loads(tool.call(json.dumps({"trip_id": "trip_rec_1"})))
    assert "pnr" in res
    assert "status" in res


def test_guardian_push_tool_simulated_when_no_token():
    tool = GuardianPushTool()
    res = json.loads(tool.call(json.dumps({"trip_id": "trip_g", "message_kind": "delay_alert"})))
    assert res["status"] in ("simulated", "skipped", "sent")
    assert "label" in res


def test_profile_capture_tool_confirmed_and_unconfirmed():
    tool = ProfileCaptureTool()
    # Unconfirmed -> confirmation_required
    res_unconfirmed = json.loads(tool.call(json.dumps({
        "field": "passport_country",
        "value": "MM",
        "source": "ai_inferred",
        "confirmed": False,
        "user_id": "u_test_1",
    })))
    assert res_unconfirmed["status"] == "confirmation_required"

    # Confirmed -> saved
    res_confirmed = json.loads(tool.call(json.dumps({
        "field": "passport_country",
        "value": "MM",
        "source": "user",
        "confirmed": True,
        "user_id": "u_test_1",
    })))
    assert res_confirmed["status"] == "saved"
    assert res_confirmed["stored_field"] == "passport_country"


def test_profile_edit_tool():
    tool = ProfileEditTool()
    res = json.loads(tool.call(json.dumps({
        "field": "cabin",
        "value": "ECONOMY",
        "user_id": "u_test_2",
    })))
    assert res["status"] in ("updated", "saved", "success")


def test_web_intel_tool():
    tool = WebIntelTool()
    res = json.loads(tool.call(json.dumps({"query": "visa requirements Singapore"})))
    assert "findings" in res
    assert "citations" in res
    assert "degraded" in res


def test_radar_scan_tool():
    tool = RadarScanTool()
    res = json.loads(tool.call(json.dumps({})))
    assert res["engine"] == "deterministic_radar"
    assert "scans" in res


def test_research_brief_tool():
    tool = ResearchBriefTool()
    res = json.loads(tool.call(json.dumps({"trip_goal": {"dest_city": "SIN"}})))
    assert "brief" in res
    assert "provenance" in res
