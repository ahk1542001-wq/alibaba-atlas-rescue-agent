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
from html import unescape
from typing import Any, Dict, List, Optional

from models.schemas import RequestedServices
from services.atlas_client import AtlasClient
from services.skills.flight_search import normalize_offer
from services.skills.location_resolve import KNOWN_CITY_AIRPORTS

_LEISURE_DOMAINS = ("hotel", "activities", "local_transport")


def _destination_label(value: Any) -> str:
    raw = str(value or "").strip()
    upper = raw.upper()
    for city, airports in KNOWN_CITY_AIRPORTS.items():
        if upper == city or any(upper == airport.get("code") for airport in airports):
            return city.title()
    return raw


def _citation_relevant(domain: str, citation: Dict[str, Any]) -> bool:
    text = " ".join(str(citation.get(key) or "") for key in (
        "title", "snippet_max280", "url")).lower()
    terms = {
        "hotel": ("hotel", "accommodation", "places to stay", "resort", "hostel"),
        "activities": ("things to do", "attraction", "tourism", "visit ", "activities"),
        "local_transport": ("transport", "getting around", "public transit", "metro", "bus", "taxi"),
    }
    return any(term in text for term in terms[domain])


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
            destination = _destination_label(params.get("destination"))
            query_templates = {
                "hotel": "hotels in {destination} official hotel websites",
                "activities": "{destination} official tourism things to do",
                "local_transport": "{destination} official public transport visitor guide",
            }
            intel = await self._web_intel.fetch(
                query_templates[domain].format(
                    destination=destination or "the destination")) \
                if self._web_intel is not None else {
                    "provider": "none", "degraded": True,
                    "offline": True, "citations": [],
                }
            citations = [
                citation for citation in (intel.get("citations") or [])
                if isinstance(citation, dict)
                and citation.get("url") and citation.get("title")
                and citation.get("retrieved_date")
                and _citation_relevant(domain, citation)
            ]
            limits = {"hotel": 1, "activities": 3, "local_transport": 1}
            kind = "activity" if domain == "activities" else domain
            items = []
            for citation in citations[:limits[domain]]:
                items.append({
                    "name": unescape(str(citation["title"]))[:160],
                    "kind": kind,
                    "source": "web_research",
                    "honesty_label": (
                        "researched suggestion — verify before booking"),
                    "price_range_sgd": None,
                    "details": {
                        "summary": unescape(str(
                            citation.get("snippet_max280") or ""))[:280],
                    },
                    "provenance": {
                        "source_url": citation["url"],
                        "retrieved_date": citation["retrieved_date"],
                        "researched_as_of": None,
                        "degraded": False,
                    },
                    "booked": False,
                })
            degraded = bool(intel.get("degraded")) or not items
            return {
                "domain": domain,
                "provenance": intel.get("provider") or "web_intel",
                "source_url": items[0]["provenance"]["source_url"]
                if items else None,
                "retrieved_date": today,
                "freshness_state": "fresh" if not degraded else "unknown",
                "degraded": degraded,
                "data": {
                    "destination": destination,
                    "items": items,
                    "note": None if items else (
                        "No source-backed suggestions are currently available."),
                },
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
