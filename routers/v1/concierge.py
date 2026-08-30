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
        target_trip_id = None
        from routers.v1.trip import get_trip_orchestrator
        orch = get_trip_orchestrator()

        if orch is not None:
            if req.trip_id:
                trip = orch.executor._trips.get(req.trip_id)
                if trip is not None:
                    trip_user = trip.context.get("user_id")
                    if trip_user and req.user_id != trip_user:
                        raise HTTPException(
                            status_code=403,
                            detail="This trip does not belong to the current user.",
                        )
                    target_trip_id = req.trip_id
                    trip_ctx = dict(trip.context)
                    trip_ctx["trip_id"] = target_trip_id
                    trip_ctx["status"] = trip.status
                    trip_ctx["pending_approvals"] = [a.model_dump(mode="json") for a in trip.pending_approvals]
                    trip_ctx["nodes"] = [n.model_dump(mode="json") for n in trip.trace]
            elif req.user_id:
                # Find latest trip belonging to THIS user ONLY
                target_trip = next(
                    (t for t in reversed(list(orch.executor._trips.values()))
                     if t.context.get("user_id") == req.user_id), None
                )
                if target_trip is not None:
                    target_trip_id = target_trip.trip_id
                    trip_ctx = dict(target_trip.context)
                    trip_ctx["trip_id"] = target_trip_id
                    trip_ctx["status"] = target_trip.status
                    trip_ctx["pending_approvals"] = [a.model_dump(mode="json") for a in target_trip.pending_approvals]
                    trip_ctx["nodes"] = [n.model_dump(mode="json") for n in target_trip.trace]

        res = await rescue_engine.answer_concierge(req.query, context=trip_ctx)

        # Back-and-forth structured proposals on active trip
        if target_trip_id and orch is not None:
            import re
            m_pax = re.search(r"\b(?:we\s+are|change\s+to|set\s+to|make\s+it)\s+(\d+|two|three|four|five)\s+passengers?\b", req.query, flags=re.IGNORECASE)
            if not m_pax:
                m_pax = re.search(r"\b(?:we\s+are|for)\s+(\d+|two|three|four|five)\s+(?:people|travelers?|pax)\b", req.query, flags=re.IGNORECASE)
            if m_pax:
                val_str = m_pax.group(1).lower()
                word_map = {"two": 2, "three": 3, "four": 4, "five": 5}
                pax_val = word_map.get(val_str, int(val_str) if val_str.isdigit() else None)
                if pax_val and 1 <= pax_val <= 9:
                    clarify_resp = await orch.propose_clarifications(target_trip_id, {"passengers": pax_val})
                    res["proposal"] = {
                        "field": "passengers",
                        "proposed_value": pax_val,
                        "confirmation_chips": clarify_resp.get("confirmation_chips", []),
                    }
                    res["reply"] = f"I've prepared a proposal to update your trip to {pax_val} passenger(s). Please confirm this change to update your search."
                    res["action_taken"] = "PASSENGER_COUNT_PROPOSAL"

        if target_trip_id:
            res["trip_id"] = target_trip_id
        return JSONResponse(content=res)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("concierge request failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=500,
            detail="Unable to answer the concierge request.",
        ) from exc
