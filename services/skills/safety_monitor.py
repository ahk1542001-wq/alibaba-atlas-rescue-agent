"""safety_monitor skill (Task #13) — consent-gated bounded rechecks.

Runs ONLY after the user enables monitoring consent. Stores a hash of the
normalized APPLICABLE evidence and emits a SafetyChangeEvent ONLY on a
material change (severity / affected region / validity period /
recommended action), retaining old + new evidence and identifying the
differences. A change may PROPOSE a partial replan via approval — it never
modifies or rebooks anything. Push delivery (if any) goes through the
existing guardian_push skill path at the orchestrator layer, never here.

Manifest documented at services/safety/safety_monitor.SKILL.md (outside
the loader glob — frozen suite pins services/skills/ at 11 entries;
recorded honestly in DECISIONS.tsv/PLAN.md).
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from models.schemas import SafetyChangeEvent, SafetyQuery
from services.skills.base import SkillBase

# material dimensions and the entry fields that realize them
_MATERIAL_FIELDS = {
    "severity": ("normalized_level",),
    "affected_region": ("affected_regions",),
    "validity": ("valid_from", "valid_to"),
    "actions": ("recommended_actions",),
}


def _material_tuple(entry: Dict[str, Any]) -> List[Any]:
    """Normalized, retrievable-at-independent fingerprint inputs."""
    return [
        entry.get("source_id"),
        entry.get("normalized_level"),
        sorted(entry.get("affected_regions") or []),
        entry.get("valid_from"),
        entry.get("valid_to"),
        sorted(entry.get("recommended_actions") or []),
    ]


def _applicable_entries(assessment: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {e["source_id"]: e
            for e in assessment.get("assessments_per_source", [])
            if e.get("applies")}


def _state_hash(applicable: Dict[str, Dict[str, Any]]) -> str:
    payload = {sid: _material_tuple(entry)
               for sid, entry in sorted(applicable.items())}
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class SafetyMonitorSkill(SkillBase):
    name = "safety_monitor"
    when_to_use = (
        "after the traveler explicitly enables monitoring consent; bounded "
        "rechecks emit SafetyChangeEvents on material advisory changes only"
    )
    capabilities = frozenset({"network_read"})

    def __init__(self, clock: Optional[Callable[[], datetime]] = None,
                 min_interval_seconds: int = 1800) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._min_interval = max(0, int(min_interval_seconds))
        self._consents: Dict[str, bool] = {}
        # trip_id -> {"hash": str, "snapshot": {source_id: entry}, "at": dt}
        self._state: Dict[str, Dict[str, Any]] = {}
        self._events: Dict[str, List[SafetyChangeEvent]] = {}

    # -- consent --------------------------------------------------------------

    def set_consent(self, trip_id: str, enabled: bool) -> None:
        self._consents[str(trip_id)] = bool(enabled)
        if not enabled:
            self._state.pop(str(trip_id), None)

    def consent_enabled(self, trip_id: str) -> bool:
        return bool(self._consents.get(str(trip_id)))

    def events_for(self, trip_id: str) -> List[SafetyChangeEvent]:
        return list(self._events.get(str(trip_id), []))

    # -- bounded recheck -------------------------------------------------------

    async def run(self, payload: Dict[str, Any],
                  context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        trip_id = str(payload.get("trip_id")
                      or (context or {}).get("trip_id") or "")
        enabled = payload.get("enabled")
        if enabled is not None:
            self.set_consent(trip_id, bool(enabled))
        return {"skill": self.name, "trip_id": trip_id,
                "monitor_enabled": self.consent_enabled(trip_id),
                "status": "consent_updated" if enabled is not None
                else "consent_required" if not self.consent_enabled(trip_id)
                else "armed"}

    async def check(self, trip_id: str, query: SafetyQuery,
                    research_skill: Any) -> Dict[str, Any]:
        trip_id = str(trip_id)
        if not self.consent_enabled(trip_id):
            return {"status": "consent_required", "events": [],
                    "trip_id": trip_id}
        now = self._clock()
        prior = self._state.get(trip_id)
        if prior is not None and self._min_interval > 0:
            elapsed = (now - prior["at"]).total_seconds()
            if elapsed < self._min_interval:
                return {"status": "recheck_too_soon", "events": [],
                        "trip_id": trip_id,
                        "retry_after_seconds": int(self._min_interval
                                                   - elapsed)}
        result = await research_skill.run(query.model_dump(mode="json"))
        assessment = result.get("assessment") or {}
        applicable = _applicable_entries(assessment)
        digest = _state_hash(applicable)
        record = {"hash": digest, "snapshot": applicable, "at": now,
                  "overall_status": assessment.get("overall_status")}
        events: List[SafetyChangeEvent] = []
        if prior is not None and prior["hash"] != digest:
            event = self._diff(trip_id, now, prior["snapshot"], applicable)
            if event is not None:
                events.append(event)
        self._state[trip_id] = record
        if events:
            self._events.setdefault(trip_id, []).extend(events)
        return {
            "status": "checked",
            "trip_id": trip_id,
            "events": [e.model_dump(mode="json") for e in events],
            "overall_status": assessment.get("overall_status"),
            "checked_at": now.isoformat(),
        }

    # -- material-change diff ----------------------------------------------------

    def _diff(self, trip_id: str, now: datetime,
              old: Dict[str, Dict[str, Any]],
              new: Dict[str, Dict[str, Any]]
              ) -> Optional[SafetyChangeEvent]:
        change_kinds: List[str] = []
        differences: List[str] = []
        for sid in sorted(set(old) | set(new)):
            o, n = old.get(sid), new.get(sid)
            if o is None:
                change_kinds.append("affected_region")
                differences.append(f"{sid}: now applies to this route")
                continue
            if n is None:
                change_kinds.append("affected_region")
                differences.append(f"{sid}: no longer applies to this route")
                continue
            for kind, fields in _MATERIAL_FIELDS.items():
                ov = [o.get(f) for f in fields]
                nv = [n.get(f) for f in fields]
                if ov != nv:
                    if kind not in change_kinds:
                        change_kinds.append(kind)
                    differences.append(
                        f"{sid}: {', '.join(fields)} "
                        f"{'/'.join(map(str, ov))} -> "
                        f"{'/'.join(map(str, nv))}")
        if not change_kinds:
            return None  # non-material drift: never an event
        return SafetyChangeEvent(
            event_id=f"sc_{uuid.uuid4().hex[:12]}",
            trip_id=trip_id,
            detected_at=now.isoformat(),
            change_kinds=change_kinds,
            differences=differences,
            old_evidence={sid: old[sid] for sid in old},
            new_evidence={sid: new[sid] for sid in new},
            proposed_action="review",
            approval_required=True,
        )
