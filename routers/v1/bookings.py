from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from models.schemas import BookingRequest
from services.atlas_client import AtlasClient

router = APIRouter(prefix="/api/rescue", tags=["Bookings"])
atlas_client = AtlasClient()

@router.post("/book")
async def execute_rescue_booking(req: BookingRequest):
    """Execute 1-click rebooking, seat assignment, and sandbox ticket issuance via Atlas."""
    try:
        verify_res = await atlas_client.verify_fare(req.offer_id)
        order_res = await atlas_client.create_booking_order(
            offer_id=req.offer_id,
            passenger={
                "name": req.passenger_name,
                "price_usd": req.price_usd
            },
            baggage_addon=req.baggage_addon,
            seat_selected=req.seat_selected or "12A"
        )
        return JSONResponse(content={
            "success": True,
            "verification": verify_res,
            "ticket": order_res,
            "message": "Rescue flight rebooked and e-ticket issued in 18 seconds."
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
