"""Concierge turn projection for Qwen-Agent."""

import json
import logging
from typing import Any, Dict, Optional

from services import llm_providers
from services.qwen_brain.agent import run_qwen_conversation, WAVE1_TOOLS

logger = logging.getLogger("qwen_brain.concierge")


def _extract_last_assistant_text(history: list) -> Optional[str]:
    for msg in reversed(history):
        if isinstance(msg, dict):
            role = msg.get("role", "")
            content = msg.get("content", "")
        else:
            role = getattr(msg, "role", "")
            content = getattr(msg, "content", "")
        if role == "assistant" and content:
            if isinstance(content, list):
                # May be list of content parts
                text_parts = [p.get("text", "") if isinstance(p, dict) else str(p) for p in content]
                return "".join(text_parts).strip()
            return str(content).strip()
    return None


async def run_qwen_concierge_turn(
    query: str,
    context: Optional[Dict[str, Any]] = None,
    engine: Optional[Any] = None,
) -> Dict[str, Any]:
    """Execute concierge assistance turn via Qwen-Agent."""
    if not context:
        if engine is not None:
            return await engine.answer_concierge(query, context=None)
        return {
            "reply": (
                "I do not have an active trip or disruption session right now. "
                "Tell me where you want to travel or simulate a disruption to get started."
            ),
            "action_taken": "NO_ACTIVE_SESSION",
        }

    # Bounded trip summary for system prompt
    trip_summary = {
        "trip_id": context.get("trip_id"),
        "status": context.get("status"),
        "goal": (context.get("goal_intake") or {}).get("goal") or context.get("goal"),
        "requested_services": context.get("requested_services"),
    }
    system_msg = (
        "You are TravelCare AI, an autonomous travel concierge and disruption-recovery assistant. "
        f"Active Trip Context: {json.dumps(trip_summary, default=str)}. "
        "Answer passenger questions concisely and accurately using available tools when appropriate. "
        "Never fabricate flight, visa, rights, or safety facts."
    )
    messages = [{"role": "user", "content": query}]

    try:
        history = await run_qwen_conversation(
            messages=messages,
            tools=list(WAVE1_TOOLS),
            system_message=system_msg,
        )
        reply = _extract_last_assistant_text(history)
        if reply:
            return {
                "reply": reply,
                "action_taken": "QWEN_AGENT_REPLY",
                "engine": llm_providers.active_provider(),
                "model": "qwen3-235b",
            }
    except Exception as exc:
        logger.warning("Qwen concierge failed: %s: %s", type(exc).__name__, exc)

    # Deterministic / rule-based fallback via legacy engine
    if engine is not None:
        return await engine.answer_concierge(query, context=context)
    from services.atlas_client import AtlasClient
    from services.rescue_engine import RescueEngine
    legacy_engine = RescueEngine(AtlasClient())
    return await legacy_engine.answer_concierge(query, context=context)
