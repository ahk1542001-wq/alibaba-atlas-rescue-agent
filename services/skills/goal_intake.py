"""goal_intake skill — contract phase (G1). Real behavior lands at G2 (§4 S1)."""

from pydantic import BaseModel

from services.skills.base import SkillBase


class GoalIntakeInput(BaseModel):
    free_text: str


class GoalIntakeSkill(SkillBase):
    name = "goal_intake"
    when_to_use = "when the user submits a free-text travel goal in any phrasing"
    input_model = GoalIntakeInput
    output_model = None  # TripGoal (models.schemas) materializes with G2 behavior
    capabilities = frozenset({"llm_call"})
