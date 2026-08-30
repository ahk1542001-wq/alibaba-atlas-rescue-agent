"""Qwen-Agent factory and runner for TravelCare AI."""

import asyncio
import datetime
import logging
from typing import Any, Dict, List, Optional

from qwen_agent.agents import Assistant
from services import llm_providers
import services.qwen_brain.tools.conversation  # Register conversation tools

logger = logging.getLogger("qwen_brain.agent")

DEFAULT_SYSTEM_MESSAGE = (
    "You are TravelCare AI, an autonomous travel concierge and disruption-recovery assistant. "
    "Use tools when needed to parse requests and look up facts. Reply concisely."
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
    fn_list = tools if tools is not None else ["goal_intake", "clarify_loop"]

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
