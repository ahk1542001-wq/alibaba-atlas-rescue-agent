"""flight_book skill — §4 S5 (G2 behavior).

Wraps atlas_client.verify_fare + create_booking_order (frozen service,
import-only). Owner correction (C) enforced here:

- fares are REFRESHED and REVERIFIED (verify_fare) IMMEDIATELY before the
  booking order — never booked on stale search data;
- idempotency map option_id -> PNR: a retry returns the same PNR and never
  double-books;
- international bookings are REFUSED with a recoverable error when the
  visa/entry data in context is missing, stale, degraded, or unverified —
  never silently permitted.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from models.schemas import BookingRecord, FlightOption
from services.atlas_client import AtlasClient
from services.rights_engine import airports_to_countries
from services.skills.base import SkillBase, SkillError


def _is_international(origin: str, destination: str) -> bool:
    if not origin or not destination:
        return False
    o, d, _ = airports_to_countries(origin, destination)
    return bool(o and d and o != d)


class FlightBookSkill(SkillBase):
    name = "flight_book"
    when_to_use = (
        "only after ApprovalGate resolves approve; books the chosen FlightOption "
        "through the Atlas sandbox and returns a BookingRecord (idempotent retry)"
    )
    capabilities = frozenset({"atlas_call", "approval_required"})

    def __init__(self, atlas: Optional[Any] = None) -> None:
        self._atlas = atlas or AtlasClient()
        self._booked: Dict[str, Dict[str, Any]] = {}  # option_id -> result

    async def run(self, payload: Dict[str, Any],
                  context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        option_id = str(payload.get("option_id") or "")
        if not option_id:
            raise SkillError("missing_option",
                             "flight booking requires option_id", recoverable=True)

        # idempotent retry: same option_id -> same PNR, zero extra sandbox calls
        if option_id in self._booked:
            replay = dict(self._booked[option_id])
            replay["idempotent_replay"] = True
            return replay

        origin = str(payload.get("origin") or "").upper()
        destination = str(payload.get("destination") or "").upper()
        context = context or {}

        # --- safety gate (C): stale/unverified visa data BLOCKS booking -----
        if _is_international(origin, destination):
            visa = context.get("visa_check")
            if not visa:
                raise SkillError(
                    "visa_check_missing",
                    "international booking refused: no visa/entry check ran "
                    "for this route", recoverable=True)
            freshness = visa.get("freshness_state", "unknown")
            if visa.get("degraded") or visa.get("baseline_only") \
                    or freshness in ("stale", "unknown"):
                raise SkillError(
                    "visa_data_stale_or_unverified",
                    "international booking refused: visa/entry data is "
                    f"{freshness}{'/degraded' if visa.get('degraded') else ''} "
                    "— refresh web-intel citations before booking",
                    recoverable=True)

        # --- refresh + reverify immediately before ordering (C) -------------
        verification = await self._atlas.verify_fare(option_id)
        if not verification.get("verified"):
            raise SkillError("fare_unverified",
                             f"fare '{option_id}' failed re-verification; "
                             "booking refused", recoverable=True)

        passenger = payload.get("passenger") or {}
        order = await self._atlas.create_booking_order(
            option_id,
            {"name": passenger.get("name", ""),
             "price_usd": ((payload.get("option") or {}).get("price") or {})
                          .get("amount")},
        )

        option_dump = payload.get("option")
        option = FlightOption(**option_dump) if option_dump else None
        record = BookingRecord(
            pnr=order["pnr"],
            option=option,
            status=order.get("status", "CONFIRMED"),
            booked_at=order.get("booking_timestamp")
            or datetime.now(timezone.utc).isoformat(),
            monitor_armed=True,
        ) if option else None

        result = {
            "pnr": order["pnr"],
            "order_id": order.get("order_id"),
            "status": order.get("status", "CONFIRMED"),
            "booking": record.model_dump(mode="json") if record else None,
            "fare_verified_at": verification.get("verified_at"),
            "monitor_armed": True,
            "idempotent_replay": False,
            "provenance": "sandbox",
        }
        self._booked[option_id] = result
        return result
