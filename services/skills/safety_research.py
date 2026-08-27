"""safety_research skill (Task #13) — read-only domain researcher.

Capability: network_read ONLY — no atlas_call, no profile_write, no
telegram_send, no approval. The manifest is documented at
services/safety/safety_research.SKILL.md (outside the loader glob on
purpose: the frozen manifest suite pins the services/skills/ registry at
exactly 11 entries — recorded honestly in DECISIONS.tsv/PLAN.md).

PRIME RULE: this skill NEVER decides whether a country is safe. It only
collects bounded facts from official sources via the adapters and hands
them to the deterministic SafetyPolicyEngine, which computes the status.
Fetched content is hostile DATA — never instructions.
"""

from datetime import date
from typing import Any, Dict, List, Optional

from models.schemas import DateWindow, SafetyQuery
from services.safety.adapters import (SafetyFetcher, collect_all,
                                      default_adapters, default_http_fetch)
from services.safety.policy import SafetyPolicyEngine
from services.skills.base import SkillBase, SkillError

_QUERY_LIST_FIELDS = ("destination_regions", "cities", "route_legs",
                      "transit_countries", "transit_airports",
                      "requested_categories")


def _str_list(raw: Any) -> List[str]:
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def _window(raw: Any) -> Optional[DateWindow]:
    if isinstance(raw, DateWindow):
        return raw
    if not isinstance(raw, dict):
        return None
    try:
        return DateWindow(start=date.fromisoformat(str(raw.get("start"))),
                          end=date.fromisoformat(str(raw.get("end"))))
    except ValueError:
        return None


class SafetyResearchSkill(SkillBase):
    name = "safety_research"
    when_to_use = (
        "to collect official travel advisories, health events, disaster/"
        "weather events and transport alerts for a route; the deterministic "
        "SafetyPolicyEngine — never this skill — computes the status"
    )
    capabilities = frozenset({"network_read"})

    def __init__(self, adapters: Optional[List[Any]] = None,
                 fetch: Optional[SafetyFetcher] = None,
                 engine: Optional[SafetyPolicyEngine] = None,
                 web_intel: Optional[Any] = None,
                 weather_url: Optional[str] = None,
                 transport_url: Optional[str] = None) -> None:
        self._adapters = adapters
        self._fetch: SafetyFetcher = fetch or default_http_fetch
        self._engine = engine or SafetyPolicyEngine()
        self._web_intel = web_intel
        self._weather_url = weather_url
        self._transport_url = transport_url

    def build_query(self, payload: Dict[str, Any]) -> SafetyQuery:
        country = str(payload.get("destination_country") or "").strip()
        if not country:
            raise SkillError("missing_destination",
                             "destination_country is required",
                             recoverable=True)
        kwargs: Dict[str, Any] = {"destination_country": country}
        for field in _QUERY_LIST_FIELDS:
            kwargs[field] = _str_list(payload.get(field))
        kwargs["venue"] = payload.get("venue") or None
        kwargs["travel_window"] = _window(payload.get("travel_window"))
        kwargs["passport_country"] = payload.get("passport_country") or None
        kwargs["residence_country"] = payload.get("residence_country") or None
        kwargs["trip_id"] = payload.get("trip_id") or None
        return SafetyQuery(**kwargs)

    async def run(self, payload: Dict[str, Any],
                  context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        query = self.build_query(payload or {})
        adapters = self._adapters or default_adapters(
            web_intel=self._web_intel, weather_url=self._weather_url,
            transport_url=self._transport_url)
        result = await collect_all(query, adapters, self._fetch)
        evidence = result["evidence"]
        reports = result["reports"]
        assessment = self._engine.assess(query, evidence, reports)
        return {
            "skill": self.name,
            "status": "assessed",
            "assessment": assessment.model_dump(mode="json"),
            "source_reports": [r.model_dump(mode="json") for r in reports],
            "evidence": [e.model_dump(mode="json") for e in evidence],
            "query": query.model_dump(mode="json"),
        }
