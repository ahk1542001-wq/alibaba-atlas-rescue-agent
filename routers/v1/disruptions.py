from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from models.schemas import DisruptionEvent
from services.atlas_client import AtlasClient
from services.rescue_engine import RescueEngine

router = APIRouter(prefix="/api/disruption", tags=["Disruptions"])
atlas_client = AtlasClient()
rescue_engine = RescueEngine(atlas_client)

@router.post("/analyze")
async def analyze_disruption(req: DisruptionEvent):
    """Trigger agentic AI analysis, multi-carrier scan, and Pareto package curation."""
    try:
        result = await rescue_engine.handle_disruption(
            flight_number=req.flight_number,
            passenger_name=req.passenger_name or "Aung Hein Kyaw",
            date=req.date,
            currency=req.currency or "USD"
        )
        return JSONResponse(content=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
