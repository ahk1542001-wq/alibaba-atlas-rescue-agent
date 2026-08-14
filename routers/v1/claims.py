from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from services.atlas_client import AtlasClient
from services.rescue_engine import RescueEngine

router = APIRouter(prefix="/api/claims", tags=["Claims"])
atlas_client = AtlasClient()
rescue_engine = RescueEngine(atlas_client)

class ClaimGenRequest(BaseModel):
    flight_number: str
    passenger_name: str

@router.post("/generate")
async def generate_claim(req: ClaimGenRequest):
    """Generate official passenger disruption compensation claim."""
    try:
        disruption = await atlas_client.get_flight_status(req.flight_number, "2026-08-14")
        claim = rescue_engine.generate_compensation_claim(disruption, req.passenger_name)
        return JSONResponse(content=claim)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
