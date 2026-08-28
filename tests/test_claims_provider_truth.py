import asyncio

import httpx

from main import app
from routers.v1 import claims
from services.atlas_client import AtlasClient


class StatusAtlas:
    def __init__(self, status=None, error=None):
        self.status = status or {}
        self.error = error

    async def get_flight_status(self, flight_number, date):
        if self.error:
            raise self.error
        return dict(self.status)


async def post_assess(payload):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post("/api/claims/assess", json=payload)


def test_claim_route_ignores_spoofed_client_airports(monkeypatch):
    monkeypatch.setattr(claims, "atlas_client", StatusAtlas({
        "origin": "BKK", "destination": "RGN",
        "status": "CANCELLED", "reason": "weather", "airline": "TG",
    }))
    response = asyncio.run(post_assess({
        "flight_number": "TG303",
        "origin_airport": "CDG",
        "destination_airport": "BKK",
    }))
    assert response.status_code == 200
    route = response.json()["route"]
    assert route["origin_airport"] == "BKK"
    assert route["destination_airport"] == "RGN"


def test_unknown_atlas_status_does_not_invent_disruption_or_route():
    status = asyncio.run(AtlasClient().get_flight_status("ZZ999", "2030-01-01"))

    assert status["flight_number"] == "ZZ999"
    assert status["status"] == "UNKNOWN"
    assert status["reason"] == "Flight status unavailable in Atlas Sandbox"
    assert "origin" not in status
    assert "destination" not in status
    assert "compensation_amount_usd" not in status


def test_unknown_atlas_claim_rejects_spoofed_client_airports(monkeypatch):
    monkeypatch.setattr(claims, "atlas_client", AtlasClient())

    response = asyncio.run(post_assess({
        "flight_number": "ZZ999",
        "origin_airport": "CDG",
        "destination_airport": "BKK",
    }))

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Cannot determine true flight route from status."
    )
    assert "CDG" not in response.text
    assert "BKK" not in response.text


def test_claim_missing_provider_route_is_422_not_500(monkeypatch):
    monkeypatch.setattr(claims, "atlas_client", StatusAtlas({
        "status": "CANCELLED", "reason": "weather",
    }))
    response = asyncio.run(post_assess({
        "flight_number": "TG303",
        "origin_airport": "CDG",
        "destination_airport": "BKK",
    }))
    assert response.status_code == 422
    assert "true flight route" in response.json()["detail"]


def test_claim_provider_error_is_generic(monkeypatch):
    monkeypatch.setattr(
        claims, "atlas_client", StatusAtlas(error=RuntimeError("SENTINEL_SECRET"))
    )
    response = asyncio.run(post_assess({"flight_number": "TG303"}))
    assert response.status_code == 502
    assert "SENTINEL_SECRET" not in response.text


def test_claim_appeal_error_is_generic(monkeypatch):
    async def mock_draft_appeal(claim, rejection_reason):
        raise RuntimeError("SENTINEL_SECRET")

    monkeypatch.setattr(claims, "draft_appeal", mock_draft_appeal)

    async def post_appeal(payload):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post("/api/claims/appeal", json=payload)

    response = asyncio.run(post_appeal({
        "claim": {"flight_number": "TG303"},
        "rejection_reason": "Extraordinary circumstances",
    }))
    assert response.status_code == 500
    assert "SENTINEL_SECRET" not in response.text
    assert response.json()["detail"] == "Unable to draft the appeal."
