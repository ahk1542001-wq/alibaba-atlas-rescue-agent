import asyncio
import json
from typing import Any, Dict

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from services.radar import get_radar

router = APIRouter(prefix="/api/radar", tags=["Radar"])


@router.get("")
async def radar_state():
    """Current radar state: watchlist, live alerts, last scan snapshot."""
    return JSONResponse(content=get_radar().state())


@router.post("/scan")
async def radar_scan():
    """Force an immediate scan (used by the UI 'Scan Now' button)."""
    result = await get_radar().scan()
    return JSONResponse(content=result)


@router.post("/watch")
async def radar_watch(req: Dict[str, Any]):
    """Add a flight to the autonomous watchlist."""
    fn = req.get("flight_number")
    date = req.get("date")
    if not fn or not date:
        return JSONResponse(status_code=400, content={"error": "flight_number and date required"})
    added = get_radar().add_flight(fn, date, req.get("passenger_name", ""))
    return JSONResponse(content={"added": added, "watchlist": get_radar().watchlist})


@router.get("/stream")
async def radar_stream():
    """Server-Sent Events stream pushing new proactive alerts as they appear."""
    radar = get_radar()

    async def event_gen():
        last_len = len(radar.alerts)
        while True:
            await asyncio.sleep(2)
            if len(radar.alerts) > last_len:
                fresh = radar.alerts[: len(radar.alerts) - last_len]
                for alert in fresh:
                    yield f"data: {json.dumps(alert)}\n\n"
                last_len = len(radar.alerts)

    return StreamingResponse(event_gen(), media_type="text/event-stream")
