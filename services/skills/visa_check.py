"""visa_check skill — contract phase (G1). Real behavior lands at G2 (§4 S6)."""

from typing import List

from pydantic import BaseModel

from services.skills.base import SkillBase


class VisaCheckInput(BaseModel):
    passport_country: str
    route: List[str]  # ordered IATA airport codes


class VisaCheckSkill(SkillBase):
    name = "visa_check"
    when_to_use = (
        "when an itinerary crosses borders or the user asks visa questions; "
        "KG baseline first, web-intel citations with as-of dates on top"
    )
    input_model = VisaCheckInput
    output_model = None  # VisaRequirement[] (models.schemas) materializes at G2
    capabilities = frozenset({"network_read"})
