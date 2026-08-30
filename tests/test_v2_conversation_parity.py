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
    # §13.3/§8 (audit finding #5): the qwen path emits at most ONE next
    # question, chosen by QUESTION_FIELD_ORDER — dest_city precedes
    # date_window, so exactly one question for dest_city is expected.
    tool = ClarifyLoopTool()
    goal = {"origin_city": "BKK", "dest_city": None, "date_window": None}
    res_str = tool.call(json.dumps({"goal": goal, "user_id": "test_user_1", "requested_services": {}}))
    data = json.loads(res_str)
    assert data["status"] == "success"
    questions = data["clarify"]["questions"]
    assert [q["field"] for q in questions] == ["dest_city"]


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


# ============================================================================
# §8.4 full parity matrix (audit finding #4) — hermetic, mocked LLM.
# For every scripted goal: legacy path vs qwen-tool path must produce the
# SAME TripGoal fields, the SAME missing_fields set, the SAME single next
# question (per QUESTION_FIELD_ORDER), and never a FORBIDDEN_PII_FIELDS
# question. Malformed LLM output must fall back to the deterministic path,
# labeled degraded, never fabricated.
# ============================================================================

import asyncio

from services import llm as llm_service
from services.conversation_controller import FORBIDDEN_PII_FIELDS
from services.profile_store import ProfileStore
from services.qwen_brain.tools.conversation import _single_next_question
from services.skills.clarify_loop import ClarifyLoopSkill
from services.skills.goal_intake import GoalIntakeSkill

_GOAL_KEYS = None  # resolved lazily from TripGoal


def _goal_compare_fields():
    global _GOAL_KEYS
    if _GOAL_KEYS is None:
        _GOAL_KEYS = sorted(
            k for k in TripGoal.model_fields
            if k not in ("goal_id", "raw_text", "missing_fields"))
    return _GOAL_KEYS


def _goal_view(goal: dict) -> dict:
    return {k: goal.get(k) for k in _goal_compare_fields()}


async def _raise_chat(*args, **kwargs):
    raise RuntimeError("LLM unavailable in hermetic parity suite")


async def _garbage_chat(*args, **kwargs):
    return "NOT-JSON {{{{ definitely not structured output"


