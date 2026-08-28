import asyncio
import json

import httpx
import pytest

from main import app
from routers.v1 import bookings, disruptions
from services.atlas_client import (
    AtlasClient,
    AtlasMalformedResponseError,
    AtlasSandboxUnavailableError,
    AtlasTicketingUnavailableError,
)
from services.skills.base import SkillError
from services.skills.flight_book import FlightBookSkill
from services.skills.flight_search import FlightSearchSkill
from services.rescue_engine import RescueEngine


def run(coro):
    return asyncio.run(coro)


def test_search_fails_closed_when_sandbox_returns_no_offers(monkeypatch):
    client = AtlasClient()

    async def unavailable(**_kwargs):
        return []

    monkeypatch.setattr(client, "cli_search_flights", unavailable)

    with pytest.raises(AtlasSandboxUnavailableError) as exc:
        run(client.search_flights("BKK", "SIN", "2030-01-01"))

    assert "off_atlas_" not in str(exc.value)


def test_search_filters_provider_city_expansion_to_exact_airports(monkeypatch):
    client = AtlasClient()

    async def provider_results(**_kwargs):
        return [
            {
                "offer_id": "off_live_bkk",
                "currency": "USD",
                "total_price": 111.57,
                "price_status": "reference",
                "bookable": False,
                "segments": [{
                    "departure_airport": "BKK",
                    "arrival_airport": "SIN",
                    "departure_time": "203001011525",
                    "arrival_time": "203001011855",
                    "carrier": "TR",
                    "flight_number": "TR639",
                    "duration_minutes": 150,
                    "cabin_class": 1,
                    "direction": "outbound",
                }],
            },
            {
                "offer_id": "off_live_dmk",
                "currency": "USD",
                "total_price": 98.51,
                "price_status": "reference",
                "bookable": False,
                "segments": [{
                    "departure_airport": "DMK",
                    "arrival_airport": "SIN",
                    "departure_time": "203001011040",
                    "arrival_time": "203001011405",
                    "carrier": "FD",
                    "flight_number": "FD357",
                    "duration_minutes": 145,
                    "cabin_class": 1,
                    "direction": "outbound",
                }],
            },
        ]

    monkeypatch.setattr(client, "cli_search_flights", provider_results)
    offers = run(client.search_flights("BKK", "SIN", "2030-01-01"))

    assert [offer["offer_id"] for offer in offers] == ["off_live_bkk"]
    assert offers[0]["origin"] == "BKK"
    assert offers[0]["destination"] == "SIN"


def test_search_never_fabricates_a_missing_provider_offer_id(monkeypatch):
    client = AtlasClient()

    async def malformed_result(**_kwargs):
        return [{
            "offer_id": "",
            "currency": "USD",
            "total_price": 111.57,
            "segments": [{
                "departure_airport": "BKK",
                "arrival_airport": "SIN",
                "departure_time": "203001011525",
                "arrival_time": "203001011855",
                "carrier": "TR",
                "flight_number": "TR639",
                "duration_minutes": 150,
                "cabin_class": 1,
                "direction": "outbound",
            }],
        }]

    monkeypatch.setattr(client, "cli_search_flights", malformed_result)

    with pytest.raises(AtlasMalformedResponseError):
        run(client.search_flights("BKK", "SIN", "2030-01-01"))


def test_fare_verification_uses_atlas_cli_booking_context(monkeypatch):
    client = AtlasClient()
    calls = []

    async def provider_call(args):
        calls.append(args)
        return {
            "booking_id": "book_sandbox_123",
            "previous_price": 111.57,
            "current_price": 111.57,
            "currency": "USD",
            "price_change": "unchanged",
            "requirements": {"required": []},
            "travelers": [{"traveler_id": "traveler_1", "type": "adult"}],
            "segments": [{"segment_id": "segment_1"}],
            "baggage_supported": True,
            "seat_supported": True,
        }

    monkeypatch.setattr(client, "_run_cli", provider_call)
    result = run(client.verify_fare("off_live_bkk"))

    assert calls == [["offer", "verify", "--offer-id", "off_live_bkk"]]
    assert result["verified"] is True
    assert result["offer_id"] == "off_live_bkk"
    assert result["booking_id"] == "book_sandbox_123"
    assert result["price_change"] == "unchanged"


