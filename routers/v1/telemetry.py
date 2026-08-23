from fastapi import APIRouter
from fastapi.responses import JSONResponse
from services.atlas_client import AtlasClient
from services.rescue_engine import RescueEngine
from services.state_graph import DisruptionRecoveryDAG

router = APIRouter(prefix="/api", tags=["Telemetry, State Graph & Ancillaries"])
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

@router.get("/radar/predictive")
async def get_predictive_radar(flight_number: str = "TG303"):
    """Fetch 45m early predictive disruption radar telemetry."""
    res = rescue_engine.get_predictive_radar(flight_number)
    return JSONResponse(content=res)

@router.get("/agent/telemetry")
async def get_agent_telemetry():
    """Fetch Qoder / Qwen-2.5 Agentic reasoning prompt and performance telemetry."""
    res = rescue_engine.get_agent_prompt_telemetry()
    return JSONResponse(content=res)

@router.get("/graph/state")
async def get_graph_state():
    """Demo replay of the Closed-Loop State Graph (DAG) execution trace.

    The values below are a canned demo replay, not a live execution — the
    live DAG trace for an actual disruption run is included in every
    /api/disruption/analyze response (session_id + nodes).
    """
    dag = DisruptionRecoveryDAG(session_id="demo_replay")
    dag.record_step("IngestionRadar", 8.2, {"source": "Atlas Live Webhook"})
    dag.record_step("PredictiveEvaluator", 14.5, {"cancellation_risk_percent": 88})
    dag.record_step("DisruptionConfirmed", 11.0, {"status": "CANCELLED"})
    dag.record_step("ParetoOptimizer", 14.8, {"offers_evaluated": 4, "curated": 3})
    dag.record_step("FareLockHold", 38.0, {"lock_status": "LOCKED", "expires_in": 900})
    dag.record_step("PassengerDecision", 12.0, {"action": "1_CLICK_REBOOK_CONFIRMED"})
    dag.record_step("TicketSettlement", 45.0, {"pnr": "ATLAS-45BAE5", "ticket": "140-981240182"})
    dag.record_step("AncillarySync", 22.0, {"baggage_transferred": True, "seat": "11B", "claim_filed": True})
    dag.record_step("ClosedLoopVerified", 5.0, {"status": "SUCCESS_VERIFIED"})
    telemetry = dag.get_graph_telemetry()
    telemetry["mode"] = "demo_replay"
    return JSONResponse(content=telemetry)
