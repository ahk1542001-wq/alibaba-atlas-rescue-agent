import pytest
import asyncio
from services.atlas_client import AtlasClient
from services.rescue_engine import RescueEngine

@pytest.mark.asyncio
async def test_atlas_client_search():
    client = AtlasClient()
    flights = await client.search_flights("BKK", "RGN", "2026-08-20")
    assert len(flights) >= 3
    assert any(f["airline_code"] == "8M" for f in flights)

@pytest.mark.asyncio
async def test_multi_currency_search():
    client = AtlasClient()
    flights_thb = await client.search_flights("BKK", "RGN", "2026-08-20", currency="THB")
    assert len(flights_thb) >= 3
    assert flights_thb[0]["currency"] == "THB"
    assert flights_thb[0]["price_converted"] > flights_thb[0]["price_usd"]

@pytest.mark.asyncio
async def test_rescue_engine_curation():
    client = AtlasClient()
    engine = RescueEngine(client)
    res = await engine.handle_disruption("TG303", passenger_name="Aung Hein Kyaw", date="2026-08-20")
    
    assert res["status"] == "PACKAGES_READY_FOR_CONFIRMATION"
    assert len(res["rescue_packages"]) == 3
    
    types = [p["package_type"] for p in res["rescue_packages"]]
    assert "FASTEST_RECOVERY" in types
    assert "BEST_VALUE" in types
    assert "DIRECT_COMFORT" in types

@pytest.mark.asyncio
async def test_booking_settlement():
    client = AtlasClient()
    booking = await client.create_booking_order(
        offer_id="off_atlas_mai_801",
        passenger={"name": "Aung Hein Kyaw", "passport": "MB123456", "price_usd": 145.00},
        seat_selected="12A"
    )
    assert booking["status"] == "CONFIRMED"
    assert booking["pnr"].startswith("ATLAS-")
    assert "ticket_number" in booking
    assert booking["seat_assigned"] == "12A"

@pytest.mark.asyncio
async def test_concierge_assistant():
    client = AtlasClient()
    engine = RescueEngine(client)
    res = await engine.answer_concierge("Can I request a vegetarian meal?")
    assert "Vegetarian" in res["reply"]
    assert res["action_taken"] == "MEAL_PREFERENCE_UPDATED"

    res_bag = await engine.answer_concierge("Where is my baggage?")
    assert "Baggage" in res_bag["reply"]
    assert res_bag["action_taken"] == "BAGGAGE_TRACKING_RETRIEVED"

@pytest.mark.asyncio
async def test_compensation_claim_generation():
    client = AtlasClient()
    engine = RescueEngine(client)
    disruption = await client.get_flight_status("TG303", "2026-08-20")
    claim = engine.generate_compensation_claim(disruption, "Aung Hein Kyaw")
    assert claim["eligible_payout_usd"] == 250.0
    assert claim["status"] == "PRE_SUBMITTED_BY_AGENT"
    assert claim["passenger_name"] == "Aung Hein Kyaw"

@pytest.mark.asyncio
async def test_agent_prompt_telemetry():
    client = AtlasClient()
    engine = RescueEngine(client)
    telemetry = engine.get_agent_prompt_telemetry()
    assert "Qwen-2.5" in telemetry["model"]
    assert "pareto_weights" in telemetry
    assert telemetry["inference_latency_ms"] < 50
