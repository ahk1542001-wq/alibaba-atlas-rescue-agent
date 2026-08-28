import asyncio

import httpx

from main import app
from routers.v1 import concierge, disruptions, flights


class ExplodingAtlas:
    async def search_flights(self, **kwargs):
        raise RuntimeError("SENTINEL_PROVIDER_SECRET")


class ExplodingEngine:
    async def answer_concierge(self, query):
        raise RuntimeError("SENTINEL_PROVIDER_SECRET")

    async def handle_disruption(self, **kwargs):
        raise RuntimeError("SENTINEL_PROVIDER_SECRET")

    async def execute_self_healing_recovery(self, flight_number, passenger):
        raise RuntimeError("SENTINEL_PROVIDER_SECRET")


async def post(path, payload=None, params=None):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post(path, json=payload, params=params)


def test_flight_search_error_is_generic(monkeypatch):
    monkeypatch.setattr(flights, "atlas_client", ExplodingAtlas())
    response = asyncio.run(post("/api/flights/search", {
        "origin": "BKK",
        "destination": "SIN",
    }))

    assert response.status_code == 502
    assert response.json()["detail"] == "Unable to search flights in Atlas Sandbox."
    assert "SENTINEL_PROVIDER_SECRET" not in response.text


def test_concierge_error_is_generic(monkeypatch):
    monkeypatch.setattr(concierge, "rescue_engine", ExplodingEngine())
    response = asyncio.run(post("/api/chat/concierge", {"query": "help"}))

    assert response.status_code == 500
    assert response.json()["detail"] == "Unable to answer the concierge request."
    assert "SENTINEL_PROVIDER_SECRET" not in response.text


def test_disruption_errors_are_generic(monkeypatch):
    monkeypatch.setattr(disruptions, "rescue_engine", ExplodingEngine())
    analyze = asyncio.run(post("/api/disruption/analyze", {
        "flight_number": "TG303",
        "passenger_name": "Demo Traveler",
    }))
    self_heal = asyncio.run(post(
        "/api/disruption/self-heal",
        params={"flight_number": "TG303", "passenger": "Demo Traveler"},
    ))

    assert analyze.status_code == 500
    assert analyze.json()["detail"] == "Unable to analyze the disruption."
    assert self_heal.status_code == 500
    assert self_heal.json()["detail"] == "Unable to run self-healing recovery."
    assert "SENTINEL_PROVIDER_SECRET" not in analyze.text + self_heal.text


def test_unknown_flight_cannot_generate_a_recovery_plan():
    response = asyncio.run(post("/api/disruption/analyze", {
        "flight_number": "ZZ999",
        "passenger_name": "Demo Traveler",
        "date": "2030-01-01",
    }))

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Flight status unavailable in Atlas Sandbox; no recovery plan was created."
    )
    assert "BKK" not in response.text
    assert "RGN" not in response.text
