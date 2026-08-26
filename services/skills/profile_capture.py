"""profile_capture skill — contract phase (G1). Real behavior lands at G2 (§4 S2/S3)."""

from typing import Any, Literal

from pydantic import BaseModel

from services.skills.base import SkillBase


class ProfileCaptureInput(BaseModel):
    user_id: str
    field: str
    value: Any
    source: Literal["user", "ai_inferred"] = "ai_inferred"


class ProfileCaptureSkill(SkillBase):
    name = "profile_capture"
    when_to_use = (
        "when clarification reveals personal facts; emits a confirmation chip "
        "and saves only after the user confirms"
    )
    input_model = ProfileCaptureInput
    output_model = None  # ProfilePatch/ConfirmationChip flow materializes at G2
    capabilities = frozenset({"profile_write"})
