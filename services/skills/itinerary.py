"""itinerary skill — §4 S8 (G2 behavior).

Builds the post-booking itinerary through the §15.2 provider chain:
ORGANIZER → AMADEUS → OSM → researched_mock. Flights always stay
source=atlas_real (from the confirmed BookingRecord); external providers
are live data ("live data" chip); the researched-mock file carries an
as-of chip and full provenance (source_url + researched_as_of).

Honesty rules: invalid file entries are DROPPED (never invented), a
corrupt/missing file degrades visibly, and providers_tried records the
chain actually attempted.
"""

import json
import re
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ValidationError

from models.schemas import ItineraryReplacementRequest
from services.skills.base import SkillBase

_DEFAULT_HOTELS_PATH = Path(__file__).resolve().parent.parent.parent \
    / "data" / "mock_hotels_sg.json"

_AIRPORT_TIMEZONES = {
    "SIN": "Asia/Singapore",
    "BKK": "Asia/Bangkok",
    "DMK": "Asia/Bangkok",
    "RGN": "Asia/Yangon",
    "FRA": "Europe/Berlin",
}


def _valid_entry(entry: Any) -> bool:
    """Tolerant schema check — unusable entries are dropped, never invented."""
    return (isinstance(entry, dict)
            and isinstance(entry.get("name"), str) and entry["name"].strip()
            and isinstance(entry.get("type"), str) and entry["type"].strip())


def _flight_label(carrier: Any, flight_no: Any) -> str:
    carrier_text = str(carrier or "").strip()
    number_text = str(flight_no or "").strip()
    # Atlas may return carrier="TR" with flight_no="TR609". Preserve the
    # provider value without displaying the duplicated "TR TR609" label.
    if (carrier_text and len(carrier_text) <= 3 and number_text and
            re.match(rf"^{re.escape(carrier_text)}\s*\d",
                     number_text, re.IGNORECASE)):
        return number_text
    return " ".join(x for x in (carrier_text, number_text) if x)


