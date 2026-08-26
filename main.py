import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from routers.v1 import flights, disruptions, bookings, concierge, claims, telemetry, hotels, radar
from routers.v1 import trip, profile, skills
from routers.v1.profile import TripApiError
from services.radar import get_radar
from services import llm
from services.trip_graph import GraphError

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the autonomous radar background loop on boot; stop on shutdown."""
    radar_engine = get_radar()
    radar_engine.start()
    try:
        yield
    finally:
        await radar_engine.stop()


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description="TravelCare AI — Autonomous Flight Disruption Recovery & Travel Companion SaaS (Alibaba Cloud x Atlas Hackathon 2026)",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

# Enable CORS for external client integrations
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static web directory
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Include Modular API Routers
app.include_router(flights.router)
app.include_router(disruptions.router)
app.include_router(bookings.router)
app.include_router(concierge.router)
app.include_router(claims.router)
app.include_router(telemetry.router)
app.include_router(hotels.router)
app.include_router(radar.router)
app.include_router(trip.router)
app.include_router(profile.router)
app.include_router(skills.router)


# --- shared §6 error contract for the trip/profile/skills routes ----------------
# {error:{code,message,recoverable}} — recoverable errors carry an actionable
# hint. Scoped to the v2 exception types: existing routes never raise these.

@app.exception_handler(TripApiError)
async def trip_api_error_handler(request, exc: TripApiError):
    from fastapi.responses import JSONResponse
    error = {"code": exc.code, "message": exc.message,
             "recoverable": exc.recoverable}
    if exc.hint:
        error["hint"] = exc.hint
    return JSONResponse(status_code=exc.status_code,
                        content={"error": error})


@app.exception_handler(GraphError)
async def graph_error_handler(request, exc: GraphError):
    from fastapi.responses import JSONResponse
    code_status = {"unknown_approval": 404, "already_resolved": 409,
                   "approval_expired": 410}
    status = code_status.get(exc.code, 422 if exc.recoverable else 500)
    return JSONResponse(status_code=status, content={"error": {
        "code": exc.code, "message": exc.message,
        "recoverable": exc.recoverable}})

@app.get("/api/health", tags=["Health"])
async def health_check():
    """System health check and upstream connection status."""
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": settings.version,
        "atlas_endpoint": settings.atrip_api_base,
        "mock_mode": settings.use_mock_fallback,
        "runtime": "Python 3.13 / FastAPI Async Gateway",
        "ai_engine": (
            f"{settings.default_model} via {llm.provider_name()}"
            if llm.provider_name() != "none"
            else "deterministic-fallback (no LLM configured)"
        )
    }

@app.get("/", response_class=HTMLResponse, tags=["Frontend"])
async def serve_dashboard():
    """Serve the production multi-view SaaS web dashboard."""
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=True)
