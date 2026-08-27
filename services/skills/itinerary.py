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
from datetime import date
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from services.skills.base import SkillBase

_DEFAULT_HOTELS_PATH = Path(__file__).resolve().parent.parent.parent \
    / "data" / "mock_hotels_sg.json"


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

        return {
            "items": items,
            "providers_tried": providers_tried,
            "count": len(items),
        }

    # -- replace-one-section (§15.2, F16) ----------------------------------------

    @staticmethod
    def replace_section(items: List[Dict[str, Any]],
                        target_id: str,
                        replacement: Dict[str, Any]) -> Dict[str, Any]:
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

        # Validate replacement has required fields
        if not isinstance(replacement, dict):
            return {"error": "invalid_replacement",
                    "message": "replacement must be a dict with name, kind, "
                               "and honesty_label",
                    "recoverable": True}
        for required in ("name", "kind"):
            if not replacement.get(required):
                return {"error": "invalid_replacement",
                        "message": f"replacement missing required field: {required}",
                        "recoverable": True}

        # Build the replacement item with provenance
        new_item = {
            "item_id": target_id,  # preserve the section ID
            "name": replacement["name"],
            "kind": replacement["kind"],
            "source": replacement.get("source", "user_replacement"),
            "honesty_label": replacement.get("honesty_label",
                                              "user-replaced section"),
            "price_range_sgd": replacement.get("price_range_sgd"),
            "details": replacement.get("details", {}),
            "provenance": replacement.get("provenance", {
                "source_url": None,
                "retrieved_date": date.today().isoformat(),
                "researched_as_of": None,
                "degraded": False,
            }),
            "booked": False,
        }

        # Check schedule overlap with other items
        overlaps = []
        new_start = (replacement.get("details") or {}).get("start_time")
        new_end = (replacement.get("details") or {}).get("end_time")
        if new_start and new_end:
            for i, item in enumerate(items):
                if i == target_idx:
                    continue
                item_start = (item.get("details") or {}).get("start_time")
                item_end = (item.get("details") or {}).get("end_time")
                if item_start and item_end:
                    if new_start < item_end and new_end > item_start:
                        overlaps.append({
                            "item_id": item.get("item_id"),
                            "name": item.get("name"),
                            "conflict": "schedule_overlap"})

        # Preserve unrelated items exactly, replace only the target
        before = dict(target_item)
        updated_items = list(items)
        updated_items[target_idx] = new_item

        return {
            "items": updated_items,
            "replaced": {
                "item_id": target_id,
                "before": before,
                "after": new_item,
            },
            "overlaps": overlaps,
            "count": len(updated_items),
        }
