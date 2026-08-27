"""flight_book skill — §4 S5 (G2 behavior).

Wraps atlas_client.verify_fare + create_booking_order (frozen service,
import-only). Owner correction (C) enforced here:

- the deterministic SAFETY gate (Task #13) runs FIRST, ahead of every
  other gate, whenever the orchestrator injects context["safety_check"]:
  do_not_travel BLOCKS booking outright (no override — user approval never
  makes the risk go away), reconsider_travel halts until a SEPARATE risk
  acknowledgement exists, unable_to_verify halts until fresh verification;
- fares are REFRESHED and REVERIFIED (verify_fare) IMMEDIATELY before the
  booking order — never booked on stale search data;
- idempotency map (trip_id, option_id) -> PNR: the lookup runs AFTER every
  safety gate (visa freshness, passport known, no baseline block, fare
  re-verification), so a replay can never skip a gate, and the key is scoped
  per trip — another trip reusing an option_id books its own PNR instead of
  replaying a foreign one (G2-DA fix);
- international bookings are REFUSED with a recoverable error when the
  visa/entry data in context is missing, stale, degraded, or unverified —
  never silently permitted;
- unknown passports (passport_unknown) and baseline-blocked routes
  (visa_blocked, e.g. BLOCKED_RISK hubs) are refused outright — a blocked
  route has NO user override.
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
        # (trip_id, option_id) -> result; per-trip scoping means cross-trip
        # option reuse can never replay a foreign trip's PNR (G2-DA fix)
        self._booked: Dict[tuple, Dict[str, Any]] = {}

    async def run(self, payload: Dict[str, Any],
                  context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        option_id = str(payload.get("option_id") or "")
        if not option_id:
            raise SkillError("missing_option",
                             "flight booking requires option_id", recoverable=True)

        origin = str(payload.get("origin") or "").upper()
        destination = str(payload.get("destination") or "").upper()
        context = context or {}
        trip_id = str(payload.get("trip_id") or context.get("trip_id") or "")

        # --- SAFETY GATE (Task #13): deterministic policy-engine status ---
        # runs BEFORE every other gate; only active when the orchestrator
        # injects context["safety_check"] (frozen harnesses stay unaffected).
        safety = context.get("safety_check")
        if isinstance(safety, dict):
            status = str(safety.get("trip_policy_status") or "")
            if status == "do_not_travel":
                raise SkillError(
                    "safety_do_not_travel",
                    "Booking blocked: an official do-not-travel advisory "
                    "applies to this destination or region. Approval does "
                    "not remove the risk and there is no override. "
                    "Authority: "
                    f"{safety.get('authority') or 'official authority'}"
                    f" (updated {safety.get('updated_at') or 'date unknown'})."
                    " Consider the safer alternatives shown on the safety "
                    "card.", recoverable=False)
            if status == "reconsider_travel" \
                    and not safety.get("risk_acknowledged"):
                raise SkillError(
                    "safety_acknowledgement_required",
                    "Booking paused: official advice says reconsider travel. "
                    "A separate, explicit risk acknowledgement is required "
                    "before booking approval. Acknowledging this warning "
                    "does not remove the risk.", recoverable=True)
            if status == "unable_to_verify" \
                    and not safety.get("verification_retried"):
                unverified = ", ".join(
                    safety.get("unverified_sources") or []) \
                    or "official sources unavailable"
                raise SkillError(
                    "safety_unverified",
                    "Booking paused: the destination's status could not be "
                    f"verified (unverified: {unverified}). Fresh "
                    "verification is required before this safety-critical "
                    "booking decision.", recoverable=True)

        # --- safety gates (C) run BEFORE any idempotency replay ---------------
        if _is_international(origin, destination):
            visa = context.get("visa_check")
            if not visa:
                raise SkillError(
                    "visa_check_missing",
                    "international booking refused: no visa/entry check ran "
                    "for this route", recoverable=True)
            if visa.get("visa_blocked"):
                raise SkillError(
                    "visa_route_blocked",
                    "booking refused: baseline visa rules BLOCK this route "
                    f"({' | '.join(visa.get('block_reasons') or []) or 'see visa check'}); "
                    "there is no override for a blocked route",
                    recoverable=False)
            if visa.get("passport_unknown"):
                raise SkillError(
                    "passport_unknown",
                    "international booking refused: passport country is "
                    "missing or unknown — capture it in the profile before "
                    "booking", recoverable=True)
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

        # --- idempotent retry: SAME trip + SAME option -> same PNR, zero extra
        # booking calls. Lookup sits AFTER every safety gate (G2-DA fix): a
        # replay can never skip visa/passport/fare checks.
        idempotency_key = (trip_id, option_id)
        if idempotency_key in self._booked:
            replay = dict(self._booked[idempotency_key])
            replay["idempotent_replay"] = True
            return replay

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
        self._booked[idempotency_key] = result
        return result
