"""Proactive Telegram Guardian.

The rescue agent should find YOU, not the other way around. When the radar
detects a disruption (or the rights engine finds unclaimed money), the
guardian pushes a proactive Telegram message with a one-tap action link.

Demo-safe: without TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID configured, sends
are simulated and returned as previews so the hackathon demo never breaks.
"""

import logging
from typing import Any, Dict, Optional

import httpx

from config import settings

logger = logging.getLogger("guardian")

TELEGRAM_API = "https://api.telegram.org"


async def notify(
    title: str,
    body: str,
    action_label: Optional[str] = None,
    deep_link: Optional[str] = None,
) -> Dict[str, Any]:
    """Send one proactive guardian push. Never raises — demo safety."""
    token = getattr(settings, "telegram_bot_token", None)
    chat_id = getattr(settings, "telegram_chat_id", None)
    text = f"🛟 {title}\n\n{body}"
    if action_label:
        text += f"\n\n👉 {action_label}" + (f": {deep_link}" if deep_link else "")

    if not token or not chat_id or not getattr(settings, "telegram_live_test", False):
        return {
            "pushed": False,
            "reason": "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not configured, or TELEGRAM_LIVE_TEST not true",
            "mocked_payload": payload
        }

    url = f"{TELEGRAM_API}/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    try:
        resp = httpx.post(url, json=payload, timeout=8)
        data: Dict[str, Any] = resp.json()
        ok = bool(data.get("ok"))
        return {
            "channel": "telegram",
            "sent": ok,
            "simulated": False,
            "preview": text,
            "error": None if ok else data.get("description"),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("guardian send failed: %s", exc)
        return {"channel": "telegram", "sent": False, "simulated": False,
                "preview": text, "error": str(exc)}
