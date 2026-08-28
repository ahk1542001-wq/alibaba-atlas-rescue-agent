import datetime
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from models.schemas import FlightSearchRequest
from services.atlas_client import AtlasClient

router = APIRouter(prefix="/api/flights", tags=["Flights"])
atlas_client = AtlasClient()
logger = logging.getLogger("flights")


def _default_search_date() -> str:
    """Sandbox rejects same-day/past searches — default to the day after tomorrow."""
    return (datetime.date.today() + datetime.timedelta(days=2)).strftime("%Y-%m-%d")

@router.post("/search")
async def search_flights(req: FlightSearchRequest):
    """Global Multi-Carrier Flight Search on Atlas GDS with multi-currency conversion."""
    try:
        offers = await atlas_client.search_flights(
            origin=req.origin,
            destination=req.destination,
            date=req.date or _default_search_date(),
            passengers=req.passengers or 1,
            cabin_class=req.cabin_class or "ECONOMY",
            currency=req.currency or "USD"
        )
        return JSONResponse(content={"count": len(offers), "offers": offers})
    except Exception as exc:
        logger.warning("flight search failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=502,
            detail="Unable to search flights in Atlas Sandbox.",
        ) from exc
