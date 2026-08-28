from fastapi import APIRouter
from fastapi.responses import JSONResponse
from services.atlas_client import AtlasClient
from services.rescue_engine import RescueEngine
from services.state_graph import DisruptionRecoveryDAG

router = APIRouter(prefix="/api", tags=["Telemetry, State Graph & Ancillaries"])
atlas_client = AtlasClient()
rescue_engine = RescueEngine(atlas_client)

@router.get("/baggage/track")
async def track_baggage(pnr: str = "DEMO-BAGGAGE"):
    """Return explicitly simulated baggage-transfer checkpoints."""
    res = await atlas_client.get_baggage_status(pnr)
    return JSONResponse(content=res)

@router.get("/seatmap")
async def get_seat_map(flight_number: str = "8M336"):
    """Return an explicitly simulated aircraft seat map."""
    res = await atlas_client.get_seat_map(flight_number)
    return JSONResponse(content=res)

@router.get("/radar/predictive")
async def get_predictive_radar(flight_number: str = "TG303"):
    """Return explicitly simulated predictive disruption telemetry."""
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
    dag.record_step("IngestionRadar", 8.2, {"source": "Explicit demo replay"})
    dag.record_step("PredictiveEvaluator", 14.5, {"cancellation_risk_percent": 88})
    dag.record_step("DisruptionConfirmed", 11.0, {"status": "CANCELLED"})
    dag.record_step("ParetoOptimizer", 14.8, {"offers_evaluated": 4, "curated": 3})
    dag.record_step("FareVerification", 38.0, {"status": "SIMULATED"})
    dag.record_step("PassengerDecision", 12.0, {"action": "DEMO_OPTION_SELECTED"})
    dag.record_step("DemoOutcome", 45.0, {"booking_created": False})
    dag.record_step("AncillarySync", 22.0, {"baggage_transferred": True, "seat": "11B", "claim_filed": True})
    dag.record_step("ClosedLoopVerified", 5.0, {"status": "SUCCESS_VERIFIED"})
    telemetry = dag.get_graph_telemetry()
    telemetry["mode"] = "demo_replay"
    telemetry["provenance"] = "explicit_demo_simulation"
    telemetry["simulated"] = True
    return JSONResponse(content=telemetry)
