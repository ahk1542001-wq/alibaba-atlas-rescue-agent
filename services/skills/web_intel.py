"""web_intel skill — contract phase (G1). Real behavior lands at G2 (§4 S7)."""

from pydantic import BaseModel, Field

from services.skills.base import SkillBase


class WebIntelInput(BaseModel):
    query: str
    ttl_hours: int = Field(24, ge=1)


class WebIntelSkill(SkillBase):
    name = "web_intel"
    when_to_use = (
        "when freshness beyond the KG seed is needed; provider chain "
        "tavily→serper→ddg_lite→static_fallback with TTL cache, citations dated"
    )
    input_model = WebIntelInput
    output_model = None  # WebIntelCitation[] (models.schemas) materializes at G2
    capabilities = frozenset({"network_read"})
