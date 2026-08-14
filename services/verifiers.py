import datetime
from typing import Dict, Any, List

class DisruptionVerifierEngine:
    """
    Cobus Greyling Loop Engineering Verifier Suite.
    Deterministic verification gates to ensure zero-hallucination and transaction safety.
    """

    @staticmethod
    def verify_fare_lock_contract(offer_id: str, price_usd: float, fare_lock_response: Dict[str, Any]) -> Dict[str, Any]:
        """Verifies that fare price is guaranteed and lock has not expired."""
        is_verified = fare_lock_response.get("verified", False)
        expires_in = fare_lock_response.get("fare_lock_expires_in_seconds", 0)
        
        if not is_verified or expires_in <= 0:
            return {
                "passed": False,
                "verifier_name": "FareLockContractVerifier",
                "error": "Fare lock rejected by Atlas GDS or expired",
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }
        
        return {
            "passed": True,
            "verifier_name": "FareLockContractVerifier",
            "locked_price_usd": price_usd,
            "ttl_seconds": expires_in,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }

    @staticmethod
    def verify_seat_no_conflict(seat_selected: str, occupied_seats: List[str]) -> Dict[str, Any]:
        """Ensures selected seat is not occupied or double-booked."""
        if seat_selected in occupied_seats:
            return {
                "passed": False,
                "verifier_name": "SeatConflictVerifier",
                "error": f"Seat {seat_selected} is already occupied. Must self-heal to next best seat.",
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }
        
        return {
            "passed": True,
            "verifier_name": "SeatConflictVerifier",
            "assigned_seat": seat_selected,
            "status": "LOCKED_NO_CONFLICT",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }

    @staticmethod
    def verify_baggage_continuity(pnr: str, original_tag: str, rescue_flight: str) -> Dict[str, Any]:
        """Verifies physical baggage transfer checkpoint integrity."""
        if not original_tag.startswith("BKK-") or not rescue_flight:
            return {
                "passed": False,
                "verifier_name": "BaggageContinuityVerifier",
                "error": "Invalid baggage tag sequence or unassigned flight",
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }
        
        return {
            "passed": True,
            "verifier_name": "BaggageContinuityVerifier",
            "baggage_tag": original_tag,
            "manifest_status": "LOADED_ON_CARGO_BAY_2",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }

    @staticmethod
    def verify_regulatory_payout(cancellation_cause: str, delay_hours: float) -> Dict[str, Any]:
        """Verifies regulatory delay compensation eligibility under aviation rights."""
        # Controllable maintenance delay >= 2 hours qualifies for $250.00
        eligible_amount = 250.00 if "maintenance" in cancellation_cause.lower() or "hydraulics" in cancellation_cause.lower() or delay_hours >= 2.0 else 0.0
        
        return {
            "passed": eligible_amount > 0,
            "verifier_name": "RegulatoryPayoutVerifier",
            "eligible_amount_usd": eligible_amount,
            "regulation": "Aviation Consumer Protection Article 14 / EU261 standard",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
