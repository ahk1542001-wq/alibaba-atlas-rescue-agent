from fastapi import APIRouter
from fastapi.responses import JSONResponse
from services.atlas_client import AtlasClient
from services.rescue_engine import RescueEngine

router = APIRouter(prefix="/api", tags=["Telemetry & Ancillaries"])
atlas_client = AtlasClient()
rescue_engine = RescueEngine(atlas_client)

@router.get("/baggage/track")
async def track_baggage(pnr: str = "ATLAS-45BAE5"):
    """Track real-time baggage transfer checkpoints."""
    res = await atlas_client.get_baggage_status(pnr)
    return JSONResponse(content=res)

@router.get("/seatmap")
async def get_seat_map(flight_number: str = "8M336"):
    """Fetch seat map for aircraft cabin."""
    res = await atlas_client.get_seat_map(flight_number)
    return JSONResponse(content=res)

@router.get("/agent/telemetry")
async def get_agent_telemetry():
    """Fetch Qoder / Qwen-2.5 Agentic reasoning prompt and performance telemetry."""
    res = rescue_engine.get_agent_prompt_telemetry()
    return JSONResponse(content=res)
