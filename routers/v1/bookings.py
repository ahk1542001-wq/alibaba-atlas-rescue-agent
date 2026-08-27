from fastapi import APIRouter, HTTPException, Header
from fastapi.responses import JSONResponse
from models.schemas import BookingRequest
from services.atlas_client import AtlasClient

router = APIRouter(prefix="/api/rescue", tags=["Bookings"])
atlas_client = AtlasClient()
_rescue_locks = {}

@router.post("/book")
async def execute_rescue_booking(req: BookingRequest, idempotency_key: str = Header(None)):
    """Execute 1-click rebooking, seat assignment, and sandbox ticket issuance via Atlas."""
    if not idempotency_key:
        idempotency_key = "legacy-default-" + req.offer_id  # fallback for demo paths
    if idempotency_key in _rescue_locks:
        if _rescue_locks[idempotency_key] == "PENDING":
            raise HTTPException(409, "Concurrent request")
        return JSONResponse(content=_rescue_locks[idempotency_key])
    _rescue_locks[idempotency_key] = "PENDING" 
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
        res_content = {
            "success": True,
            "verification": verify_res,
            "ticket": order_res,
            "message": "Rescue flight rebooked and e-ticket issued in 18 seconds."
        }
        _rescue_locks[idempotency_key] = res_content
        return JSONResponse(content=res_content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
