import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from models.schemas import ConciergeQuery
from services.atlas_client import AtlasClient
from services.rescue_engine import RescueEngine

router = APIRouter(prefix="/api/chat", tags=["Concierge"])
atlas_client = AtlasClient()
rescue_engine = RescueEngine(atlas_client)
logger = logging.getLogger("concierge")

@router.post("/concierge")
async def chat_concierge(req: ConciergeQuery):
    """AI Travel Concierge endpoint for real-time passenger assistance."""
    try:
        trip_ctx = None
        target_trip_id = req.trip_id
        from routers.v1.trip import get_trip_orchestrator
        orch = get_trip_orchestrator()

        if not target_trip_id and req.user_id:
            # find latest trip for user
            target_trip_id = next(
                (t.trip_id for t in reversed(list(orch.executor._trips.values()))
                 if t.context.get("user_id") == req.user_id), None
            )
        if not target_trip_id and orch.executor._trips:
            # use most recent active trip
            target_trip_id = list(orch.executor._trips.keys())[-1]

        if target_trip_id and target_trip_id in orch.executor._trips:
            trip = orch.executor._trips[target_trip_id]
            trip_ctx = dict(trip.context)
            trip_ctx["trip_id"] = target_trip_id
            trip_ctx["status"] = trip.status
            trip_ctx["pending_approvals"] = [a.model_dump(mode="json") for a in trip.pending_approvals]
            trip_ctx["nodes"] = [n.model_dump(mode="json") for n in trip.trace]

        res = await rescue_engine.answer_concierge(req.query, context=trip_ctx)
        if target_trip_id:
            res["trip_id"] = target_trip_id
        return JSONResponse(content=res)
    except Exception as exc:
        logger.warning("concierge request failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=500,
            detail="Unable to answer the concierge request.",
        ) from exc
