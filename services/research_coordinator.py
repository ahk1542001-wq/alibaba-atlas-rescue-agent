"""Bounded ResearchCoordinator — owner correction (C).

Decision: separate module (services/research_coordinator.py) so the trip
executor stays generic (§3.1) while research policy (what to research,
provenance stamping, re-verification before booking) lives in one bounded
place — fewest new concepts, logged in DECISIONS.tsv.

Invariants under test:
- plan_research derives domains STRICTLY from RequestedServices: flight-only
  intents never mount hotel/activities/local_transport researchers; visa is
  added as a safety dep for international bookings even when not requested.
- Every result is a ResearchRecord-shaped dict: provenance + source_url +
  retrieved_date + freshness_state + degraded (never silently fresh).
- refresh_and_verify RESEARCHES (search) then REVERIFIES (verify_fare)
  immediately before booking — never book on stale search data.
"""

from datetime import date
from typing import Any, Dict, List, Optional

from models.schemas import RequestedServices
from services.atlas_client import AtlasClient
from services.skills.flight_search import normalize_offer

_LEISURE_DOMAINS = ("hotel", "activities", "local_transport")


class ResearchCoordinator:
    def __init__(self, atlas: Optional[Any] = None,
                 web_intel: Optional[Any] = None) -> None:
        self._atlas = atlas or AtlasClient()
        self._web_intel = web_intel
        self._last_flight_params: Dict[str, Any] = {}

    # -- planning (intent-first, owner correction B) --------------------------------

    def plan_research(self, requested: RequestedServices,
                      international: bool, booking: bool) -> List[str]:
        """Domains strictly from requested_services (+ mandatory visa safety)."""
        if isinstance(requested, dict):
            requested = RequestedServices(**requested)
        domains: List[str] = []
        if requested.flight_search == "requested":
            domains.append("flight")
        # safety dep: cross-border booking ALWAYS gets a visa check
        if requested.visa_check == "requested" or (international and booking):
            domains.append("visa")
        for domain in _LEISURE_DOMAINS:
            if getattr(requested, domain) == "requested":
                domains.append(domain)
        return domains

    # -- execution ---------------------------------------------------------------------

    async def run_domain(self, domain: str,
                         params: Dict[str, Any]) -> Dict[str, Any]:
        today = date.today().isoformat()
        if domain == "flight":
            origin = str(params.get("origin") or "")
            destination = str(params.get("destination") or "")
            travel_date = str(params.get("date") or "")
            self._last_flight_params = {"origin": origin,
                                        "destination": destination,
                                        "date": travel_date}
            offers = await self._atlas.search_flights(
                origin, destination, travel_date,
                passengers=int(params.get("passengers") or 1))
            return {
                "domain": "flight",
                "provenance": "atlas_sandbox",
                "source_url": f"atlas-sandbox://search/{origin}-{destination}",
                "retrieved_date": today,
                "freshness_state": "fresh",
                "degraded": False,
                "data": {"options": [normalize_offer(o) for o in offers]},
            }
        if domain == "visa":
            # visa freshness is owned by the visa_check skill; coordinator
            # only records the delegation honestly
            return {
                "domain": "visa",
                "provenance": "visa_check_skill",
                "source_url": None,
                "retrieved_date": today,
                "freshness_state": "unknown",
                "degraded": False,
                "data": {"delegate": "services.skills.visa_check"},
            }
        if domain in _LEISURE_DOMAINS:
            return {
                "domain": domain,
                "provenance": "researched_mock",
                "source_url": params.get("source_url"),
                "retrieved_date": today,
                "freshness_state": "unknown",  # as-of dated; never claimed fresh
                "degraded": self._web_intel is None,
                "data": {"destination": params.get("destination")},
            }
        return {
            "domain": domain,
            "provenance": "none",
            "source_url": None,
            "retrieved_date": today,
            "freshness_state": "unknown",
            "degraded": True,
            "data": {"error": f"unknown research domain '{domain}'"},
        }

    # -- owner correction (C): refresh + reverify immediately before booking ----------

    async def refresh_and_verify(self, offer_id: str,
                                 origin: Optional[str] = None,
                                 destination: Optional[str] = None,
                                 travel_date: Optional[str] = None) -> Dict[str, Any]:
        params = dict(self._last_flight_params)
        if origin:
            params["origin"] = origin
        if destination:
            params["destination"] = destination
        if travel_date:
            params["date"] = travel_date

        # REFRESH: re-search so the fare is priced against current inventory
        await self._atlas.search_flights(
            params.get("origin", ""), params.get("destination", ""),
            params.get("date", ""), passengers=int(params.get("passengers") or 1))
        # REVERIFY: booking may only proceed on a verified fare
        verification = await self._atlas.verify_fare(offer_id)
        return {
            "offer_id": offer_id,
            "verified": bool(verification.get("verified")),
            "fare_lock_expires_in_seconds":
                verification.get("fare_lock_expires_in_seconds"),
            "retrieved_date": date.today().isoformat(),
            "freshness_state": "fresh",
            "provenance": "atlas_sandbox",
        }
