"""flight_search skill — §4 S4 (G2 behavior).

Wraps atlas_client.search_flights (frozen service, import-only) and
normalizes offers into §5 FlightOption cards. Provenance is ALWAYS flagged
sandbox — search results never masquerade as live airline inventory.
Every result carries research provenance (retrieved_date) per owner
correction (C).
"""

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from models.schemas import FlightEndpoint, FlightOption, Money
from services.atlas_client import AtlasClient, AtlasProviderError, AtlasSandboxUnavailableError
from services.skills.base import SkillBase, SkillError


def normalize_offer(offer: Dict[str, Any],
                    passengers: Optional[int] = None) -> Dict[str, Any]:
    """Map one Atlas sandbox offer onto the §5 FlightOption shape."""
    dep_time = str(offer.get("departure_time") or "")
    arr_time = str(offer.get("arrival_time") or "")
    passenger_count = max(1, int(passengers or offer.get("passenger_count") or 1))
    currency = str(offer.get("currency") or "USD")
    amount = offer.get("price_amount")
    if amount is None and currency != "USD":
        amount = offer.get("price_converted")
    if amount is None:
        amount = offer.get("price_usd")
    raw_amount = float(amount or 0.0)
    provider_total = (
        offer.get("price_scope") == "trip_total"
        or offer.get("price_is_total") is True
    )
    total_amount = raw_amount if provider_total else raw_amount * passenger_count
    per_passenger_amount = (
        raw_amount / passenger_count if provider_total else raw_amount
    )
    option = FlightOption(
        id=str(offer.get("offer_id") or ""),
        search_id=(str(offer.get("search_id"))
                   if offer.get("search_id") is not None else None),
        carrier=str(offer.get("airline_code") or offer.get("airline") or ""),
        flight_no=str(offer.get("flight_number") or ""),
        dep=FlightEndpoint(airport=str(offer.get("origin") or ""), time=dep_time),
        arr=FlightEndpoint(airport=str(offer.get("destination") or ""),
                           time=arr_time),
        duration_min=int(offer.get("duration_minutes") or 0),
        price=Money(amount=total_amount, currency=currency),
        price_per_passenger=Money(amount=per_passenger_amount,
                                  currency=currency),
        passenger_count=passenger_count,
        price_status=str(offer.get("price_status") or "unknown"),
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
        travel_date = payload.get("date") or payload.get("date_window") or ""
        passengers = int(payload.get("passengers") or 1)

        dates_to_query: List[str] = []
        date_window_truncated = False
        if isinstance(travel_date, dict):
            start_str = travel_date.get("start")
            end_str = travel_date.get("end")
            if start_str and end_str:
                try:
                    s_dt = date.fromisoformat(str(start_str))
                    e_dt = date.fromisoformat(str(end_str))
                    delta = (e_dt - s_dt).days
                    if delta < 0:
                        s_dt, e_dt = e_dt, s_dt
                        delta = -delta
                    # Bounded range: cap at 7 days max for safety
                    max_days = min(delta, 7)
                    date_window_truncated = delta > 7
                    dates_to_query = [(s_dt + timedelta(days=i)).isoformat() for i in range(max_days + 1)]
                except Exception:
                    dates_to_query = [str(start_str)]
            elif start_str:
                dates_to_query = [str(start_str)]
        elif isinstance(travel_date, (list, tuple)):
            date_window_truncated = len(travel_date) > 8
            dates_to_query = [str(d) for d in travel_date[:8]]
        elif travel_date:
            dates_to_query = [travel_date.isoformat() if hasattr(travel_date, "isoformat") else str(travel_date)]
        else:
            dates_to_query = [""]

        offers: List[Dict[str, Any]] = []
        errors: List[Exception] = []
        failed_dates: List[str] = []
        for d in dates_to_query:
            try:
                res = await self._atlas.search_flights(
                    origin, destination, d, passengers=passengers)
                if res and isinstance(res, list):
                    offers.extend(res)
            except AtlasProviderError as exc:
                errors.append(exc)
                failed_dates.append(d)
            except Exception as exc:
                errors.append(exc)
                failed_dates.append(d)

        if not offers and errors:
            err = errors[0]
            err_code = (
                "atlas_sandbox_unavailable"
                if isinstance(err, AtlasSandboxUnavailableError)
                or getattr(err, "code", "") == "ATLAS_REQUEST_FAILED"
                else "provider_failure"
            )
            raise SkillError(
                err_code,
                "Atlas Sandbox flight search is temporarily unavailable; "
                "retry the search without changing your trip details.",
                recoverable=True,
            ) from err

        options: List[Dict[str, Any]] = []
        filtered_mismatched_routes = 0
        seen_ids = set()
        for offer in offers:
            option = normalize_offer(offer, passengers=passengers)
            if option["id"] in seen_ids:
                continue
            seen_ids.add(option["id"])
            if (option["dep"]["airport"].strip().upper() != origin or
                    option["arr"]["airport"].strip().upper() != destination):
                filtered_mismatched_routes += 1
                continue
            options.append(option)

        # rank: shortest duration first, grouped by currency, then price as tiebreaker (S4 procedure)
        # Prevents numeric cross-ranking of different currencies (e.g. 6800 THB vs 200 USD)
        options.sort(key=lambda o: (o["duration_min"], o["price"]["currency"], o["price"]["amount"]))

        # Honesty (G4-DA-fix F5): report the requested date and LABEL any
        # near-term substitution — the sandbox clamps same-day/past windows,
        # and the returned options must never be presented silently as the
        # requested window.
        requested_date = str(travel_date.get("start") if isinstance(travel_date, dict) else travel_date) or None
        date_note = None
        if requested_date and options and all(
                not str(o["dep"]["time"]).startswith(str(d))
                for o in options for d in dates_to_query if d):
            returned = sorted({str(o["dep"]["time"])[:10]
                                for o in options})
            date_note = (
                f"requested {requested_date}; the Atlas sandbox returned "
                f"near-term dates ({', '.join(returned)}) — the sandbox "
                "clamps same-day/past windows and the substitution is shown "
                "as-is, never relabeled")
        return {
            "options": options,
            "provenance": "sandbox",
            "retrieved_date": date.today().isoformat(),
            "source_url": f"atlas-sandbox://search/{origin}-{destination}",
            "freshness_state": "fresh",
            "count": len(options),
            "filtered_mismatched_routes": filtered_mismatched_routes,
            "requested_date": requested_date,
            "date_note": date_note,
            "searched_dates": list(dates_to_query),
            "failed_dates": failed_dates,
            "partial_failure": bool(failed_dates and options),
            "date_window_truncated": date_window_truncated,
        }