def test_offer_verification_maps_ticketing_activation_blocker(monkeypatch):
    client = AtlasClient()
    envelope = {
        "status": "action_required",
        "code": "SUBSCRIPTION_REQUIRED",
        "message": "provider detail must not leak",
        "data": {},
        "details": {"ticketing_blocker": "TICKETING_ACTIVATION_REQUIRED"},
    }

    class FakeProcess:
        async def communicate(self):
            return json.dumps(envelope).encode(), b""

    async def fake_subprocess(*_args, **_kwargs):
        return FakeProcess()

    monkeypatch.setattr("services.atlas_client.shutil.which", lambda _name: "/atlas-flight")
    monkeypatch.setattr(
        "services.atlas_client.asyncio.create_subprocess_exec", fake_subprocess
    )

    with pytest.raises(AtlasTicketingUnavailableError) as exc:
        run(client.verify_fare("off_live_bkk"))

    assert exc.value.code == "TICKETING_ACTIVATION_REQUIRED"
    assert "provider detail" not in str(exc.value)


def test_booking_never_fabricates_pnr_when_ticketing_is_unavailable(monkeypatch):
    client = AtlasClient()

    async def provider_call(args):
        assert args == ["auth", "status"]
        return {
            "authenticated": True,
            "search_available": True,
            "ticketing_available": False,
            "ticketing_blocker": "TICKETING_ACTIVATION_REQUIRED",
        }

    monkeypatch.setattr(client, "_run_cli", provider_call)

    with pytest.raises(AtlasTicketingUnavailableError) as exc:
        run(client.create_booking_order(
            "book_sandbox_123",
            {"name": "Demo Traveler", "price_usd": 111.57},
        ))

    assert "ATLAS-" not in str(exc.value)


def test_status_without_provider_capability_is_unknown_not_demo_fixture():
    status = run(AtlasClient().get_flight_status("TG303", "2030-01-01"))

    assert status == {
        "flight_number": "TG303",
        "airline_code": "TG",
        "status": "UNKNOWN",
        "reason": "Flight status is not available from the Atlas Sandbox CLI",
    }


def test_flight_search_skill_surfaces_recoverable_sandbox_error():
    class UnavailableAtlas:
        async def search_flights(self, *args, **kwargs):
            raise AtlasSandboxUnavailableError(
                "ATLAS_REQUEST_FAILED",
                "Atlas Sandbox request could not be completed.",
            )

    with pytest.raises(SkillError) as exc:
        run(FlightSearchSkill(UnavailableAtlas()).run({
            "origin": "BKK",
            "destination": "SIN",
            "date": "2030-01-01",
            "passengers": 1,
        }))

    assert exc.value.code == "atlas_sandbox_unavailable"
    assert exc.value.recoverable is True


def test_flight_book_skill_surfaces_ticketing_activation_without_fake_pnr():
    class TicketingDisabledAtlas:
        async def verify_fare(self, offer_id):
            return {
                "verified": True,
                "offer_id": offer_id,
                "booking_id": "book_sandbox_123",
                "verified_at": "2030-01-01T00:00:00+00:00",
            }

        async def create_booking_order(self, booking_id, passenger, **kwargs):
            assert booking_id == "book_sandbox_123"
            raise AtlasTicketingUnavailableError(
                "TICKETING_ACTIVATION_REQUIRED",
                "Atlas Sandbox ticketing is not activated for this account.",
            )

    with pytest.raises(SkillError) as exc:
        run(FlightBookSkill(TicketingDisabledAtlas()).run({
            "trip_id": "trip_demo",
            "option_id": "off_live_bkk",
            "origin": "BKK",
            "destination": "CNX",
            "passenger": {"name": "Demo Traveler"},
        }))

    assert exc.value.code == "atlas_ticketing_unavailable"
    assert exc.value.recoverable is True
    assert "ATLAS-" not in str(exc.value)


def test_flight_book_skill_maps_ticketing_block_during_fare_verification():
    class VerificationBlockedAtlas:
        async def verify_fare(self, _offer_id):
            raise AtlasTicketingUnavailableError(
                "TICKETING_ACTIVATION_REQUIRED",
                "Atlas Sandbox ticketing is not activated for this account.",
            )

    with pytest.raises(SkillError) as exc:
        run(FlightBookSkill(VerificationBlockedAtlas()).run({
            "trip_id": "trip_demo",
            "option_id": "off_live_bkk",
            "origin": "BKK",
            "destination": "CNX",
            "passenger": {"name": "Demo Traveler"},
        }))

    assert exc.value.code == "atlas_ticketing_unavailable"
    assert exc.value.recoverable is True


