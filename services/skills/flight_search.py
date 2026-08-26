"""flight_search skill — §4 S4 (G2 behavior).

Wraps atlas_client.search_flights (frozen service, import-only) and
normalizes offers into §5 FlightOption cards. Provenance is ALWAYS flagged
sandbox — search results never masquerade as live airline inventory.
Every result carries research provenance (retrieved_date) per owner
correction (C).
"""

from datetime import date
from typing import Any, Dict, List, Optional

from models.schemas import FlightEndpoint, FlightOption, Money
from services.atlas_client import AtlasClient
from services.skills.base import SkillBase, SkillError


def normalize_offer(offer: Dict[str, Any]) -> Dict[str, Any]:
    """Map one Atlas sandbox offer onto the §5 FlightOption shape."""
    dep_time = str(offer.get("departure_time") or "")
    arr_time = str(offer.get("arrival_time") or "")
    option = FlightOption(
        id=str(offer.get("offer_id") or ""),
        carrier=str(offer.get("airline_code") or offer.get("airline") or ""),
        flight_no=str(offer.get("flight_number") or ""),
        dep=FlightEndpoint(airport=str(offer.get("origin") or ""), time=dep_time),
        arr=FlightEndpoint(airport=str(offer.get("destination") or ""),
                           time=arr_time),
        duration_min=int(offer.get("duration_minutes") or 0),
        price=Money(amount=float(offer.get("price_usd") or 0.0),
                    currency=str(offer.get("currency") or "USD")),
        sandbox_provenance=True,
    )
    return option.model_dump(mode="json")


class FlightSearchSkill(SkillBase):
    name = "flight_search"
    when_to_use = (
        "when the TripGoal carries route and dates; searches the Atlas sandbox "
        "and returns ranked FlightOption cards (never canned arrays)"
    )
    capabilities = frozenset({"atlas_call", "network_read"})

    def __init__(self, atlas: Optional[Any] = None) -> None:
        self._atlas = atlas or AtlasClient()

    async def run(self, payload: Dict[str, Any],
                  context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        origin = str(payload.get("origin") or "").strip().upper()
        destination = str(payload.get("destination") or "").strip().upper()
        if not origin or not destination:
            raise SkillError("missing_route",
                             "flight search requires origin and destination",
                             recoverable=True)
        travel_date = payload.get("date") or ""
        if hasattr(travel_date, "isoformat"):
            travel_date = travel_date.isoformat()
        passengers = int(payload.get("passengers") or 1)

        offers = await self._atlas.search_flights(
            origin, destination, str(travel_date), passengers=passengers)
        options: List[Dict[str, Any]] = [normalize_offer(o) for o in offers]
        # rank: shortest duration first, price as tiebreaker (S4 procedure)
        options.sort(key=lambda o: (o["duration_min"], o["price"]["amount"]))
        return {
            "options": options,
            "provenance": "sandbox",
            "retrieved_date": date.today().isoformat(),
            "source_url": f"atlas-sandbox://search/{origin}-{destination}",
            "freshness_state": "fresh",
            "count": len(options),
        }
