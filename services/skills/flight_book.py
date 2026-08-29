"""flight_book skill — §4 S5 (G2 behavior).

Wraps atlas_client.verify_fare + create_booking_order (frozen service,
import-only). Owner correction (C) enforced here:

- the deterministic SAFETY gate (Task #13) runs FIRST, ahead of every
  other gate, whenever the orchestrator injects context["safety_check"]:
  do_not_travel BLOCKS booking outright (no override — user approval never
  makes the risk go away), reconsider_travel halts until a SEPARATE risk
  acknowledgement exists, unable_to_verify halts UNCONDITIONALLY until a
  verified (non-unable_to_verify) status exists — a failed verification
  retry never clears it (G4.6-DA fix F1);
- fares are REFRESHED and REVERIFIED (verify_fare) IMMEDIATELY before the
  booking order — never booked on stale search data; when Atlas requires
  increased-fare confirmation, the resumed run confirms the server-bound
  opaque booking context instead of re-verifying the original offer;
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

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional

from models.schemas import BookingRecord, FlightOption
from services.atlas_client import (
    AtlasClient,
    AtlasProviderError,
    AtlasTicketingUnavailableError,
    AtlasTravelerDataRequiredError,
)
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
        self._booking_locks: Dict[tuple, asyncio.Lock] = {}

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
            if status == "unable_to_verify":
                # G4.6-DA fix F1: blocks UNCONDITIONALLY — a failed
                # verification retry is not a fresh verification. Only a
                # VERIFIED status (which by definition is not
                # unable_to_verify) ever lifts this gate.
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

        idempotency_key = (trip_id, option_id)
        lock = self._booking_locks.setdefault(idempotency_key, asyncio.Lock())
        async with lock:
            # Refresh and reverify inside the per-booking lock. Concurrent
            # identical calls cannot both cross the provider-create boundary.
            confirmed_snapshot = payload.get("confirmed_price_snapshot")
            confirmed_snapshot = (confirmed_snapshot
                                  if isinstance(confirmed_snapshot, dict)
                                  else None)
            confirmed_booking_id = str(
                (confirmed_snapshot or {}).get("booking_id") or "").strip()
            if confirmed_snapshot:
                if ((confirmed_snapshot.get("offer_id") or "") != option_id
                        or confirmed_snapshot.get("amount") is None
                        or not confirmed_snapshot.get("currency")
                        or not confirmed_booking_id):
                    raise SkillError(
                        "price_reapproval_context_invalid",
                        "The approved fare snapshot is incomplete or does not "
                        "match the selected offer.",
                        recoverable=True,
                    )
            try:
                if confirmed_booking_id:
                    verification = await self._atlas.confirm_price(
                        confirmed_booking_id)
                else:
                    verification = await self._atlas.verify_fare(option_id)
            except AtlasTicketingUnavailableError as exc:
                raise SkillError(
                    "atlas_ticketing_unavailable",
                    "Atlas Sandbox ticketing is not activated; no booking "
                    "or PNR was created.",
                    recoverable=True,
                ) from exc
            except AtlasProviderError as exc:
                raise SkillError(
                    "atlas_fare_verification_unavailable",
                    "Atlas Sandbox could not re-verify this fare; search "
                    "again before approving a booking.",
                    recoverable=True,
                ) from exc
            price_change = verification.get("price_change")
            opt_dict = payload.get("option") or {}
            opt_price = opt_dict.get("price")
            opt_amt = opt_price.get("amount") if isinstance(opt_price, dict) else opt_dict.get("price_usd")
            confirmed_price = verification.get("current_price")
            confirmed_currency = verification.get("currency")
            curr = verification.get("currency") or (opt_price.get("currency") if isinstance(opt_price, dict) else "USD")
            new_price = verification.get("current_price") or verification.get("price_usd")
            prev_price = verification.get("previous_price") or opt_amt

            if confirmed_snapshot:
                expected_currency = str(
                    confirmed_snapshot["currency"]).upper()
                actual_currency = str(confirmed_currency or "").upper()
                try:
                    expected_amount = Decimal(str(
                        confirmed_snapshot["amount"]))
                    actual_amount = Decimal(str(confirmed_price))
                except (InvalidOperation, TypeError, ValueError):
                    expected_amount = actual_amount = None
                if (expected_amount is None or actual_amount is None
                        or not expected_amount.is_finite()
                        or not actual_amount.is_finite()
                        or actual_amount != expected_amount
                        or actual_currency != expected_currency):
                    err = SkillError(
                        "fare_price_increased",
                        "The confirmed Atlas fare no longer matches the "
                        "amount and currency that were approved; a fresh "
                        "approval is required before booking.",
                        recoverable=True,
                    )
                    err.details = {
                        "price_change": "changed_after_approval",
                        "previous_price": confirmed_snapshot["amount"],
                        "current_price": confirmed_price,
                        "currency": actual_currency or expected_currency,
                        "offer_id": option_id,
                        "booking_id": verification.get("booking_id"),
                        "verified_at": verification.get("verified_at")
                        or datetime.now(timezone.utc).isoformat(),
                    }
                    raise err

            notice = None
            if price_change == "decreased" or (prev_price and new_price and float(new_price) < float(prev_price)):
                notice = f"Fare decreased from {curr} {prev_price} to {curr} {new_price}."

            if (not verification.get("price_confirmed") and (
                    price_change == "increased"
                    or verification.get("price_confirmation_required")
                    or (prev_price and new_price
                        and float(new_price) > float(prev_price)))):
                err = SkillError(
                    "fare_price_increased",
                    f"Fare for option '{option_id}' increased from {curr} {prev_price} to {curr} {new_price}; re-approval required before booking.",
                    recoverable=True,
                )
                err.details = {
                    "price_change": "increased",
                    "previous_price": prev_price,
                    "current_price": new_price,
                    "currency": curr,
                    "offer_id": option_id,
                    "booking_id": verification.get("booking_id"),
                    "verified_at": verification.get("verified_at") or datetime.now(timezone.utc).isoformat(),
                }
                raise err

            if not verification.get("verified"):
                raise SkillError("fare_unverified",
                                 f"fare '{option_id}' failed re-verification; "
                                 "booking refused", recoverable=True)
            booking_id = str(verification.get("booking_id") or "").strip()
            if not booking_id:
                raise SkillError(
                    "atlas_booking_context_missing",
                    "Atlas Sandbox returned no booking context; search and "
                    "verify the fare again.",
                    recoverable=True,
                )

            if idempotency_key in self._booked:
                replay = dict(self._booked[idempotency_key])
                replay["idempotent_replay"] = True
                return replay

            option_dump = deepcopy(payload.get("option") or {})
            if confirmed_snapshot:
                confirmed_amount = float(Decimal(str(
                    confirmed_snapshot["amount"])))
                confirmed_currency = str(
                    confirmed_snapshot["currency"]).upper()
                option_dump["price"] = {
                    "amount": confirmed_amount,
                    "currency": confirmed_currency,
                }
                option_dump["price_usd"] = confirmed_amount
                passenger_count = max(1, int(
                    option_dump.get("passenger_count") or 1))
                if option_dump.get("price_per_passenger") is not None:
                    option_dump["price_per_passenger"] = {
                        "amount": confirmed_amount / passenger_count,
                        "currency": confirmed_currency,
                    }
            passenger = payload.get("passenger") or {}
            try:
                order = await self._atlas.create_booking_order(
                    booking_id,
                    {"name": passenger.get("name", ""),
                     "price_usd": (option_dump.get("price") or {})
                                  .get("amount")},
                )
            except AtlasTicketingUnavailableError as exc:
                raise SkillError(
                    "atlas_ticketing_unavailable",
                    "Atlas Sandbox ticketing is not activated; no booking "
                    "or PNR was created.",
                    recoverable=True,
                ) from exc
            except AtlasTravelerDataRequiredError as exc:
                raise SkillError(
                    "atlas_traveler_data_required",
                    "Atlas Sandbox requires an approved ephemeral traveler-"
                    "data flow before an order can be created.",
                    recoverable=True,
                ) from exc
            except AtlasProviderError as exc:
                raise SkillError(
                    "atlas_booking_unavailable",
                    "Atlas Sandbox could not create the order; no booking or "
                    "PNR was created.",
                    recoverable=True,
                ) from exc

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
                "notice": notice,
                "monitor_armed": True,
                "idempotent_replay": False,
                "provenance": "sandbox",
            }
            self._booked[idempotency_key] = result
            return result
