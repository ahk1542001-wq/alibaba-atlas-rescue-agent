"""Qwen-Agent Conversation projection and goal intake layer."""

import asyncio
import logging
import json
from typing import Any, Dict, List, Optional, Tuple

from models.schemas import ConversationTurn
from services.conversation_controller import project_conversation_turn
from services.qwen_brain.agent import run_qwen_conversation
from services.qwen_brain.tools.conversation import GoalIntakeTool, ClarifyLoopTool
from services.skills.goal_intake import GoalIntakeSkill
from services.skills.clarify_loop import ClarifyLoopSkill

logger = logging.getLogger("qwen_brain.conversation")


def translate_messages_to_qwen(messages: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Translate internal TravelCare messages to Qwen-Agent message format."""
    qwen_msgs = []
    for m in messages:
        role = m.get("role", "user")
        if role not in ("user", "assistant", "system"):
            role = "user"
        content = m.get("content") or m.get("text") or ""
        qwen_msgs.append({"role": role, "content": str(content)})
    return qwen_msgs


async def run_qwen_goal_intake(
    goal_text: str,
    user_id: str,
    context: Optional[Dict[str, Any]] = None,
    goal_intake_skill: Optional[GoalIntakeSkill] = None,
    clarify_loop_skill: Optional[ClarifyLoopSkill] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Execute goal intake and clarify loop through Qwen-Agent conversation tools.

    Falls back cleanly to deterministic skill execution if tools return failed status.
    """
    intake_tool = GoalIntakeTool(skill=goal_intake_skill)
    # §13.3 contract: goal_intake takes `text` and returns
    # {status, trip_goal, missing_fields}.
    # Audit #7: deterministic tool calls are sync — dispatch them off the loop.
    intake_res_str = await asyncio.to_thread(
        intake_tool.call, json.dumps({"text": goal_text}), context=context
    )
    try:
        intake_data = json.loads(intake_res_str)
    except Exception:
        intake_data = {"status": "failed"}

    if intake_data.get("status") == "success":
        goal = intake_data.get("trip_goal") or intake_data.get("goal", {})
        req_services = intake_data.get("requested_services", {})
        goal_out = {
            "goal": goal,
            "requested_services": req_services,
            "degraded": intake_data.get("degraded", False),
        }
    else:
        skill = goal_intake_skill or GoalIntakeSkill()
        goal_out = await skill.run({"free_text": goal_text}, context)

    clarify_tool = ClarifyLoopTool(skill=clarify_loop_skill)
    # §13.3 contract: params {trip_goal, profile}; the tool still accepts the
    # user_id/requested_services aliases the deterministic skill needs.
    clarify_res_str = await asyncio.to_thread(
        clarify_tool.call,
        json.dumps({
            "trip_goal": goal_out["goal"],
            "profile": (context or {}).get("profile") or {},
            "user_id": user_id,
            "requested_services": goal_out["requested_services"],
        }),
        context=context,
    )
    try:
        clarify_data = json.loads(clarify_res_str)
    except Exception:
        clarify_data = {"status": "failed"}

    if clarify_data.get("status") == "success":
        clarify_out = clarify_data.get("clarify", {})
    else:
        clarify_skill = clarify_loop_skill or ClarifyLoopSkill()
        clarify_out = await clarify_skill.run({
            "goal": goal_out["goal"],
            "user_id": user_id,
            "requested_services": goal_out["requested_services"],
        }, context)

    return goal_out, clarify_out


async def run_qwen_trip_turn(
    state: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
) -> ConversationTurn:
    """Derive conversation turn through Qwen brain while preserving deterministic contracts."""
    turn = project_conversation_turn(state, context=context)
    return turn
