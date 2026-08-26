"""flight_search skill — contract phase (G1). Real behavior lands at G2 (§4 S4)."""

from typing import Optional

from pydantic import BaseModel, Field

from models.schemas import DateWindow
from services.skills.base import SkillBase


class FlightSearchInput(BaseModel):
    origin: str
    destination: str
    date_window: Optional[DateWindow] = None
    passengers: int = Field(1, ge=1)


class FlightSearchSkill(SkillBase):
    name = "flight_search"
    when_to_use = (
        "when the TripGoal carries route and dates; searches the Atlas sandbox "
        "and returns ranked FlightOption cards (never canned arrays)"
    )
    input_model = FlightSearchInput
    output_model = None  # List[FlightOption] (models.schemas) materializes at G2
    capabilities = frozenset({"atlas_call", "network_read"})
