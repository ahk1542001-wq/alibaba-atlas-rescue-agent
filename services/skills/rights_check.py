"""rights_check skill — contract phase (G1). Real behavior lands at G2 (§4 S9)."""

from typing import Optional

from pydantic import BaseModel

from services.skills.base import SkillBase


class RightsCheckInput(BaseModel):
    origin_airport: str
    destination_airport: str
    circumstances: Optional[str] = None


class RightsCheckSkill(SkillBase):
    name = "rights_check"
    when_to_use = (
        "when a disruption is confirmed or the user asks about entitlements; "
        "jurisdiction chosen server-side from the airport pair, regime cited"
    )
    input_model = RightsCheckInput
    output_model = None  # RightsOpinion materializes at G2 via rights_engine
    capabilities = frozenset()  # local rights_engine tables only; no external caps
