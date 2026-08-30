"""Qwen-Agent factory and runner for TravelCare AI."""

import asyncio
import datetime
import logging
from typing import Any, Dict, List, Optional

from qwen_agent.agents import Assistant
from services import llm_providers

# Register all Wave 1 tools
import services.qwen_brain.tools.conversation
import services.qwen_brain.tools.flight
import services.qwen_brain.tools.visa
import services.qwen_brain.tools.rights
import services.qwen_brain.tools.safety

logger = logging.getLogger("qwen_brain.agent")

WAVE1_TOOLS = [
    "goal_intake",
    "clarify_loop",
    "flight_search",
    "visa_check",
    "rights_check",
    "safety_check",
]

DEFAULT_SYSTEM_MESSAGE = (
    "You are TravelCare AI, an autonomous travel concierge and disruption-recovery assistant. "
    "Use tools when needed to parse requests and look up facts. Never fabricate flight, "
    "visa, rights, or safety facts — always invoke the corresponding tool. Reply concisely."
)


def build_travelcare_agent(
    tools: Optional[List[str]] = None,
    system_message: Optional[str] = None,
) -> Optional[Assistant]:
    """Construct a Qwen-Agent Assistant with the resolved healthy provider config.

    Returns None if no LLM provider is available / configured.
    """
    llm_cfg = llm_providers.resolve_llm_cfg()
    if not llm_cfg:
        logger.info("No healthy LLM provider resolved; Qwen-Agent cannot be initialized.")
        return None

    today = datetime.date.today().isoformat()
    sys_msg = (system_message or DEFAULT_SYSTEM_MESSAGE) + f" Today's date is {today}."
    fn_list = tools if tools is not None else list(WAVE1_TOOLS)

    try:
        bot = Assistant(
            llm=llm_cfg,
            system_message=sys_msg,
            function_list=fn_list,
            name="TravelCare Qwen-Agent",
            description="Autonomous TravelCare agent powered by Qwen3-235B",
        )
        return bot
    except Exception as exc:
        logger.warning(f"Failed to instantiate Qwen-Agent Assistant: {type(exc).__name__}: {exc}")
        return None


async def run_qwen_conversation(
    messages: List[Dict[str, Any]],
    tools: Optional[List[str]] = None,
    system_message: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Run Qwen-Agent conversation asynchronously via thread pool.

    Returns the message history on success or an empty list on failure.
    """
    bot = build_travelcare_agent(tools=tools, system_message=system_message)
    if not bot:
        return []

    def _sync_run():
        history = []
        try:
            for history in bot.run(messages=messages, stream=False):
                pass
            return history
        except Exception as exc:
            logger.warning(f"Qwen-Agent execution error: {type(exc).__name__}: {exc}")
            return []

    return await asyncio.to_thread(_sync_run)
