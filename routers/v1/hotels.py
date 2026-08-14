from fastapi import APIRouter
from typing import Dict, Any, List
from services.atlas_client import AtlasClient

router = APIRouter(prefix="/api/hotels", tags=["Emergency Transit Hotels"])
atlas_client = AtlasClient()

@router.get("/search", response_model=List[Dict[str, Any]])
async def search_transit_hotels(airport: str = "BKK"):
    """Search Booking.com / Agoda partner emergency transit hotels with check-in/out and free breakfast."""
    return await atlas_client.search_transit_hotels(airport)

@router.get("/vouchers/care", response_model=Dict[str, Any])
async def get_care_gift_vouchers(pnr: str = "ATLAS-45BAE5"):
    """Retrieve 24/7 care gift vouchers pack (lounge, dining, Grab transfer, 10GB eSIM)."""
    return await atlas_client.issue_care_gift_vouchers(pnr)
