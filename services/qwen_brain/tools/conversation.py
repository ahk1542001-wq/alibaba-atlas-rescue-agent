"""Conversation layer tools for Qwen-Agent: goal_intake and clarify_loop."""

import asyncio
import concurrent.futures
import json
from typing import Any, Dict, Optional

import json5
from qwen_agent.tools.base import BaseTool, register_tool

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


@register_tool("goal_intake")
class GoalIntakeTool(BaseTool):
    description = (
        "Extract structured travel goals (origin city, destination city, dates, "
        "passengers, budget) from natural language text."
    )
    parameters = [
        {
            "name": "free_text",
            "type": "string",
            "description": "The traveler's natural language travel request",
            "required": True,
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
            free_text = str(args.get("free_text", "")).strip()
            ctx = context or args.get("context")
            result = _run_coro_sync(self._skill.run({"free_text": free_text}, ctx))
            return json.dumps({
                "status": "success",
                "goal": result.get("goal", {}),
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
            "name": "goal",
            "type": "object",
            "description": "Current structured travel goal dictionary",
            "required": True,
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
            goal = args.get("goal") or {}
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
            result = _run_coro_sync(self._skill.run(payload, ctx))
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
