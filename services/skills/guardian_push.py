"""guardian_push skill — §4 S10 (G2 behavior).

Proactive Telegram alerts via the frozen services.guardian (import-only).
Privacy hard rule (§9.4): passport numbers and identity-document values are
STRIPPED from the payload before anything is built or sent. Token absent →
delivery_status=skipped_not_failed + simulated=True (graceful skip, never
an error, never a fabricated send).
"""

from typing import Any, Dict, Optional

from config import settings
from services.skills.base import SkillBase

# identity-document fields never leave the agent (only masked forms may surface)
_FORBIDDEN_PAYLOAD_KEYS = {"passport_no", "passport_number", "passport",
                           "passport_no_raw", "national_id", "document_number"}


def _sanitize_value(value: Any) -> Any:
    """Recursively drop forbidden identity fields through dicts AND
    lists/tuples (G2-DA fix: [{"passport_no": ...}] used to survive)."""
    if isinstance(value, dict):
        return {key: _sanitize_value(item) for key, item in value.items()
                if str(key).lower() not in _FORBIDDEN_PAYLOAD_KEYS}
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_value(item) for item in value)
    return value


def sanitize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop forbidden identity fields; recurse into nested dicts/lists/tuples."""
    return _sanitize_value(payload or {})


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

        from services.guardian import notify  # frozen service, import-only
        body_lines = [f"{k}: {v}" for k, v in safe.items()
                      if not isinstance(v, dict)]
        result = await notify(title=f"TravelCare alert — {event}",
                              body="\n".join(body_lines) or event)
        status = "sent" if result.get("sent") else (
            "skipped_not_failed" if result.get("simulated") else "failed")
        out: Dict[str, Any] = {
            "delivery_status": status,
            "simulated": bool(result.get("simulated")),
            "channel": result.get("channel", "telegram"),
            "event": event,
            "payload": safe,
            "preview": result.get("preview"),
            "error": result.get("error"),
        }
        if result.get("reason"):
            out["reason"] = result["reason"]
        return out
