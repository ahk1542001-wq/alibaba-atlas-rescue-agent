"""clarify_loop skill — contract phase (G1). Real behavior lands at G2 (§4 S2 loop L1)."""

from typing import Optional

from pydantic import BaseModel

from models.schemas import TripGoal
from services.skills.base import SkillBase


class ClarifyLoopInput(BaseModel):
    goal: TripGoal
    user_id: str
    last_user_message: Optional[str] = None


class ClarifyLoopSkill(SkillBase):
    name = "clarify_loop"
    when_to_use = (
        "after goal intake, when TripGoal fields are incomplete; asks only "
        "missing questions and surfaces confirmation chips for inferred facts"
    )
    input_model = ClarifyLoopInput
    output_model = None  # pending questions + ConfirmationChip[] materialize at G2
    capabilities = frozenset({"llm_call"})
