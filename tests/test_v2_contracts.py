"""§13.3 tool contract alignment (audit finding #5).

goal_intake: param `text`; return {status, trip_goal, missing_fields}.
clarify_loop: params {trip_goal, profile}; return {status, clarify:{questions:[ONE]}}.
The qwen conversation path must emit at most ONE next question, chosen by
QUESTION_FIELD_ORDER.
"""

import json

from services.conversation_controller import QUESTION_FIELD_ORDER
from services.qwen_brain.tools.conversation import ClarifyLoopTool, GoalIntakeTool


# --- goal_intake -------------------------------------------------------------

def test_goal_intake_contract_param_text_and_return_shape():
    tool = GoalIntakeTool()
    res = json.loads(tool.call(json.dumps(
        {"text": "Fly from Bangkok to Yangon on 2026-09-28 to 2026-09-30"})))
    assert res["status"] == "success"
    goal = res["trip_goal"]
    assert goal["origin_city"] == "BKK"
    assert goal["dest_city"] == "RGN"
    assert isinstance(res.get("missing_fields"), list)


def test_goal_intake_missing_fields_for_partial_goal():
    tool = GoalIntakeTool()
    res = json.loads(tool.call(json.dumps({"text": "I want to go to Singapore"})))
    assert res["status"] == "success"
    mf = res["missing_fields"]
    assert "dest_city" not in mf
    for field in ("origin_city", "date_window", "passengers"):
        assert field in mf, field
    # ordered by QUESTION_FIELD_ORDER
    idx = [QUESTION_FIELD_ORDER.index(f) for f in mf if f in QUESTION_FIELD_ORDER]
    assert idx == sorted(idx)


def test_goal_intake_no_missing_fields_for_complete_goal():
    tool = GoalIntakeTool()
    res = json.loads(tool.call(json.dumps(
        {"text": "Fly from Bangkok to Yangon on 2026-09-28 to 2026-09-30 for 2 passengers"})))
    assert res["status"] == "success"
    assert res["missing_fields"] == []


def test_goal_intake_legacy_free_text_alias_still_supported():
    tool = GoalIntakeTool()
    res = json.loads(tool.call(json.dumps(
        {"free_text": "Fly from Bangkok to Yangon on 2026-09-28 to 2026-09-30"})))
    assert res["status"] == "success"
    assert res["trip_goal"]["dest_city"] == "RGN"


# --- clarify_loop ------------------------------------------------------------

def test_clarify_loop_contract_params_and_single_next_question():
    tool = ClarifyLoopTool()
    trip_goal = {"origin_city": "BKK", "dest_city": None, "date_window": None}
    res = json.loads(tool.call(json.dumps({"trip_goal": trip_goal, "profile": {}})))
    assert res["status"] == "success"
    questions = res["clarify"]["questions"]
    assert len(questions) == 1, "clarify_loop must emit exactly ONE next question"
    assert questions[0]["field"] == "dest_city"  # first per QUESTION_FIELD_ORDER


def test_clarify_loop_single_question_respects_field_order():
    tool = ClarifyLoopTool()
    trip_goal = {"origin_city": None, "dest_city": "RGN", "date_window": None}
    res = json.loads(tool.call(json.dumps({"trip_goal": trip_goal, "profile": {}})))
    questions = res["clarify"]["questions"]
    assert [q["field"] for q in questions] == ["origin_city"]


def test_clarify_loop_no_questions_when_goal_complete():
    tool = ClarifyLoopTool()
    trip_goal = {"origin_city": "BKK", "dest_city": "RGN",
                 "date_window": {"start": "2026-09-28", "end": "2026-09-30"},
                 "passengers_explicit": True, "passengers": 1}
    res = json.loads(tool.call(json.dumps({"trip_goal": trip_goal, "profile": {}})))
    assert res["status"] == "success"
    assert res["clarify"]["questions"] == []


def test_clarify_loop_legacy_goal_alias_still_supported():
    tool = ClarifyLoopTool()
    res = json.loads(tool.call(json.dumps(
        {"goal": {"origin_city": "BKK", "dest_city": None}, "user_id": "u_ctr_1"})))
    assert res["status"] == "success"
    assert len(res["clarify"]["questions"]) == 1
