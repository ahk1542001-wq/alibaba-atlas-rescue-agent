import asyncio
import hashlib
import json
from copy import deepcopy
from typing import Dict, Tuple

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse

from models.schemas import BookingRequest
from services.atlas_client import (
    AtlasClient,
    AtlasTicketingUnavailableError,
    AtlasTravelerDataRequiredError,
)

router = APIRouter(prefix="/api/rescue", tags=["Bookings"])
atlas_client = AtlasClient()
_rescue_booking_ledger: Dict[str, Tuple[str, dict]] = {}
_rescue_booking_locks: Dict[str, asyncio.Lock] = {}


def _payload_hash(req: BookingRequest) -> str:
    canonical = json.dumps(
        req.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()

@router.post("/book")
async def execute_rescue_booking(
    req: BookingRequest,
    idempotency_key: str = Header(None, alias="Idempotency-Key"),
):
    """Issue one Atlas Sandbox order with conflict-safe retry semantics."""
    key = (idempotency_key or "").strip()
    if not key:
        raise HTTPException(
            status_code=422,
            detail="Idempotency-Key header is required for booking requests.",
        )

    request_hash = _payload_hash(req)
    lock = _rescue_booking_locks.setdefault(key, asyncio.Lock())
    async with lock:
        stored = _rescue_booking_ledger.get(key)
        if stored is not None:
            stored_hash, stored_response = stored
            if stored_hash != request_hash:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Idempotency-Key was already used with a different "
                        "booking payload."
                    ),
                )
            return JSONResponse(content=deepcopy(stored_response))

        try:
            verify_res = await atlas_client.verify_fare(req.offer_id)
            if not verify_res.get("verified"):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "The fare could not be re-verified; no booking order "
                        "was created."
                    ),
                )
            booking_id = str(verify_res.get("booking_id") or "").strip()
            if not booking_id:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "Atlas Sandbox returned no booking context; no order "
                        "was created."
                    ),
                )
            order_res = await atlas_client.create_booking_order(
                booking_id=booking_id,
                passenger={
                    "name": req.passenger_name,
                    "price_usd": req.price_usd,
                    "party_size": req.party_size,
                },
                baggage_addon=req.baggage_addon,
                seat_selected=req.seat_selected or "12A",
            )
        except AtlasTicketingUnavailableError as exc:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Atlas Sandbox ticketing is not activated; no booking "
                    "or PNR was created."
                ),
            ) from exc
        except AtlasTravelerDataRequiredError as exc:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Atlas Sandbox requires an approved ephemeral traveler-"
                    "data flow; no booking or PNR was created."
                ),
            ) from exc
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Atlas Sandbox booking failed. Retry the same request "
                    "with the same Idempotency-Key."
                ),
            ) from exc

        response = {
            "success": True,
            "verification": verify_res,
            "ticket": order_res,
            "message": "Rescue flight rebooked and Sandbox e-ticket issued.",
        }
        _rescue_booking_ledger[key] = (request_hash, deepcopy(response))
        return JSONResponse(content=response)
