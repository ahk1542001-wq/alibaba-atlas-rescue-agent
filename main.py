import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from routers.v1 import flights, disruptions, bookings, concierge, claims, telemetry

app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description="TravelCare AI — Autonomous Flight Disruption Recovery & Travel Companion SaaS (Alibaba Cloud x Atlas Hackathon 2026)",
    docs_url="/api/docs",
    redoc_url="/api/redoc"
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
        "ai_engine": "Alibaba Cloud Qwen-2.5 via Qoder"
    }

@app.get("/", response_class=HTMLResponse, tags=["Frontend"])
async def serve_dashboard():
    """Serve the production multi-view SaaS web dashboard."""
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=True)
