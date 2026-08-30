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


# --- Audit fix: server-side approval validation for flight_book -------------

class _FakeTrip:
    def __init__(self, trip_id, context=None, pending_approvals=None):
        self.trip_id = trip_id
        self.context = context or {}
        self.pending_approvals = pending_approvals or []


class _FakeTripStore:
    def __init__(self, trips=None):
        self._trips = {t.trip_id: t for t in (trips or [])}

    def get(self, trip_id):
        return self._trips[trip_id]  # KeyError for unknown trips


class _RecordingBookSkill:
    """Records payload/context; never books."""

    def __init__(self, raise_error=None):
        self.calls = []
        self._raise = raise_error

    async def run(self, payload, context=None):
        self.calls.append((dict(payload), dict(context or {})))
        if self._raise is not None:
            raise self._raise
        return {"pnr": "FAKEPNR", "status": "CONFIRMED", "provenance": "sandbox"}


def test_flight_book_refuses_model_approved_string_without_server_grant():
    # The model claims approval_state="approved" but server-side trip state
    # has no granted approval -> the tool must refuse and never call the skill.
    from services.skills.base import SkillError  # noqa: F401 (import sanity)
    skill = _RecordingBookSkill()
    trip = _FakeTrip("trip_srv_1", context={"goal": {}})
    store = _FakeTripStore([trip])
    tool = FlightBookTool(skill=skill, trip_store=store)
    res = json.loads(tool.call(json.dumps({
        "offer_id": "off_999",
        "trip_id": "trip_srv_1",
        "approval_state": "approved",
    })))
    assert res["status"] == "approval_required"
    assert skill.calls == [], "skill must never run without server-side approval"


def test_flight_book_refuses_unknown_trip():
    skill = _RecordingBookSkill()
    store = _FakeTripStore([])
    tool = FlightBookTool(skill=skill, trip_store=store)
    res = json.loads(tool.call(json.dumps({
        "offer_id": "off_1",
        "trip_id": "trip_missing",
        "approval_state": "approved",
    })))
    assert res["status"] == "approval_required"
    assert skill.calls == []


def test_flight_book_refuses_while_booking_approval_pending_server_side():
    from models.schemas import ApprovalRequest
    skill = _RecordingBookSkill()
    pending = ApprovalRequest(approval_id="trip_srv_2:001",
                              node_name="approve_booking",
                              created_at="2026-08-31T00:00:00Z")
    trip = _FakeTrip("trip_srv_2",
                     context={"approval_granted": True},
                     pending_approvals=[pending])
    store = _FakeTripStore([trip])
    tool = FlightBookTool(skill=skill, trip_store=store)
    res = json.loads(tool.call(json.dumps({
        "offer_id": "off_2",
        "trip_id": "trip_srv_2",
        "approval_state": "approved",
    })))
    assert res["status"] == "approval_required"
    assert skill.calls == []


def test_flight_book_approved_path_maps_offer_and_forwards_real_context():
    skill = _RecordingBookSkill()
    safety_ctx = {"trip_policy_status": "travel_with_caution",
                  "risk_acknowledged": False}
    trip = _FakeTrip("trip_srv_3",
                     context={"approval_granted": True,
                              "safety_check": safety_ctx,
                              "visa_check": {"visa_blocked": False}})
    store = _FakeTripStore([trip])
    tool = FlightBookTool(skill=skill, trip_store=store)
    res = json.loads(tool.call(json.dumps({
        "offer_id": "off_777",
        "trip_id": "trip_srv_3",
        "approval_state": "approved",
        "origin": "BKK",
        "destination": "RGN",
    })))
    assert res.get("status") in ("CONFIRMED", "booked"), res
    assert len(skill.calls) == 1
    payload, context = skill.calls[0]
    assert payload["option_id"] == "off_777", "offer_id must map to option_id"
    assert payload["trip_id"] == "trip_srv_3"
    assert context["approval_granted"] is True
    assert context["safety_check"] == safety_ctx, \
        "real trip safety_check context must be forwarded, never fabricated"
    assert context["visa_check"] == {"visa_blocked": False}


def test_flight_book_propagates_safety_do_not_travel_from_skill():
    from services.skills.base import SkillError
    err = SkillError("safety_do_not_travel",
                     "Booking blocked: an official do-not-travel advisory applies.",
                     recoverable=False)
    skill = _RecordingBookSkill(raise_error=err)
    trip = _FakeTrip("trip_srv_4",
                     context={"approval_granted": True,
                              "safety_check": {"trip_policy_status": "do_not_travel"}})
    store = _FakeTripStore([trip])
    tool = FlightBookTool(skill=skill, trip_store=store)
    res = json.loads(tool.call(json.dumps({
        "offer_id": "off_5",
        "trip_id": "trip_srv_4",
        "approval_state": "approved",
    })))
    assert res["status"] == "failed"
    assert res.get("error_code") == "safety_do_not_travel"


def test_guardian_push_live_send_carries_no_simulated_label(monkeypatch):
    async def fake_notify(title, body):
        return {"sent": True, "simulated": False, "channel": "telegram",
                "preview": f"LIVE: {title}"}
    import services.guardian as guardian_mod
    monkeypatch.setattr(guardian_mod, "notify", fake_notify)
    tool = GuardianPushTool()
    res = json.loads(tool.call(json.dumps({"trip_id": "trip_g_live",
                                           "message_kind": "delay_alert"})))
    assert res["status"] == "sent"
    assert res["label"] == "live_push"
    assert "Simulated" not in res.get("preview", ""), \
        "live pushes must never carry the Simulated preview label"


def test_guardian_push_simulated_preview_is_labeled(monkeypatch):
    async def fake_notify(title, body):
        return {"sent": False, "simulated": True, "channel": "telegram",
                "preview": f"preview: {title}"}
    import services.guardian as guardian_mod
    monkeypatch.setattr(guardian_mod, "notify", fake_notify)
    tool = GuardianPushTool()
    res = json.loads(tool.call(json.dumps({"trip_id": "trip_g_sim",
                                           "message_kind": "delay_alert"})))
    assert res["status"] == "simulated"
    assert res["label"] == "simulated_push"
    assert "Simulated" in res.get("preview", "")


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


def test_profile_edit_tool_declared_user_source():
    tool = ProfileEditTool()
    res = json.loads(tool.call(json.dumps({
        "field": "cabin",
        "value": "ECONOMY",
        "source": "user",
        "user_id": "u_test_2",
    })))
    assert res["status"] in ("updated", "saved", "success")


def test_profile_edit_tool_model_initiated_defaults_ai_inferred_and_is_refused():
    # Audit fix: the tool must pass through the declared source and default to
    # "ai_inferred" when model-initiated. ProfileEditSkill only accepts
    # source="user" (inferred values must go through profile_capture with
    # explicit confirmation), so an undeclared model edit is refused honestly.
    tool = ProfileEditTool()
    res = json.loads(tool.call(json.dumps({
        "field": "cabin",
        "value": "BUSINESS",
        "user_id": "u_test_2",
    })))
    assert res["status"] == "failed"
    assert "invalid_edit_source" in res.get("error_code", "") or \
        "source='user'" in res.get("error", "")


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
