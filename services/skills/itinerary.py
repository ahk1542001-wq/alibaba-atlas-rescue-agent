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


class ItinerarySkill(SkillBase):
    name = "itinerary"
    when_to_use = (
        "after booking confirmation; builds itinerary items where flights stay "
        "atlas_real and hotels/activities carry suggestion/researched-mock chips"
    )
    capabilities = frozenset({"llm_call"})

    def __init__(self, hotels_path: Optional[Path] = None,
                 organizer: Optional[Callable[[], Awaitable[List[Dict[str, Any]]]]] = None,
                 amadeus: Optional[Callable[[], Awaitable[List[Dict[str, Any]]]]] = None,
                 osm: Optional[Callable[[], Awaitable[List[Dict[str, Any]]]]] = None) -> None:
        self._hotels_path = Path(hotels_path) if hotels_path else _DEFAULT_HOTELS_PATH
        self._providers = [("organizer", organizer), ("amadeus", amadeus),
                           ("osm", osm)]

    # -- flight item (always atlas_real) -----------------------------------------

    @staticmethod
    def _flight_item(booking: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        option = booking.get("option") or {}
        if not option:
            return None
        dep = option.get("dep") or {}
        arr = option.get("arr") or {}
        return {
            "item_id": f"itin-flt-{(option.get('flight_no') or 'x')[:8]}",
            "name": f"{option.get('carrier', '')} {option.get('flight_no', '')} "
                    f"{dep.get('airport', '?')}→{arr.get('airport', '?')}".strip(),
            "kind": "flight",
            "source": "atlas_real",
            "honesty_label": "booked flight (Atlas sandbox record)",
            "price_range_sgd": None,
            "details": {"pnr": booking.get("pnr"),
                        "dep_time": dep.get("time"), "arr_time": arr.get("time"),
                        "status": booking.get("status")},
            "provenance": {"source_url": None, "retrieved_date": None,
                           "researched_as_of": None, "degraded": False},
            "booked": True,
        }

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

    async def _enrich(self, providers_tried: List[str]) -> List[Dict[str, Any]]:
        for name, provider in self._providers:
            if provider is None:
                continue
            providers_tried.append(name)
            try:
                entries = await provider()
            except Exception:  # noqa: BLE001 — hostile providers degrade, chain moves on
                continue
            valid = [e for e in (entries or []) if _valid_entry(e)]
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

        # researched-mock fallback — always attempted when nothing live won
        providers_tried.append("researched_mock")
        mock = self._read_researched_mock()
        return [self._mock_item(e) for e in mock["entries"]]

    async def run(self, payload: Dict[str, Any],
                  context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        booking = payload.get("booking") or {}
        if hasattr(booking, "model_dump"):  # BookingRecord accepted too
            booking = booking.model_dump(mode="json")

        items: List[Dict[str, Any]] = []
        flight = self._flight_item(booking)
        if flight:
            items.append(flight)

        providers_tried: List[str] = []
        items.extend(await self._enrich(providers_tried))

        # Assign stable item_ids to all items
        for i, item in enumerate(items):
            if "item_id" not in item:
                item["item_id"] = f"itin-{i:03d}-{item.get('kind', 'item')[:4]}"

        timezone_name = self._timezone_for_booking(booking)
        return {
            "items": items,
            "providers_tried": providers_tried,
            **self.summarize(items, timezone_name),
        }

    @staticmethod
    def _timezone_for_booking(booking: Dict[str, Any]) -> str:
        option = booking.get("option") or {}
        airport = str(((option.get("arr") or {}).get("airport")) or "").upper()
        return _AIRPORT_TIMEZONES.get(airport, "UTC")

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
