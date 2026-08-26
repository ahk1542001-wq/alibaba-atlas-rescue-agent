"""disruption_monitor skill — contract phase (G1). Real behavior lands at G2 (§4 S11)."""

from typing import List

from pydantic import BaseModel

from services.skills.base import SkillBase


class DisruptionMonitorInput(BaseModel):
    pnr: str
    flight_ids: List[str] = []


class DisruptionMonitorSkill(SkillBase):
    name = "disruption_monitor"
    when_to_use = (
        "while an active PNR exists; watches the radar feed and emits a "
        "DisruptionEvent that mounts the RecoveryDAG subgraph"
    )
    input_model = DisruptionMonitorInput
    output_model = None  # DisruptionEvent? materializes at G2
    capabilities = frozenset({"network_read"})
