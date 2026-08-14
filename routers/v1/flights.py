from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from models.schemas import FlightSearchRequest
from services.atlas_client import AtlasClient

router = APIRouter(prefix="/api/flights", tags=["Flights"])
atlas_client = AtlasClient()

@router.post("/search")
async def search_flights(req: FlightSearchRequest):
    """Global Multi-Carrier Flight Search on Atlas GDS with multi-currency conversion."""
    try:
        offers = await atlas_client.search_flights(
            origin=req.origin,
            destination=req.destination,
            date=req.date or "2026-08-20",
            passengers=req.passengers or 1,
            cabin_class=req.cabin_class or "ECONOMY",
            currency=req.currency or "USD"
        )
        return JSONResponse(content={"count": len(offers), "offers": offers})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