class ItinerarySkill(SkillBase):
    name = "itinerary"
    when_to_use = (
        "before approval for an honest planned preview, and after booking "
        "confirmation to promote only the provider-confirmed flight; leisure "
        "items carry suggestion/researched-mock provenance"
    )
    capabilities = frozenset({"llm_call"})

    def __init__(self, hotels_path: Optional[Path] = None,
                 organizer: Optional[Callable[[], Awaitable[List[Dict[str, Any]]]]] = None,
                 amadeus: Optional[Callable[[], Awaitable[List[Dict[str, Any]]]]] = None,
                 osm: Optional[Callable[[], Awaitable[List[Dict[str, Any]]]]] = None,
                 allow_mock_fallback: bool = False) -> None:
        self._hotels_path = Path(hotels_path) if hotels_path else _DEFAULT_HOTELS_PATH
        self._providers = [("organizer", organizer), ("amadeus", amadeus),
                           ("osm", osm)]
        self._allow_mock_fallback = allow_mock_fallback or (hotels_path is not None)

    # -- flight items (atlas_real when booked, atlas_sandbox when planned) -------

    @staticmethod
    def _flight_item(booking: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        option = booking.get("option") or {}
        if not option:
            return None
        dep = option.get("dep") if isinstance(option.get("dep"), dict) else {}
        arr = option.get("arr") if isinstance(option.get("arr"), dict) else {}
        carrier = option.get("carrier") or option.get("airline_code") or option.get("airline") or ""
        flight_no = option.get("flight_no") or option.get("flight_number") or "x"
        dep_airport = dep.get("airport") or option.get("origin") or "?"
        arr_airport = arr.get("airport") or option.get("destination") or "?"
        dep_time = dep.get("time") or option.get("departure_time")
        arr_time = arr.get("time") or option.get("arrival_time")
        pnr = booking.get("pnr")
        return {
            "item_id": f"itin-flt-{(flight_no or 'x')[:8]}",
            "name": (f"{_flight_label(carrier, flight_no)} "
                     f"{dep_airport}→{arr_airport}").strip(),
            "kind": "flight",
            "source": "atlas_real" if pnr else "atlas_sandbox",
            "honesty_label": "booked flight (Atlas sandbox record)" if pnr else "planned flight — not booked",
            "price_range_sgd": None,
            "details": {
                "pnr": pnr,
                "dep_time": dep_time,
                "arr_time": arr_time,
                "carrier": carrier,
                "flight_no": flight_no,
                "status": booking.get("status") or ("CONFIRMED" if pnr else "PLANNED"),
            },
            "provenance": {
                "source_url": None,
                "retrieved_date": date.today().isoformat() if pnr else None,
                "researched_as_of": None,
                "degraded": False,
            },
            "booked": bool(pnr),
        }

    @staticmethod
    def _planned_flight_item(option: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not option or not isinstance(option, dict):
            return None
        dep = option.get("dep") if isinstance(option.get("dep"), dict) else {}
        arr = option.get("arr") if isinstance(option.get("arr"), dict) else {}
        carrier = option.get("carrier") or option.get("airline_code") or option.get("airline") or ""
        flight_no = option.get("flight_no") or option.get("flight_number") or "x"
        dep_airport = dep.get("airport") or option.get("origin") or "?"
        arr_airport = arr.get("airport") or option.get("destination") or "?"
        dep_time = dep.get("time") or option.get("departure_time")
        arr_time = arr.get("time") or option.get("arrival_time")

        price_range_sgd = None
        native_price = None
        price_obj = option.get("price")
        if isinstance(price_obj, dict) and price_obj.get("amount") is not None:
            try:
                amt = float(price_obj["amount"])
                currency = str(price_obj.get("currency") or "").upper()
                native_price = {"amount": amt, "currency": currency}
                if currency == "SGD":
                    price_range_sgd = [amt, amt]
            except (ValueError, TypeError):
                pass
        elif option.get("price_usd") is not None:
            try:
                amt = float(option["price_usd"])
                native_price = {"amount": amt, "currency": "USD"}
            except (ValueError, TypeError):
                pass

        return {
            "item_id": f"itin-flt-{(flight_no or 'x')[:8]}",
            "name": (f"{_flight_label(carrier, flight_no)} "
                     f"{dep_airport}→{arr_airport}").strip(),
            "kind": "flight",
            "source": "atlas_sandbox",
            "honesty_label": "planned flight — not booked",
            "price_range_sgd": price_range_sgd,
            "details": {
                "pnr": None,
                "option_id": option.get("id") or option.get("offer_id"),
                "carrier": carrier,
                "flight_no": flight_no,
                "dep_time": dep_time,
                "arr_time": arr_time,
                "status": "PLANNED",
                "price": native_price,
            },
            "provenance": {
                "source_url": option.get("source_url") or f"atlas-sandbox://offers/{option.get('id') or option.get('offer_id') or flight_no}",
                "retrieved_date": date.today().isoformat(),
                "researched_as_of": None,
                "degraded": False,
            },
            "booked": False,
        }

    @classmethod
    def reconcile_flight(cls, itinerary: Dict[str, Any],
                         option: Optional[Dict[str, Any]] = None,
                         booking: Optional[Dict[str, Any]] = None,
                         timezone_name: Optional[str] = None) -> Dict[str, Any]:
        """Reconciles the flight entry in an existing itinerary dict.

        If a confirmed booking is provided, promotes the flight item to booked=True with PNR.
        If an option is provided without confirmed booking, sets the flight item as planned (booked=False).
        Preserves all leisure items (hotels, activities, transport, replacements).
        """
        if not isinstance(itinerary, dict):
            itinerary = {"items": []}
        items = list(itinerary.get("items") or [])

        new_flight = None
        if booking and (booking.get("pnr") or booking.get("option")):
            new_flight = cls._flight_item(booking)
        elif option:
            new_flight = cls._planned_flight_item(option)

        if new_flight is None:
            return itinerary

        flight_idx = None
        for idx, it in enumerate(items):
            if it.get("kind") == "flight":
                flight_idx = idx
                break

        if flight_idx is not None:
            new_flight["item_id"] = items[flight_idx].get("item_id") or new_flight["item_id"]
            items[flight_idx] = new_flight
        else:
            items.insert(0, new_flight)

        tz = timezone_name or itinerary.get("timezone")
        if not tz:
            if booking:
                tz = cls._timezone_for_booking(booking)
            elif option:
                arr = (option.get("arr") or {}).get("airport") or option.get("destination") or ""
                tz = _AIRPORT_TIMEZONES.get(str(arr).upper(), "Asia/Singapore")
            else:
                tz = "Asia/Singapore"

        summary = cls.summarize(items, tz)
        result = dict(itinerary)
        result["items"] = items
        result.update(summary)
        return result

    # -- researched-mock file (tolerant) -------------------------------------------

    def _read_researched_mock(self) -> Dict[str, Any]:
        try:
            raw = json.loads(self._hotels_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — missing/corrupt file degrades honestly
            return {"entries": [], "degraded": True}
        if isinstance(raw, list):
            entries = raw
        elif isinstance(raw, dict):
            entries = []
            for key in ("hotels", "activities", "local_transport", "items"):
                block = raw.get(key)
                if isinstance(block, list):
                    entries.extend(block)
        else:
            return {"entries": [], "degraded": True}
        return {"entries": [e for e in entries if _valid_entry(e)],
                "degraded": False}

    @staticmethod
    def _mock_item(entry: Dict[str, Any]) -> Dict[str, Any]:
        as_of = entry.get("researched_as_of") or ""
        return {
            "name": entry["name"],
            "kind": entry.get("type", "hotel"),
            "source": "researched_mock",
            "honesty_label": f"researched mock — data as of {as_of}" if as_of
                             else "researched mock (unverified date)",
            "price_range_sgd": entry.get("price_range_sgd"),
            "details": {k: v for k, v in entry.items()
                        if k not in ("name", "type", "price_range_sgd",
                                     "source_url", "researched_as_of")},
            "provenance": {"source_url": entry.get("source_url"),
                           "retrieved_date": date.today().isoformat(),
                           "researched_as_of": as_of or None,
                           "degraded": False},
        }

    # -- provider chain (§15.2): organizer → amadeus → osm → researched_mock -------

    @staticmethod
    def _select_plan_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Choose a compact plan, not a sum of mutually exclusive alternatives."""
        limits = {"hotel": 1, "activity": 3, "local_transport": 1}
        counts = {kind: 0 for kind in limits}
        selected: List[Dict[str, Any]] = []
        for entry in entries:
            kind = entry.get("type")
            if kind not in limits or counts[kind] >= limits[kind]:
                continue
            selected.append(entry)
            counts[kind] += 1
        return selected

    async def _enrich(self, providers_tried: List[str],
                      requested_domains: Optional[List[str]] = None,
                      context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        allowed_kinds = None
        if requested_domains is not None:
            allowed_kinds = {
                "activity" if domain == "activities" else domain
                for domain in requested_domains
                if domain in ("hotel", "activities", "local_transport")
            }
            if not allowed_kinds:
                return []

        def requested(entry: Dict[str, Any]) -> bool:
            return allowed_kinds is None or entry.get("type") in allowed_kinds

        for name, provider in self._providers:
            if provider is None:
                continue
            providers_tried.append(name)
            try:
                entries = await provider()
            except Exception:  # noqa: BLE001 — hostile providers degrade, chain moves on
                continue
            valid = self._select_plan_entries([
                e for e in (entries or []) if _valid_entry(e) and requested(e)])
            if valid:
                return [{
                    "name": e["name"], "kind": e.get("type", "hotel"),
                    "source": name, "honesty_label": "live data",
                    "price_range_sgd": e.get("price_range_sgd"),
                    "details": {k: v for k, v in e.items()
                                 if k not in ("name", "type")},
                    "provenance": {"source_url": e.get("source_url"),
                                   "retrieved_date": date.today().isoformat(),
                                   "researched_as_of": None, "degraded": False},
                } for e in valid]

        # In runtime path: no mock fallback. Return empty list if no live/verified provider data won.
        allow_mock = (
            self._allow_mock_fallback
            or (context and (context.get("allow_mock_fallback") or context.get("is_simulation")))
        )
        if allow_mock:
            providers_tried.append("researched_mock")
            mock = self._read_researched_mock()
            selected = self._select_plan_entries(
                [e for e in mock["entries"] if requested(e)])
            if selected:
                return [self._mock_item(e) for e in selected]
        return []

    async def run(self, payload: Dict[str, Any],
                  context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        booking = payload.get("booking")
        if booking is None and context:
            booking = (context.get("flight_book") or {}).get("booking")
        if hasattr(booking, "model_dump"):  # BookingRecord accepted too
            booking = booking.model_dump(mode="json")

        items: List[Dict[str, Any]] = []
        option = None
        if booking and (booking.get("option") or booking.get("pnr")):
            flight = self._flight_item(booking)
            if flight:
                items.append(flight)
        else:
            option = payload.get("option")
            if not option:
                options = payload.get("options")
                if not options and context:
                    options = (context.get("flight_search") or {}).get("options")
                if options and isinstance(options, list) and len(options) > 0:
                    option = options[0]
            if option:
                flight = self._planned_flight_item(option)
                if flight:
                    items.append(flight)

        requested_domains = payload.get("requested_domains")
        if requested_domains is not None and not isinstance(requested_domains, list):
            requested_domains = []
        providers_tried: List[str] = []
        items.extend(await self._enrich(providers_tried, requested_domains, context=context))

        # Assign stable item_ids to all items
        for i, item in enumerate(items):
            if "item_id" not in item:
                item["item_id"] = f"itin-{i:03d}-{item.get('kind', 'item')[:4]}"

        if booking:
            timezone_name = self._timezone_for_booking(booking)
        elif option:
            arr_apt = str(((option.get("arr") or {}).get("airport")) or option.get("destination") or "").upper()
            timezone_name = _AIRPORT_TIMEZONES.get(arr_apt, "Asia/Singapore")
        else:
            timezone_name = "Asia/Singapore"

        return {
            "items": items,
            "providers_tried": providers_tried,
            **self.summarize(items, timezone_name),
        }

    @staticmethod
    def _timezone_for_booking(booking: Dict[str, Any]) -> str:
        option = booking.get("option") or {}
        airport = str(((option.get("arr") or {}).get("airport")) or option.get("destination") or "").upper()
        return _AIRPORT_TIMEZONES.get(airport, "Asia/Singapore")


    @staticmethod
    def _parse_time(value: Any, timezone_name: str) -> Optional[datetime]:
        if not isinstance(value, str) or not value.strip():
            return None
        raw = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(raw)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
            return parsed.astimezone(timezone.utc)
        except (ValueError, ZoneInfoNotFoundError):
            return None

    @classmethod
    def _time_range(cls, item: Dict[str, Any],
                    timezone_name: str) -> tuple[Optional[datetime], Optional[datetime], Any, Any]:
        details = item.get("details") or {}
        if item.get("kind") == "flight":
            raw_start = details.get("dep_time")
            raw_end = details.get("arr_time")
        else:
            raw_start = details.get("start_time")
            raw_end = details.get("end_time")
        return (cls._parse_time(raw_start, timezone_name),
                cls._parse_time(raw_end, timezone_name),
                raw_start, raw_end)

    @classmethod
    def summarize(cls, items: List[Dict[str, Any]],
                  timezone_name: str = "Asia/Singapore") -> Dict[str, Any]:
        by_category: Dict[str, List[float]] = {}
        total_low = 0.0
        total_high = 0.0
        priced_items = 0
        invalid_prices: List[Dict[str, Any]] = []
        for item in items:
            price = item.get("price_range_sgd")
            if price is None:
                continue
            if (not isinstance(price, list) or len(price) != 2
                    or not all(isinstance(v, (int, float)) for v in price)
                    or price[0] < 0 or price[1] < price[0]):
                invalid_prices.append({"item_id": item.get("item_id"),
                                       "reason": "invalid_price_range"})
                continue
            low, high = float(price[0]), float(price[1])
            category = str(item.get("kind") or "other")
            current = by_category.setdefault(category, [0.0, 0.0])
            current[0] += low
            current[1] += high
            total_low += low
            total_high += high
            priced_items += 1

        ranges = []
        invalid_ranges: List[Dict[str, Any]] = []
        for item in items:
            start, end, raw_start, raw_end = cls._time_range(
                item, timezone_name)
            if raw_start is None and raw_end is None:
                continue
            if start is None or end is None or end <= start:
                invalid_ranges.append({
                    "item_id": item.get("item_id"),
                    "reason": "invalid_time_range",
                })
                continue
            ranges.append((start, end, item))

        overlaps: List[Dict[str, Any]] = []
        ranges.sort(key=lambda row: row[0])
        for index, (start, end, item) in enumerate(ranges):
            for other_start, other_end, other in ranges[index + 1:]:
                if other_start >= end:
                    break
                if start < other_end and end > other_start:
                    overlaps.append({
                        "item_ids": [item.get("item_id"), other.get("item_id")],
                        "reason": "schedule_overlap",
                    })

        transfer_warnings: List[Dict[str, Any]] = []
        flights = [r for r in ranges if r[2].get("kind") == "flight"]
        non_flights = [r for r in ranges if r[2].get("kind") != "flight"]
        for _, arrival, flight in flights:
            future = [r for r in non_flights if r[0] >= arrival]
            if future:
                next_start, _, next_item = min(future, key=lambda row: row[0])
                minutes = int((next_start - arrival).total_seconds() / 60)
                if minutes < 90:
                    transfer_warnings.append({
                        "from_item_id": flight.get("item_id"),
                        "to_item_id": next_item.get("item_id"),
                        "available_minutes": minutes,
                        "reason": "insufficient_airport_transfer_time",
                    })

        check_in_warnings: List[Dict[str, Any]] = []
        latest_arrival = max((end for _, end, item in flights), default=None)
        if latest_arrival is not None:
            for item in items:
                if item.get("kind") != "hotel":
                    continue
                latest_raw = (item.get("details") or {}).get(
                    "latest_check_in_time")
                latest_check_in = cls._parse_time(latest_raw, timezone_name)
                if latest_raw and (latest_check_in is None
                                   or latest_arrival > latest_check_in):
                    check_in_warnings.append({
                        "item_id": item.get("item_id"),
                        "reason": "arrival_after_latest_check_in",
                    })

        valid = not (invalid_ranges or invalid_prices or overlaps
                     or transfer_warnings or check_in_warnings)
        return {
            "count": len(items),
            "timezone": timezone_name,
            "budget": {
                "currency": "SGD",
                "by_category": by_category,
                "total_range_sgd": [total_low, total_high],
                "priced_items": priced_items,
                "unpriced_items": len(items) - priced_items,
            },
            "validation": {
                "valid": valid,
                "overlaps": overlaps,
                "invalid_ranges": invalid_ranges,
                "invalid_prices": invalid_prices,
                "transfer_warnings": transfer_warnings,
                "check_in_warnings": check_in_warnings,
            },
        }

    # -- replace-one-section (§15.2, F16) ----------------------------------------

    @classmethod
    def replace_section(cls, items: List[Dict[str, Any]],
                        target_id: str,
                        replacement: Dict[str, Any],
                        timezone_name: str = "Asia/Singapore") -> Dict[str, Any]:
        """Replace a single non-booked itinerary section by item_id.

        Rules:
        - Booked flights cannot be replaced through this path (requires a
          new explicit booking flow).
        - Unrelated sections are preserved byte-equivalently.
        - Replacement carries provenance and honesty labels.
        - Schedule overlaps with other items are flagged.
        - Returns the updated items list with before/after metadata.
        """
        target_idx = None
        for i, item in enumerate(items):
            if item.get("item_id") == target_id:
                target_idx = i
                break

        if target_idx is None:
            return {"error": "unknown_section",
                    "message": f"section '{target_id}' not found in itinerary",
                    "recoverable": True}

        target_item = items[target_idx]

        # Every flight change must go through option selection so the itinerary,
        # approval snapshot, fare verification, and provider request stay aligned.
        if target_item.get("kind") == "flight" and not target_item.get("booked"):
            return {
                "error": "flight_section_requires_selection",
                "message": "planned flights must be changed through the flight "
                           "option selector, not the leisure-section editor",
                "recoverable": True,
                "hint": "return to Choose your options and select another "
                        "Atlas Sandbox offer",
            }

        # Booked flights require a new explicit booking flow
        if target_item.get("booked") or (
                target_item.get("kind") == "flight"
                and target_item.get("source") == "atlas_real"):
            return {"error": "booked_section_immutable",
                    "message": "booked flight sections cannot be replaced through "
                               "this path — start a new booking flow or use the "
                               "recovery mechanism",
                    "recoverable": True,
                    "hint": "POST /api/trips/{id}/plan to start a new booking, "
                            "or use the recovery approval if disrupted"}

        if hasattr(replacement, "model_dump"):
            replacement = replacement.model_dump(mode="json")
        if not isinstance(replacement, dict):
            return {"error": "invalid_replacement",
                    "message": "replacement must contain a name and section kind",
                    "recoverable": True}
        try:
            request = ItineraryReplacementRequest.model_validate(replacement)
        except ValidationError as exc:
            first = exc.errors()[0] if exc.errors() else {}
            location = ".".join(map(str, first.get("loc") or [])) or "request"
            return {"error": "invalid_replacement",
                    "message": f"invalid replacement field: {location}",
                    "recoverable": True}
        normalized = request.model_dump(mode="json")

        # Build the replacement item with provenance
        new_item = {
            "item_id": target_id,  # preserve the section ID
            "name": normalized["name"],
            "kind": normalized["kind"],
            "source": "user_replacement",
            "honesty_label": "user-replaced section (not booked)",
            "price_range_sgd": normalized.get("price_range_sgd"),
            "details": normalized.get("details", {}),
            "provenance": {
                "source_url": normalized.get("source_url"),
                "retrieved_date": date.today().isoformat(),
                "researched_as_of": None,
                "degraded": False,
            },
            "booked": False,
        }

        # Preserve unrelated items exactly, replace only the target
        before = deepcopy(target_item)
        updated_items = list(items)
        updated_items[target_idx] = new_item
        summary = cls.summarize(updated_items, timezone_name)

        return {
            "items": updated_items,
            "replaced": {
                "item_id": target_id,
                "before": before,
                "after": new_item,
            },
            **summary,
        }
