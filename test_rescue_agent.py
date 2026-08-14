import pytest
import asyncio
from services.atlas_client import AtlasClient
from services.rescue_engine import RescueEngine
from services.state_graph import DisruptionRecoveryDAG
from services.verifiers import DisruptionVerifierEngine

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
    assert "predictive_radar" in res
    assert "dag_telemetry" in res
    assert res["predictive_radar"]["predicted_cancellation_risk_percent"] == 88
    
    types = [p["package_type"] for p in res["rescue_packages"]]
    assert "FASTEST_RECOVERY" in types
    assert "BEST_VALUE" in types
    assert "DIRECT_COMFORT" in types

@pytest.mark.asyncio
async def test_state_graph_dag_execution():
    dag = DisruptionRecoveryDAG()
    dag.record_step("IngestionRadar", 8.2)
    dag.record_step("PredictiveEvaluator", 14.5)
    dag.record_step("DisruptionConfirmed", 11.0)
    dag.record_step("ParetoOptimizer", 14.8)
    dag.record_step("FareLockHold", 38.0)
    dag.record_step("PassengerDecision", 12.0)
    dag.record_step("TicketSettlement", 45.0)
    dag.record_step("AncillarySync", 22.0)
    dag.record_step("ClosedLoopVerified", 5.0)

    telemetry = dag.get_graph_telemetry()
    assert telemetry["total_nodes_executed"] == 9
    assert telemetry["is_closed_loop_complete"] is True
    assert telemetry["total_dag_latency_ms"] > 0

@pytest.mark.asyncio
async def test_deterministic_verifiers_suite():
    # 1. FareLock Contract
    fare_v = DisruptionVerifierEngine.verify_fare_lock_contract(
        "off_atlas_mai_801", 145.0, {"verified": True, "fare_lock_expires_in_seconds": 900}
    )
    assert fare_v["passed"] is True

    # 2. Seat Conflict
    seat_v = DisruptionVerifierEngine.verify_seat_no_conflict("11B", ["11A", "11C", "11F"])
    assert seat_v["passed"] is True
    seat_fail = DisruptionVerifierEngine.verify_seat_no_conflict("11A", ["11A", "11C"])
    assert seat_fail["passed"] is False

    # 3. Baggage Continuity
    bag_v = DisruptionVerifierEngine.verify_baggage_continuity("ATLAS-45BAE5", "BKK-45BA-8921", "8M 336")
    assert bag_v["passed"] is True

    # 4. Regulatory Payout
    payout_v = DisruptionVerifierEngine.verify_regulatory_payout("Aircraft Hydraulic Maintenance", 3.0)
    assert payout_v["passed"] is True
    assert payout_v["eligible_amount_usd"] == 250.0

@pytest.mark.asyncio
async def test_self_healing_fault_injection_loop():
    client = AtlasClient()
    engine = RescueEngine(client)
    res = await engine.execute_self_healing_recovery("TG303", "Aung Hein Kyaw")
    assert res["status"] == "SELF_HEALING_COMPLETED"
    assert "TG 307" in res["healed_flight_assigned"]
    assert res["assigned_seat"] == "14A (Star Alliance Priority)"
    assert res["dag_telemetry"]["total_nodes_executed"] >= 6

@pytest.mark.asyncio
async def test_predictive_radar_and_diff():
    client = AtlasClient()
    engine = RescueEngine(client)
    radar = engine.get_predictive_radar("TG303")
    assert radar["lead_time_advantage_minutes"] == 45
    assert radar["inbound_aircraft_tail"].startswith("HS-TKF")

    diff = engine.generate_flight_diff("TG303", "8M336")
    assert diff["original_flight"] == "TG303"
    assert diff["rescue_flight"] == "8M336"
    assert diff["queue_time_saved_minutes"] == 190

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
async def test_agent_prompt_telemetry_and_token_economics():
    client = AtlasClient()
    engine = RescueEngine(client)
    telemetry = engine.get_agent_prompt_telemetry()
    assert "Qwen-2.5" in telemetry["model"]
    assert "token_economics" in telemetry
    assert telemetry["token_economics"]["cost_usd_per_recovery"] == 0.0018
    assert len(telemetry["verifier_suite"]) == 4
    assert telemetry["inference_latency_ms"] < 50