def _run_sync(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


PARITY_GOALS = [
    # (id, text, extra per-case assertions are inline below)
    ("complete_goal",
     "Fly from Bangkok to Yangon on 2026-09-28 to 2026-09-30 for 2 passengers"),
    ("missing_destination", "Fly from Bangkok in late September"),
    ("missing_dates", "Fly from Bangkok to Yangon"),
    ("multi_airport_origin", "Bangkok to Yangon on 2026-09-28 to 2026-09-30"),
    ("missing_passport", "Fly from Bangkok to Yangon on 2026-09-28 to 2026-09-30"),
    ("venue_instead_of_city",
     "I want to see Marina Bay Sands in late September"),
    ("non_english", "\u1019\u103c\u1014\u103a\u1019\u102c\u1010\u103d\u1004\u103a"
     "\u1000\u102d\u102f \u101e\u103d\u102c\u1038\u1015\u103c\u102f\u1015\u1032\u1019\u103b\u102c\u1038"),
    ("rambling_over_detailed",
     "So my cousin said we should totally go, and honestly after thinking "
     "about it a lot, maybe Bangkok, actually definitely Bangkok, flying to "
     "Yangon, dates are 2026-09-28 to 2026-09-30, two of us, aisle seats if "
     "possible, and we love street food"),
    ("contradicts_profile", "Fly from Yangon to Bangkok on 2026-10-01 to 2026-10-05"),
    ("empty_input", ""),
    ("garbage_input", "zzz @@@ 12345 !?"),
    ("missing_origin", "Get me to Yangon on 2026-09-28 to 2026-09-30"),
]


@pytest.mark.parametrize("case_id, text", PARITY_GOALS)
def test_parity_matrix_goal_intake_and_clarify(tmp_path, monkeypatch, case_id, text):
    monkeypatch.setattr(llm_service, "chat", _raise_chat)

    legacy_intake = GoalIntakeSkill(llm_chat=_raise_chat)
    qwen_intake = GoalIntakeTool(skill=GoalIntakeSkill(llm_chat=_raise_chat))

    # --- intake parity ------------------------------------------------------
    legacy_out = _run_sync(legacy_intake.run({"free_text": text}, None))
    qwen_res = json.loads(qwen_intake.call(json.dumps({"text": text})))
    assert qwen_res["status"] == "success"

    legacy_goal = legacy_out["goal"]
    qwen_goal = qwen_res["trip_goal"]
    assert _goal_view(legacy_goal) == _goal_view(qwen_goal), \
        f"[{case_id}] TripGoal fields differ between paths"
    assert legacy_out.get("requested_services") == qwen_res.get("requested_services"), \
        f"[{case_id}] requested_services differ between paths"

    # missing_fields parity: qwen tool's missing_fields must equal the set
    # derived from the legacy goal view.
    qwen_missing = set(qwen_res["missing_fields"])
    derived = set()
    if not qwen_goal.get("origin_city"):
        derived.add("origin_city")
    if not qwen_goal.get("dest_city"):
        derived.add("dest_city")
    if not qwen_goal.get("date_window"):
        derived.add("date_window")
    if not (qwen_goal.get("passengers_explicit")
            or qwen_goal.get("passengers_confirmed")):
        derived.add("passengers")
    assert qwen_missing == derived, f"[{case_id}] missing_fields mismatch"

    # --- clarify parity: SAME single next question --------------------------
    store = ProfileStore(root=tmp_path)
    user_id = f"parity_{case_id}"
    if case_id == "contradicts_profile":
        # seed a stored passport country so both paths see the SAME profile
        # state while the goal text contradicts profile expectations
        prof = store.get_or_create(user_id)
        prof.identity.passport_country = "MM"
    legacy_clarify = ClarifyLoopSkill(profile_store=store)
    qwen_clarify = ClarifyLoopTool(skill=ClarifyLoopSkill(profile_store=store))

    rs = legacy_out.get("requested_services") or {}
    legacy_c = _run_sync(legacy_clarify.run(
        {"goal": legacy_goal, "user_id": user_id, "requested_services": rs}, None))
    qwen_c = json.loads(qwen_clarify.call(json.dumps({
        "trip_goal": qwen_goal, "profile": {}, "user_id": user_id,
        "requested_services": rs,
    })))["clarify"]

    legacy_next = _single_next_question(legacy_c.get("questions") or [])
    qwen_next = qwen_c.get("questions") or []
    assert [q.get("field") for q in qwen_next] == [q.get("field") for q in legacy_next], \
        f"[{case_id}] next-question identity differs: {qwen_next} vs {legacy_next}"
    assert len(qwen_next) <= 1, f"[{case_id}] qwen path must ask at most ONE question"

    # PII rule: neither path ever asks a forbidden field
    for q in (legacy_c.get("questions") or []) + qwen_next:
        assert q.get("field") not in FORBIDDEN_PII_FIELDS, \
            f"[{case_id}] forbidden PII field asked: {q.get('field')}"

    # ambiguity confirmation parity (multi-airport 'Bangkok' flags BOTH paths)
    if case_id == "multi_airport_origin":
        for g in (legacy_goal, qwen_goal):
            assert g.get("origin_airport_candidates") == ["BKK", "DMK"]
            assert not g.get("confirmed_origin_airport"), \
                "multi-airport origin must require confirmation in both paths"
        assert [q.get("field") for q in qwen_next] == ["confirmed_origin_airport"] \
            or [q.get("field") for q in legacy_next] == [q.get("field") for q in qwen_next]

    # venue-instead-of-city parity: both paths resolve venue deterministically
    if case_id == "venue_instead_of_city":
        assert _goal_view(legacy_goal).get("venue") == _goal_view(qwen_goal).get("venue")


def test_parity_malformed_llm_output_falls_back_labeled(tmp_path, monkeypatch):
    """§8.4 item 3: malformed LLM output → deterministic fallback, labeled
    degraded; identical structured result to the pure-legacy path; no crash,
    no fabricated fields."""
    legacy_intake = GoalIntakeSkill(llm_chat=_garbage_chat)
    qwen_intake = GoalIntakeTool(skill=GoalIntakeSkill(llm_chat=_garbage_chat))
    text = "Fly from Bangkok to Yangon on 2026-09-28 to 2026-09-30"

    legacy_out = _run_sync(legacy_intake.run({"free_text": text}, None))
    qwen_res = json.loads(qwen_intake.call(json.dumps({"text": text})))

    assert qwen_res["status"] == "success"
    assert qwen_res.get("degraded") is True, \
        "malformed LLM output must be labeled degraded (honest fallback)"
    assert legacy_out.get("degraded") is True
    assert _goal_view(legacy_out["goal"]) == _goal_view(qwen_res["trip_goal"]), \
        "fallback must reproduce the deterministic legacy extraction exactly"
    # nothing fabricated: no field present in qwen result that legacy lacks
    for key, value in _goal_view(qwen_res["trip_goal"]).items():
        assert value == _goal_view(legacy_out["goal"]).get(key)
