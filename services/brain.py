"""Authoritative runtime selector for TravelCare brain architecture.

Callers must check brain flags strictly through this module.
"""

import importlib.util
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


def qwen_brain_available() -> bool:
    """True only if the qwen-agent package can actually be imported.

    Uses importlib.util.find_spec (no import side effects) so the deferred
    qwen_brain imports in the routers can gate on it and serve a LABELED
    legacy fallback instead of a raw 500 when the package is absent
    (audit finding #9).
    """
    try:
        return importlib.util.find_spec("qwen_agent") is not None
    except Exception:
        return False
