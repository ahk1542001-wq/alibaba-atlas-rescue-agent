"""guardian_push skill — §4 S10 (G2 behavior).

Proactive Telegram alerts via the frozen services.guardian (import-only).
Privacy hard rule (§9.4): passport numbers and identity-document values are
STRIPPED from the payload before anything is built or sent. Token absent →
delivery_status=skipped_not_failed + simulated=True (graceful skip, never
an error, never a fabricated send).
"""

from typing import Any, Dict

from config import settings
from services.skills.base import SkillBase

# identity-document fields never leave the agent (only masked forms may surface)
_FORBIDDEN_PAYLOAD_KEYS = {"passport_no", "passport_number", "passport",
                           "passport_no_raw", "national_id", "document_number"}


def sanitize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop forbidden identity fields; recurse into nested dicts."""
    clean: Dict[str, Any] = {}
    for key, value in (payload or {}).items():
        if str(key).lower() in _FORBIDDEN_PAYLOAD_KEYS:
            continue
        if isinstance(value, dict):
            clean[key] = sanitize_payload(value)
        else:
            clean[key] = value
    return clean


class GuardianPushSkill(SkillBase):
    name = "guardian_push"
    when_to_use = (
        "when a proactive alert is warranted; wraps services.guardian via "
        "asyncio.to_thread — token absent yields skipped_not_failed"
    )
    capabilities = frozenset({"telegram_send"})

    async def run(self, payload: Dict[str, Any],
                  context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        event = str(payload.get("event") or "alert")
        safe = sanitize_payload(payload.get("payload") or {})

        token = getattr(settings, "telegram_bot_token", "")
        if not token:
            # graceful skip — demo-safe, never a failure, never a fake send
            return {
                "delivery_status": "skipped_not_failed",
                "simulated": True,
                "channel": "telegram",
                "event": event,
                "payload": safe,
                "reason": "TELEGRAM_BOT_TOKEN not configured",
            }

        from services.guardian import notify  # frozen service, import-only
        body_lines = [f"{k}: {v}" for k, v in safe.items()
                      if not isinstance(v, dict)]
        result = await notify(title=f"TravelCare alert — {event}",
                              body="\n".join(body_lines) or event)
        status = "sent" if result.get("sent") else (
            "skipped_not_failed" if result.get("simulated") else "failed")
        return {
            "delivery_status": status,
            "simulated": bool(result.get("simulated")),
            "channel": result.get("channel", "telegram"),
            "event": event,
            "payload": safe,
            "error": result.get("error"),
        }
