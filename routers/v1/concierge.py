from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from models.schemas import ConciergeQuery
from services.atlas_client import AtlasClient
from services.rescue_engine import RescueEngine

router = APIRouter(prefix="/api/chat", tags=["Concierge"])
atlas_client = AtlasClient()
rescue_engine = RescueEngine(atlas_client)

@router.post("/concierge")
async def chat_concierge(req: ConciergeQuery):
    """AI Travel Concierge endpoint for real-time passenger assistance."""
    try:
        res = await rescue_engine.answer_concierge(req.query)
        return JSONResponse(content=res)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
