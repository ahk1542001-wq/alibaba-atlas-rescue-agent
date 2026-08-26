"""guardian_push skill — contract phase (G1). Real behavior lands at G2 (§4 S10)."""

from typing import Any, Dict

from pydantic import BaseModel

from services.skills.base import SkillBase


class GuardianPushInput(BaseModel):
    event: str
    payload: Dict[str, Any] = {}


class GuardianPushSkill(SkillBase):
    name = "guardian_push"
    when_to_use = (
        "when a proactive alert is warranted; wraps services.guardian via "
        "asyncio.to_thread — token absent yields skipped_not_failed"
    )
    input_model = GuardianPushInput
    output_model = None  # delivery_status materializes at G2
    capabilities = frozenset({"telegram_send"})
