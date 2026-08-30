"""Conversation layer tools for Qwen-Agent: goal_intake and clarify_loop."""

import asyncio
import concurrent.futures
import json
from typing import Any, Dict, Optional

import json5
from qwen_agent.tools.base import BaseTool, register_tool

from services.conversation_controller import QUESTION_FIELD_ORDER
from services.skills.goal_intake import GoalIntakeSkill
from services.skills.clarify_loop import ClarifyLoopSkill


def _run_coro_sync(coro):
    """Execute an async coroutine synchronously from within a tool call."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is None:
        return asyncio.run(coro)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()


def _missing_goal_fields(goal: Dict[str, Any]) -> list:
    """Goal-derived missing fields, ordered by QUESTION_FIELD_ORDER.

    Profile-dependent fields (passport_country, home_city) are deliberately
    NOT computed here — goal_intake does not read profiles; clarify_loop
    owns those questions.
    """
    missing = []
    if not goal.get("origin_city"):
        missing.append("origin_city")
    if not goal.get("dest_city"):
        missing.append("dest_city")
    if not goal.get("date_window"):
        missing.append("date_window")
    # the extractor defaults passengers to 1, so only an EXPLICIT or confirmed
    # count satisfies the field (a bare value may be the default)
    if not (goal.get("passengers_explicit") or goal.get("passengers_confirmed")):
        missing.append("passengers")
    return sorted(missing, key=lambda f: QUESTION_FIELD_ORDER.index(f))


def _single_next_question(questions: list) -> list:
    """§13.3/§8 contract: the qwen conversation path emits at most ONE next
    question — the first missing field per QUESTION_FIELD_ORDER."""
    order = {field: index for index, field in enumerate(QUESTION_FIELD_ORDER)}
    ranked = [q for q in questions if q.get("field") in order]
    if ranked:
        return [min(ranked, key=lambda q: order[q["field"]])]
    return list(questions)[:1]


@register_tool("goal_intake")
class GoalIntakeTool(BaseTool):
    description = (
        "Extract structured travel goals (origin city, destination city, dates, "
        "passengers, budget) from natural language text."
    )
    parameters = [
        {
            "name": "text",
            "type": "string",
            "description": "The traveler's natural language travel request",
            "required": True,
        },
        {
            "name": "free_text",
            "type": "string",
            "description": "Legacy alias of 'text' (deprecated)",
            "required": False,
        },
    ]

    def __init__(self, cfg: Optional[Dict[str, Any]] = None, skill: Optional[GoalIntakeSkill] = None):
        super().__init__(cfg)
        self._skill = skill or GoalIntakeSkill()

    def call(self, params: str, context: Optional[Dict[str, Any]] = None, **kwargs) -> str:
        try:
            args = json5.loads(params)
            if not isinstance(args, dict):
                return json.dumps({
                    "status": "failed",
                    "error": "Parameters must decode to a JSON object",
                    "tool": "goal_intake",
                })
            # §13.3 contract: param name is `text`; `free_text` kept as alias.
            free_text = str(args.get("text") or args.get("free_text") or "").strip()
            ctx = context or args.get("context")
            result = _run_coro_sync(self._skill.run({"free_text": free_text}, ctx))
            trip_goal = result.get("goal", {})
            return json.dumps({
                "status": "success",
                # §13.3 return shape: {status, trip_goal, missing_fields}
                "trip_goal": trip_goal,
                "missing_fields": _missing_goal_fields(trip_goal),
                # legacy keys kept for existing internal callers
                "goal": trip_goal,
                "requested_services": result.get("requested_services", {}),
                "degraded": result.get("degraded", False),
            })
        except Exception as exc:
            return json.dumps({
                "status": "failed",
                "error": f"{type(exc).__name__}: {str(exc)}",
                "tool": "goal_intake",
            })


@register_tool("clarify_loop")
class ClarifyLoopTool(BaseTool):
    description = (
        "Identify missing required travel information and generate clarification "
        "questions or scope choices for incomplete travel goals."
    )
    parameters = [
        {
            "name": "trip_goal",
            "type": "object",
            "description": "Current structured travel goal dictionary",
            "required": True,
        },
        {
            "name": "profile",
            "type": "object",
            "description": "User profile snapshot used to skip already-known facts",
            "required": False,
        },
        {
            "name": "goal",
            "type": "object",
            "description": "Legacy alias of 'trip_goal' (deprecated)",
            "required": False,
        },
        {
            "name": "user_id",
            "type": "string",
            "description": "User identifier for profile inspection",
            "required": False,
        },
        {
            "name": "requested_services",
            "type": "object",
            "description": "Requested services state dictionary",
            "required": False,
        },
        {
            "name": "scope_choice",
            "type": "string",
            "description": "Optional three-way scope choice",
            "required": False,
        },
    ]

    def __init__(self, cfg: Optional[Dict[str, Any]] = None, skill: Optional[ClarifyLoopSkill] = None):
        super().__init__(cfg)
        self._skill = skill or ClarifyLoopSkill()

    def call(self, params: str, context: Optional[Dict[str, Any]] = None, **kwargs) -> str:
        try:
            args = json5.loads(params)
            if not isinstance(args, dict):
                return json.dumps({
                    "status": "failed",
                    "error": "Parameters must decode to a JSON object",
                    "tool": "clarify_loop",
                })
            # §13.3 contract: params {trip_goal, profile}; `goal` kept as alias.
            goal = args.get("trip_goal") or args.get("goal") or {}
            user_id = str(args.get("user_id") or "")
            requested_services = args.get("requested_services") or {}
            scope_choice = args.get("scope_choice")

            payload = {
                "goal": goal,
                "user_id": user_id,
                "requested_services": requested_services,
            }
            if scope_choice:
                payload["scope_choice"] = scope_choice

            ctx = context or args.get("context")
            # Contract note: the deterministic ClarifyLoopSkill resolves the
            # authoritative profile from the profile store by user_id; the
            # `profile` param is accepted per §13.3 and folded into the
            # context so skill/side logic can see it.
            skill_ctx = dict(ctx or {})
            if args.get("profile") is not None:
                skill_ctx.setdefault("profile", args.get("profile"))
            result = _run_coro_sync(self._skill.run(payload, skill_ctx or None))
            # §13.3/§8: the qwen CONTRACT surface emits at most ONE next
            # question (questions:[ONE]). The full legacy question list is
            # preserved under questions_all because the deterministic UI
            # question stepper and the missing_fields derivation consume it
            # exactly as legacy does (the UI shows one card at a time).
            full_questions = list(result.get("questions") or [])
            result = dict(result)
            result["questions"] = _single_next_question(full_questions)
            result["questions_all"] = full_questions
            return json.dumps({
                "status": "success",
                "clarify": result,
            })
        except Exception as exc:
            return json.dumps({
                "status": "failed",
                "error": f"{type(exc).__name__}: {str(exc)}",
                "tool": "clarify_loop",
            })
