"""Authoritative runtime selector for TravelCare brain architecture.

Callers must check brain flags strictly through this module.
"""

import os
from config import settings


def active_brain() -> str:
    """Return the active brain name ('legacy' | 'qwen_agent')."""
    # Re-read env or fall back to settings to honor dynamic runtime test patches
    env_val = os.getenv("TRAVELCARE_BRAIN")
    if env_val is not None:
        val = env_val.strip().lower()
        if val in {"legacy", "qwen_agent"}:
            return val
        return "legacy"
    return settings.travelcare_brain


def is_qwen_brain() -> bool:
    """Return True if the active brain is Qwen-Agent."""
    return active_brain() == "qwen_agent"
