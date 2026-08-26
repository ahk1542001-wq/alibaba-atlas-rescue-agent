"""flight_book skill — contract phase (G1). Real behavior lands at G2 (§4 S5)."""

from typing import List

from pydantic import BaseModel

from services.skills.base import SkillBase


class FlightBookInput(BaseModel):
    option_id: str
    passenger_refs: List[str] = []


class FlightBookSkill(SkillBase):
    name = "flight_book"
    when_to_use = (
        "only after ApprovalGate resolves approve; books the chosen FlightOption "
        "through the Atlas sandbox and returns a BookingRecord (idempotent retry)"
    )
    input_model = FlightBookInput
    output_model = None  # BookingRecord (models.schemas) materializes at G2
    capabilities = frozenset({"atlas_call", "approval_required"})
