import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from main import app
from models.schemas import ConversationTurn, TripGoal, RequestedServices
from services.qwen_brain.agent import build_travelcare_agent
from services.qwen_brain.tools.conversation import GoalIntakeTool, ClarifyLoopTool


def test_build_travelcare_agent_returns_none_when_no_provider(monkeypatch):
    from services import llm_providers
    monkeypatch.setattr(llm_providers, "resolve_llm_cfg", lambda: None)
    agent = build_travelcare_agent()
    assert agent is None


def test_build_travelcare_agent_creates_assistant_when_provider_available(monkeypatch):
    from services import llm_providers
    dummy_cfg = {
        "model": "qwen/qwen3-235b-a22b-2507",
        "model_server": "https://openrouter.ai/api/v1",
        "api_key": "test_key",
        "generate_cfg": {"fncall_prompt_type": "nous", "extra_body": {"enable_thinking": False}},
    }
    monkeypatch.setattr(llm_providers, "resolve_llm_cfg", lambda: dummy_cfg)
    agent = build_travelcare_agent()
    assert agent is not None


def test_goal_intake_tool_structured_extraction():
    tool = GoalIntakeTool()
    res_str = tool.call(json.dumps({"free_text": "Fly from Bangkok to Yangon on 2026-09-28 to 2026-09-30"}))
    data = json.loads(res_str)
    assert data["status"] == "success"
    goal = data["goal"]
    assert goal["origin_city"] == "BKK"
    assert goal["dest_city"] == "RGN"
    assert goal["date_window"]["start"] == "2026-09-28"
    assert goal["date_window"]["end"] == "2026-09-30"


def test_goal_intake_tool_resilience_on_invalid_json():
    tool = GoalIntakeTool()
    res_str = tool.call("invalid-json{}}")
    data = json.loads(res_str)
    assert data["status"] == "failed"
    assert "error" in data


def test_clarify_loop_tool_generates_missing_questions():
    tool = ClarifyLoopTool()
    goal = {"origin_city": "BKK", "dest_city": None, "date_window": None}
    res_str = tool.call(json.dumps({"goal": goal, "user_id": "test_user_1", "requested_services": {}}))
    data = json.loads(res_str)
    assert data["status"] == "success"
    questions = data["clarify"]["questions"]
    fields = [q["field"] for q in questions]
    assert "dest_city" in fields
    assert "date_window" in fields


def test_clarify_loop_tool_resilience_on_invalid_json():
    tool = ClarifyLoopTool()
    res_str = tool.call("malformed-json{{")
    data = json.loads(res_str)
    assert data["status"] == "failed"
    assert "error" in data


def test_trip_start_parity_between_legacy_and_qwen_brain(monkeypatch):
    client = TestClient(app)
    
    # 1. Start trip with legacy brain
    monkeypatch.setenv("TRAVELCARE_BRAIN", "legacy")
    res_legacy = client.post("/api/trip/start", json={
        "goal_text": "Fly from BKK to RGN on 2026-09-28 to 2026-09-30",
        "user_id": "parity_tester_legacy",
    })
    assert res_legacy.status_code == 200
    legacy_data = res_legacy.json()
    legacy_trip_id = legacy_data["trip_id"]
    
    state_legacy = client.get(f"/api/trip/{legacy_trip_id}/state").json()
    
    # 2. Start trip with qwen_agent brain
    monkeypatch.setenv("TRAVELCARE_BRAIN", "qwen_agent")
    res_qwen = client.post("/api/trip/start", json={
        "goal_text": "Fly from BKK to RGN on 2026-09-28 to 2026-09-30",
        "user_id": "parity_tester_qwen",
    })
    assert res_qwen.status_code == 200
    qwen_data = res_qwen.json()
    qwen_trip_id = qwen_data["trip_id"]
    
    state_qwen = client.get(f"/api/trip/{qwen_trip_id}/state").json()
    
    # Parity assertions: both derive identical status, current_state, and conversation phase
    assert state_legacy["status"] == state_qwen["status"]
    assert state_legacy["conversation"]["phase"] == state_qwen["conversation"]["phase"]
    assert state_legacy["readiness"]["ready_for_search"] == state_qwen["readiness"]["ready_for_search"]
