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
)
from services.atlas_client import AtlasClient
from services.rescue_engine import RescueEngine

router = APIRouter(prefix="/api/claims", tags=["Claims"])

atlas_client = AtlasClient()
rescue_engine = RescueEngine(atlas_client)


class ClaimAssessRequest(BaseModel):
    flight_number: str = "TG303"
    date: str = "2026-08-20"
    passenger_name: str = "Aung Hein Kyaw"
    origin_country: str = "FR"
    destination_country: str = "TH"
    carrier_country: str = "FR"
    distance_km: int = Field(9200, ge=1, le=20000)


@router.post("/assess")
async def assess_claim(req: ClaimAssessRequest):
    """Claim Autopilot: detect regime, compute entitlement, classify cause."""
    try:
        status = await atlas_client.get_flight_status(req.flight_number, req.date)
        reason = str(status.get("reason", ""))
        disruption_type = str(status.get("status", "disruption"))

        regimes = detect_jurisdictions(
            req.origin_country, req.destination_country, req.carrier_country
        )
        if not regimes:
            return JSONResponse(content={
                "jurisdictions": [],
                "best": None,
                "verdict": (
                    "No mandatory air-passenger-rights regime detected for this "
                    "route. Duty-of-care still applies under the airline's "
                    "conditions of carriage."
                ),
            })

        best = regimes[0]
        entitlement = compute_entitlement(best["id"], req.distance_km)
        classification = await classify_cause(reason, best["id"])
        compensable = classification.get("classification") == "COMPENSABLE"

        claim = {
            "jurisdiction_id": best["id"],
            "airline": status.get("airline", req.flight_number[:2]),
            "flight_number": req.flight_number,
            "date": req.date,
            "passenger_name": req.passenger_name,
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
