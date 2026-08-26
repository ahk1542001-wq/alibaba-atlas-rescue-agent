"""itinerary skill — contract phase (G1). Real behavior lands at G2 (§4 S8)."""

from typing import Optional

from pydantic import BaseModel

from models.schemas import BookingRecord
from services.skills.base import SkillBase


class ItineraryInput(BaseModel):
    booking: BookingRecord
    budget_hint: Optional[str] = None


class ItinerarySkill(SkillBase):
    name = "itinerary"
    when_to_use = (
        "after booking confirmation; builds itinerary items where flights stay "
        "atlas_real and hotels/activities carry suggestion/researched-mock chips"
    )
    input_model = ItineraryInput
    output_model = None  # ItineraryItem[] materializes at G2
    capabilities = frozenset({"llm_call"})
