import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional

from services.rights_engine import (
    classify_cause,
    compute_entitlement,
    detect_jurisdictions,
    build_evidence_pack,
    draft_appeal,
    airports_to_countries,
    route_distance_km,
)
from services.atlas_client import AtlasClient
from services.rescue_engine import RescueEngine

router = APIRouter(prefix="/api/claims", tags=["Claims"])

atlas_client = AtlasClient()
rescue_engine = RescueEngine(atlas_client)


class ClaimAssessRequest(BaseModel):
    flight_number: str
    date: Optional[str] = None
    passenger_name: Optional[str] = None
    origin_airport: Optional[str] = None
    destination_airport: Optional[str] = None


@router.post("/assess")
async def assess_claim(req: ClaimAssessRequest):
    """Claim Autopilot: detect regime, compute entitlement, classify cause.

    Jurisdictions are derived server-side from the real itinerary (airports +
    airline code) — never from client-supplied country hints.
    """
    try:
        date = req.date or datetime.date.today().strftime("%Y-%m-%d")
        status = await atlas_client.get_flight_status(req.flight_number, date)
        reason = str(status.get("reason", ""))
        disruption_type = str(status.get("status", "disruption"))

        origin_airport = (req.origin_airport or status.get("origin") or "").upper()
        dest_airport = (req.destination_airport or status.get("destination") or "").upper()
        airline_code = req.flight_number[:2]
        o_c, d_c, c_c = airports_to_countries(origin_airport, dest_airport, airline_code)
        distance_km = route_distance_km(origin_airport, dest_airport)

        route_info = {
            "origin_airport": origin_airport or None,
            "destination_airport": dest_airport or None,
            "origin_country": o_c or "UNKNOWN",
            "destination_country": d_c or "UNKNOWN",
            "carrier_country": c_c or "UNKNOWN",
            "distance_km": distance_km,
        }

        regimes = detect_jurisdictions(o_c, d_c, c_c)
        if not regimes:
            unmapped = [
                k for k, v in (
                    ("origin", o_c), ("destination", d_c), ("carrier", c_c)
                ) if not v
            ]
            verdict = (
                f"No mandatory air-passenger-rights regime detected for "
                f"{origin_airport or '?'}→{dest_airport or '?'}. "
                + (
                    f"Jurisdiction could not be resolved for: {', '.join(unmapped)}. "
                    if unmapped else ""
                )
                + "Duty-of-care still applies under the airline's conditions of carriage."
            )
            return JSONResponse(content={
                "route": route_info,
                "jurisdictions": [],
                "best": None,
                "verdict": verdict,
            })

        best = regimes[0]
        entitlement = compute_entitlement(best["id"], distance_km)
        classification = await classify_cause(reason, best["id"])
        compensable = classification.get("classification") == "COMPENSABLE"

        claim = {
            "jurisdiction_id": best["id"],
            "airline": status.get("airline", req.flight_number[:2]),
            "flight_number": req.flight_number,
            "date": date,
            "passenger_name": req.passenger_name or "",
            "origin_airport": origin_airport,
            "destination_airport": dest_airport,
            "reason": reason,
            "disruption_type": disruption_type,
            "classification": classification.get("classification"),
            "entitlement": entitlement,
        }
        evidence = build_evidence_pack(claim)

        verdict = (
            f"Strong claim: {best['name']} applies and the stated cause is "
            f"compensable. {entitlement.get('fixed_cash_compensation') or ''}"
            if compensable
            else f"Likely extraordinary circumstance under {best['name']} — cash "
                 "compensation unlikely, but duty of care (meals/hotel/refund) "
                 "still applies cause-blind."
        )
        return JSONResponse(content={
            "route": route_info,
            "jurisdictions": [
                {"id": r["id"], "name": r["name"], "citation": r["citation"],
                 "trigger": r["trigger"]}
                for r in regimes
            ],
            "best": {
                "id": best["id"],
                "name": best["name"],
                "citation": best["citation"],
                "duty_of_care": best.get("duty_of_care"),
                "refund_or_reroute": best.get("refund_or_reroute"),
            },
            "reason": reason,
            "classification": classification,
            "entitlement": entitlement,
            "evidence_pack": evidence,
            "verdict": verdict,
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class AppealRequest(BaseModel):
    claim: dict = Field(..., description="Claim payload returned by /assess")
    rejection_reason: str = "Extraordinary circumstances beyond our control"


@router.post("/appeal")
async def appeal_rejected_claim(req: AppealRequest):
    """Draft a regulation-citing appeal against an airline rejection."""
    try:
        claim = dict(req.claim)
        result = await draft_appeal(claim, req.rejection_reason)
        return JSONResponse(content=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
