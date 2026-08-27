"""RecoveryPlanSkill — §4 S13 (G2 behavior).

Prepares flight disruption recovery options and an immutable approval request
snapshot. Reuses RescueEngine / Atlas search patterns without ever booking
prior to explicit user approval at the recovery gate.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from models.schemas import ApprovalRequest, FlightOption, Money
from services.atlas_client import AtlasClient
from services.rescue_engine import RescueEngine
from services.skills.base import SkillBase, SkillError
from services.skills.flight_search import normalize_offer


class RecoveryPlanInput(BaseModel):
    trip_id: str
    booking: Optional[Dict[str, Any]] = None
    event: Optional[Dict[str, Any]] = None


class RecoveryOption(BaseModel):
    option_id: str
    package_type: str
    option: FlightOption
    reason: str
    farelock_available: bool = True


class RecoveryPlanResult(BaseModel):
    trip_id: str
    status: str = "approval_required"
    recovery_options: List[RecoveryOption] = Field(default_factory=list)
    approval_request: Optional[ApprovalRequest] = None


class RecoveryPlanSkill(SkillBase):
    name = "recovery_plan"
    when_to_use = (
        "when DisruptionEvent is confirmed; prepares recovery flight options "
        "and creates an immutable approval request without booking"
    )
    capabilities = frozenset({"atlas_call", "llm_call", "approval_required"})
    input_model = RecoveryPlanInput
    output_model = RecoveryPlanResult

    def __init__(self, atlas: Optional[Any] = None, engine: Optional[Any] = None) -> None:
        self._atlas = atlas or AtlasClient()
        self._engine = engine or RescueEngine(self._atlas)

    async def run(self, payload: Dict[str, Any],
                  context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        trip_id = str(payload.get("trip_id") or (context or {}).get("trip_id") or "trip-demo")
        booking = payload.get("booking") or (context or {}).get("booking") or {}
        event = payload.get("event") or (context or {}).get("disruption_event") or {}

        opt_data = (booking.get("option") or booking.get("booking", {}).get("option") or {})
        origin = str(opt_data.get("dep", {}).get("airport") or event.get("origin") or "BKK").upper()
        destination = str(opt_data.get("arr", {}).get("airport") or event.get("destination") or "SIN").upper()

        departure_time = str((opt_data.get("dep") or {}).get("time") or "")
        travel_date = departure_time[:10] if len(departure_time) >= 10 \
            else str(event.get("date") or date.today().isoformat())
        original_id = opt_data.get("id")

        # Search alternatives through the injected Atlas boundary. The date
        # comes from the original BookingRecord; no fixed demo date is used.
        res = self._atlas.search_flights(origin, destination, travel_date)
        if hasattr(res, "__await__"):
            raw_offers = await res
        else:
            raw_offers = res
        if not raw_offers:
            return RecoveryPlanResult(
                trip_id=trip_id,
                status="no_alternatives_available",
                recovery_options=[],
                approval_request=None,
            ).model_dump(mode="json")

        recovery_options: List[RecoveryOption] = []
        for offer in raw_offers:
            norm = normalize_offer(offer)
            if norm.get("id") == original_id:
                continue
            i = len(recovery_options)
            pkg_type = "FASTEST_RECOVERY" if i == 0 else ("CHEAPEST" if i == 1 else "SAME_AIRLINE")
            recovery_options.append(RecoveryOption(
                option_id=norm["id"],
                package_type=pkg_type,
                option=FlightOption(**norm),
                reason=f"{pkg_type.replace('_', ' ').title()} alternative departing at {norm['dep']['time']}",
                farelock_available=True,
            ))
            if len(recovery_options) >= 3:
                break

        if not recovery_options:
            return RecoveryPlanResult(
                trip_id=trip_id,
                status="no_alternatives_available",
                recovery_options=[],
                approval_request=None,
            ).model_dump(mode="json")

        option_snapshots = [
            option.option.model_dump(mode="json") for option in recovery_options]
        approval_id = f"appr-recov-{uuid.uuid4().hex[:8]}"
        approval = ApprovalRequest(
            approval_id=approval_id,
            trip_id=trip_id,
            node_name="recovery_booking",
            purpose="recovery_booking",
            options=[{
                "id": option.option_id,
                "label": option.option.flight_no,
                "reason": option.reason,
            } for option in recovery_options],
            immutable_option={"options": option_snapshots},
            price_snapshot={"options": [
                {"id": option["id"], "price": option.get("price")}
                for option in option_snapshots
            ]},
            created_at=datetime.now(timezone.utc).isoformat(),
            expires_at=(datetime.now(timezone.utc) + timedelta(minutes=30))
            .isoformat(),
        )

        res = RecoveryPlanResult(
            trip_id=trip_id,
            status="approval_required",
            recovery_options=recovery_options,
            approval_request=approval,
        )
        return res.model_dump(mode="json")
