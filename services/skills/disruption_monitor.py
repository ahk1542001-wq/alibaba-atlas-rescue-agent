"""disruption_monitor skill — §4 S11 (G2 behavior).

Arms a watch over the booked PNR/flight_ids. On a disruption event the
skill asks the trip executor (ON_DISRUPTION_EVENT hook) to mount the
frozen DisruptionRecoveryDAG as a subgraph — the trace is appended to the
trip's graph state. The G2 harness exposes simulate_disruption() so the
unit suite can prove mount latency (<2s) without a live radar feed; real
radar/SSE wiring lands at G3 behind the same hook.
"""

from typing import Any, Dict, List, Optional

from services.skills.base import SkillBase


class DisruptionMonitorSkill(SkillBase):
    name = "disruption_monitor"
    when_to_use = (
        "while an active PNR exists; watches the radar feed and emits a "
        "DisruptionEvent that mounts the RecoveryDAG subgraph"
    )
    capabilities = frozenset({"network_read"})

    def __init__(self, trip_registry: Optional[Any] = None) -> None:
        self._registry = trip_registry
        self._watch: Dict[str, Any] = {}

    async def run(self, payload: Dict[str, Any],
                  context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        pnr = str(payload.get("pnr") or "")
        flight_ids: List[str] = [str(f) for f in (payload.get("flight_ids") or [])]
        trip_id = payload.get("trip_id") or (context or {}).get("trip_id")

        mounted = False
        if trip_id and self._registry is not None:
            # armed: the mount happens when a disruption event actually fires,
            # not at watch-arming time (no speculative subgraphs)
            self._watch = {"pnr": pnr, "flight_ids": flight_ids,
                           "trip_id": trip_id}
        return {
            "armed": bool(pnr),
            "subgraph_mounted": mounted,
            "watching": dict(self._watch),
            "pnr": pnr,
            "flight_ids": flight_ids,
        }

    async def simulate_disruption(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Deterministic disruption hook (unit harness / demo). Real radar
        events call the same ON_DISRUPTION_EVENT path at G3."""
        trip_id = self._watch.get("trip_id")
        if not trip_id or self._registry is None:
            return {"mounted": False, "event": event,
                    "reason": "no armed trip registry"}
        telemetry = await self._registry.on_disruption(trip_id, event)
        return {"mounted": True, "event": event,
                "trip_id": trip_id, "subgraph": telemetry}