def test_legacy_booking_route_reports_ticketing_activation_without_fake_pnr(
    monkeypatch,
):
    class TicketingDisabledAtlas:
        async def verify_fare(self, offer_id):
            return {
                "verified": True,
                "offer_id": offer_id,
                "booking_id": "book_sandbox_123",
            }

        async def create_booking_order(self, booking_id, passenger, **kwargs):
            assert booking_id == "book_sandbox_123"
            raise AtlasTicketingUnavailableError(
                "TICKETING_ACTIVATION_REQUIRED",
                "Atlas Sandbox ticketing is not activated for this account.",
            )

    monkeypatch.setattr(bookings, "atlas_client", TicketingDisabledAtlas())

    async def post_booking():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            return await client.post(
                "/api/rescue/book",
                headers={"Idempotency-Key": "ticketing-disabled-1"},
                json={
                    "offer_id": "off_live_bkk",
                    "passenger_name": "Demo Traveler",
                    "price_usd": 111.57,
                },
            )

    response = run(post_booking())

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Atlas Sandbox ticketing is not activated; no booking or PNR was created."
    )
    assert "ATLAS-" not in response.text


def test_health_reports_sandbox_only_without_mock_mode():
    async def get_health():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            return await client.get("/api/health")

    response = run(get_health())
    body = response.json()

    assert response.status_code == 200
    assert body["atlas_mode"] == "sandbox_only"
    assert body["atlas_provider"] == "atlas-flight CLI"
    assert "mock_mode" not in body


def test_explicit_disruption_simulation_never_calls_atlas_provider(monkeypatch):
    client = AtlasClient()

    async def provider_call_forbidden(*_args, **_kwargs):
        pytest.fail("explicit demo simulation must not call Atlas Sandbox")

    monkeypatch.setattr(client, "_run_cli", provider_call_forbidden)
    result = run(RescueEngine(client).handle_disruption(
        flight_number="TG303",
        passenger_name="Demo Traveler",
        date="2030-01-01",
        currency="USD",
        nationality="MM",
        simulation=True,
    ))

    assert result["provenance"] == "explicit_demo_simulation"
    assert result["disruption"]["status"] == "CANCELLED"
    assert result["fare_lock"]["simulated"] is True


def test_disruption_api_requires_explicit_simulation_gate(monkeypatch):
    calls = []

    class CapturingEngine:
        async def handle_disruption(self, **kwargs):
            calls.append(kwargs)
            return {"provenance": "explicit_demo_simulation"}

    monkeypatch.setattr(disruptions, "rescue_engine", CapturingEngine())

    async def post(allow_sim):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post(
                "/api/disruption/analyze",
                params={"allow_sim": allow_sim},
                json={
                    "flight_number": "TG303",
                    "passenger_name": "Demo Traveler",
                    "date": "2030-01-01",
                },
            )

    response = run(post("true"))

    assert response.status_code == 200
    assert response.json()["provenance"] == "explicit_demo_simulation"
    assert calls[0]["simulation"] is True


def test_self_healing_demo_never_returns_a_fake_pnr_or_ticket():
    result = run(RescueEngine(AtlasClient()).execute_self_healing_recovery(
        "TG303", "Demo Traveler"
    ))

    assert result["provenance"] == "explicit_demo_simulation"
    assert result["simulated"] is True
    assert result["booking_created"] is False
    assert "pnr" not in result
    assert "ticket" not in result


def test_concierge_without_session_never_invents_a_booking(monkeypatch):
    engine = RescueEngine(AtlasClient())

    async def no_llm(_query):
        return None

    monkeypatch.setattr(engine, "_qwen_concierge_reply", no_llm)
    result = run(engine.answer_concierge("What happened to my trip?"))

    assert result["action_taken"] == "NO_ACTIVE_SESSION"
    assert "rebooked" not in result["reply"].lower()
    assert "confirmed" not in result["reply"].lower()


def test_legacy_ancillary_and_graph_data_are_explicit_simulations():
    client = AtlasClient()
    baggage = run(client.get_baggage_status("DEMO-BAGGAGE"))
    seat_map = run(client.get_seat_map("DEMO-FLIGHT"))
    radar = RescueEngine(client).get_predictive_radar("DEMO-FLIGHT")

    async def get_graph():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as http:
            return await http.get("/api/graph/state")

    graph_response = run(get_graph())
    graph = graph_response.json()

    for payload in (baggage, seat_map, radar, graph):
        assert payload["provenance"] == "explicit_demo_simulation"
        assert payload["simulated"] is True
    assert "pnr" not in graph_response.text.lower()
    assert "ticket" not in graph_response.text.lower()
