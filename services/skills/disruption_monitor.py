"""disruption_monitor skill — §4 S11 (G2 behavior).

Arms a watch over the booked PNR/flight_ids. Watches are keyed BY TRIP_ID
(G2-DA fix): arming trip B no longer overwrites trip A's watch, and
simulate_disruption() carries a validated target trip_id so a disruption
can never mount onto the wrong trip. On a disruption event the skill asks
the trip executor (ON_DISRUPTION_EVENT hook) to mount the frozen
DisruptionRecoveryDAG as a subgraph — the trace is appended to the trip's
graph state. The G2 harness exposes simulate_disruption() so the unit
suite can prove mount latency (<2s) without a live radar feed; real
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
        # trip_id -> watch; per-trip keys keep concurrent trips isolated
        self._watches: Dict[str, Dict[str, Any]] = {}

    async def run(self, payload: Dict[str, Any],
                  context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        pnr = str(payload.get("pnr") or "")
        flight_ids: List[str] = [str(f) for f in (payload.get("flight_ids") or [])]
        trip_id = payload.get("trip_id") or (context or {}).get("trip_id")

        if pnr and trip_id and self._registry is not None:
            # armed: the mount happens when a disruption event actually fires,
            # not at watch-arming time (no speculative subgraphs)
            self._watches[str(trip_id)] = {"pnr": pnr, "flight_ids": flight_ids,
                                           "trip_id": str(trip_id)}
        return {
            "armed": bool(pnr),
            "subgraph_mounted": False,
            "watching": dict(self._watches.get(str(trip_id)) or {}),
            "armed_trips": sorted(self._watches),
            "pnr": pnr,
            "flight_ids": flight_ids,
        }

    async def simulate_disruption(self, event: Dict[str, Any],
                                  trip_id: Optional[str] = None
                                  ) -> Dict[str, Any]:
        """Deterministic disruption hook (unit harness / demo). Real radar
        events call the same ON_DISRUPTION_EVENT path at G3.

        Targeting is VALIDATED (G2-DA fix): an explicit trip_id must be an
        armed watch; without one, targeting is deterministic only when
        exactly one watch is armed — otherwise the event is refused instead
        of guessing a trip.
        """
        if trip_id is None:
            if len(self._watches) == 1:
                trip_id = next(iter(self._watches))
            elif len(self._watches) > 1:
                return {"mounted": False, "event": event,
                        "reason": "ambiguous_target",
                        "hint": "pass trip_id; armed watches: "
                                + ", ".join(sorted(self._watches))}
            else:
                return {"mounted": False, "event": event,
                        "reason": "no armed trip registry"}
        trip_id = str(trip_id)
        watch = self._watches.get(trip_id)
        if watch is None or self._registry is None:
            return {"mounted": False, "event": event, "trip_id": trip_id,
                    "reason": "unknown_or_unarmed_trip"}
        try:
            telemetry = await self._registry.on_disruption(trip_id, event)
        except KeyError:
            # trip vanished from the registry: refuse honestly, never guess
            return {"mounted": False, "event": event, "trip_id": trip_id,
                    "reason": "unknown_trip"}
        return {"mounted": True, "event": event,
                "trip_id": trip_id, "pnr": watch.get("pnr"),
                "subgraph": telemetry}
