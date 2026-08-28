import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from models.schemas import DisruptionEvent
from services.atlas_client import AtlasClient
from services.rescue_engine import FlightStatusUnavailableError, RescueEngine

router = APIRouter(prefix="/api/disruption", tags=["Disruptions"])
atlas_client = AtlasClient()
rescue_engine = RescueEngine(atlas_client)
logger = logging.getLogger("disruptions")

@router.post("/analyze")
async def analyze_disruption(req: DisruptionEvent, allow_sim: bool = False):
    """Trigger agentic AI analysis, multi-carrier scan, and Pareto package curation."""
    try:
        result = await rescue_engine.handle_disruption(
            flight_number=req.flight_number,
            passenger_name=req.passenger_name,
            date=req.date,
            currency=req.currency or "USD",
            nationality=req.nationality or "MM",
            simulation=allow_sim,
        )
        return JSONResponse(content=result)
    except FlightStatusUnavailableError as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                "Flight status unavailable in Atlas Sandbox; "
                "no recovery plan was created."
            ),
        ) from exc
    except Exception as exc:
        logger.warning("disruption analysis failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=500,
            detail="Unable to analyze the disruption.",
        ) from exc

@router.post("/self-heal")
async def trigger_self_healing_recovery(flight_number: str, passenger: str = ""):
    """Trigger Graph & Loop Engineering Fault Injection & Auto Self-Healing Recovery."""
    try:
        result = await rescue_engine.execute_self_healing_recovery(flight_number, passenger)
        return JSONResponse(content=result)
    except Exception as exc:
        logger.warning("self-healing recovery failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=500,
            detail="Unable to run self-healing recovery.",
        ) from exc
