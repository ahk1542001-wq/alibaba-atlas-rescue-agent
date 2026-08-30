"""Tests for Gate G5: Fare Price Increase Reapproval and Idempotent Resolution."""

import pytest
import asyncio
import json
from models.schemas import ApprovalRequest, FlightOption, FlightEndpoint, Money
from services.atlas_client import AtlasClient, AtlasMalformedResponseError
from services.skills.flight_book import FlightBookSkill
from services.skills.base import SkillError
from routers.v1.trip import TripOrchestrator, TripApiError


class FakeAtlasWithPriceChanges:
    def __init__(self, price_change="unchanged", new_price=245.0):
        self.price_change = price_change
        self.new_price = new_price
        self.order_calls = 0
        self.order_payloads = []
        self.verify_calls = 0
        self.confirm_calls = []

    async def search_flights(self, origin, destination, date_, passengers=1, **kwargs):
        return [{
            "offer_id": "opt_test", "airline_code": "SQ",
            "airline": "Singapore Airlines", "flight_number": "SQ712",
            "origin": origin, "destination": destination,
            "departure_time": f"{date_} 09:30",
            "arrival_time": f"{date_} 11:00",
            "duration_minutes": 150, "price_usd": 210.0, "currency": "USD",
        }]

    async def verify_fare(self, offer_id: str):
        self.verify_calls += 1
        if self.price_change == "increased":
            return {
                "verified": False,
                "price_change": "increased",
                "price_confirmation_required": True,
                "booking_id": "bkg_new_ctx_123",
                "previous_price": 210.0,
                "current_price": self.new_price,
                "currency": "USD",
                "verified_at": "2026-09-28T10:00:00Z",
            }
        if self.price_change == "decreased":
            return {
                "verified": True,
                "price_change": "decreased",
                "price_confirmation_required": False,
                "booking_id": "bkg_ctx_123",
                "previous_price": 210.0,
                "current_price": 190.0,
                "currency": "USD",
                "verified_at": "2026-09-28T10:00:00Z",
            }
        return {
            "verified": True,
            "price_change": "unchanged",
            "price_confirmation_required": False,
            "booking_id": "bkg_ctx_123",
            "previous_price": 210.0,
            "current_price": 210.0,
            "currency": "USD",
            "verified_at": "2026-09-28T10:00:00Z",
        }

    async def confirm_price(self, booking_id: str):
        self.confirm_calls.append(booking_id)
        return {
            "verified": True,
            "price_change": "increased",
            "price_confirmation_required": False,
            "price_confirmed": True,
            "booking_id": booking_id,
            "previous_price": 210.0,
            "current_price": self.new_price,
            "currency": "USD",
            "verified_at": "2026-09-28T10:00:30Z",
        }

    async def create_booking_order(self, booking_id, traveler):
        self.order_calls += 1
        self.order_payloads.append((booking_id, traveler))
        return {
            "pnr": "PNR12345",
            "order_id": "ORD987",
            "status": "CONFIRMED",
            "booking_timestamp": "2026-09-28T10:01:00Z",
        }


def _dummy_option(price_amt=210.0):
    return {
        "id": "opt_test",
        "carrier": "SQ",
        "flight_no": "SQ712",
        "dep": {"airport": "BKK", "time": "2026-09-28 09:30"},
        "arr": {"airport": "SIN", "time": "2026-09-28 11:00"},
        "duration_min": 150,
        "price": {"amount": price_amt, "currency": "USD"},
        "sandbox_provenance": True,
    }


def test_official_price_confirmation_envelope_reaches_reapproval_state(
        monkeypatch):
    envelope = {
        "status": "action_required",
        "code": "PRICE_CONFIRMATION_REQUIRED",
        "data": {
            "booking_id": "bkg_price_ctx_123",
            "previous_price": 210.0,
            "current_price": 250.0,
            "currency": "USD",
            "price_change": "increased",
            "requirements": {"required": []},
            "travelers": [{"traveler_id": "trav_1", "type": "adult"}],
            "segments": [{"segment_id": "seg_1"}],
        },
    }

    class FakeProcess:
        async def communicate(self):
            return json.dumps(envelope).encode(), b""

    async def fake_subprocess(*_args, **_kwargs):
        return FakeProcess()

    monkeypatch.setattr("services.atlas_client.shutil.which",
                        lambda _name: "/atlas-flight")
    monkeypatch.setattr(
        "services.atlas_client.asyncio.create_subprocess_exec",
        fake_subprocess,
    )

    result = asyncio.run(AtlasClient().verify_fare("offer_opaque_1"))

    assert result["booking_id"] == "bkg_price_ctx_123"
    assert result["price_confirmation_required"] is True
    assert result["verified"] is False


def test_confirm_price_preserves_opaque_booking_id_and_official_command(
        monkeypatch):
    calls = []
    opaque_id = "bkg_Aa9_-opaque.123"

    async def fake_run_cli(_self, args):
        calls.append(args)
        return {
            "booking_id": opaque_id,
            "previous_price": 210.0,
            "current_price": 250.0,
            "currency": "USD",
            "price_change": "increased",
        }

    monkeypatch.setattr(AtlasClient, "_run_cli", fake_run_cli)
    result = asyncio.run(AtlasClient().confirm_price(opaque_id))

    assert calls == [[
        "booking", "confirm-price", "--booking-id", opaque_id,
    ]]
    assert result["booking_id"] == opaque_id
    assert result["price_confirmed"] is True
    assert result["price_confirmation_required"] is False


@pytest.mark.parametrize("current_price,currency", [
    (250.0, None),
    (None, "USD"),
    (float("nan"), "USD"),
    (250.0, "BTC"),
])
def test_confirm_price_rejects_missing_or_nonfinite_money_before_order(
        monkeypatch, current_price, currency):
    async def fake_run_cli(_self, _args):
        return {
            "booking_id": "bkg_money_contract",
            "current_price": current_price,
            "currency": currency,
            "price_change": "increased",
        }

    monkeypatch.setattr(AtlasClient, "_run_cli", fake_run_cli)

    with pytest.raises(AtlasMalformedResponseError):
        asyncio.run(AtlasClient().confirm_price("bkg_money_contract"))


def test_confirmed_price_must_match_server_bound_approval_snapshot():
    fake = FakeAtlasWithPriceChanges(price_change="increased", new_price=300.0)
    skill = FlightBookSkill(atlas=fake)

    with pytest.raises(SkillError) as exc_info:
        asyncio.run(skill.run({
            "trip_id": "t-price-mismatch",
            "option_id": "opt_test",
            "origin": "BKK",
            "destination": "SIN",
            "option": _dummy_option(210.0),
            "confirmed_price_snapshot": {
                "booking_id": "bkg_bound_250",
                "offer_id": "opt_test",
                "amount": 250.0,
                "currency": "USD",
            },
        }, context={
            "visa_check": {
                "freshness_state": "fresh",
                "visa_blocked": False,
                "passport_unknown": False,
            },
        }))

    assert exc_info.value.code == "fare_price_increased"
    assert exc_info.value.details["previous_price"] == 250.0
    assert exc_info.value.details["current_price"] == 300.0
    assert fake.confirm_calls == ["bkg_bound_250"]
    assert fake.order_calls == 0


def test_unchanged_price_proceeds_to_booking():
    fake = FakeAtlasWithPriceChanges(price_change="unchanged")
    skill = FlightBookSkill(atlas=fake)
    res = asyncio.run(skill.run({
        "trip_id": "t1",
        "option_id": "opt_test",
        "origin": "BKK",
        "destination": "SIN",
        "option": _dummy_option(210.0),
    }, context={
        "visa_check": {"freshness_state": "fresh", "visa_blocked": False, "passport_unknown": False},
    }))
    assert res["pnr"] == "PNR12345"
    assert res["status"] == "CONFIRMED"


def test_price_decrease_proceeds_with_real_notice():
    fake = FakeAtlasWithPriceChanges(price_change="decreased")
    skill = FlightBookSkill(atlas=fake)
    res = asyncio.run(skill.run({
        "trip_id": "t1",
        "option_id": "opt_test",
        "origin": "BKK",
        "destination": "SIN",
        "option": _dummy_option(210.0),
    }, context={
        "visa_check": {"freshness_state": "fresh", "visa_blocked": False, "passport_unknown": False},
    }))
    assert res["pnr"] == "PNR12345"
    assert res["notice"] is not None
    assert "decreased" in res["notice"].lower()
    assert "190" in res["notice"]


def test_price_increase_in_orchestrator_creates_immutable_approval_and_zero_orders(tmp_path):
    from services.profile_store import ProfileStore
    from services.web_intel_client import WebIntelClient
    from tests.test_e2e_trip_journey import _fresh_fetcher

    store = ProfileStore(root=tmp_path)
    store.get_or_create("user_price_test")
    store.set_field("user_price_test", "passport_country", "MM", source="user")

    web = WebIntelClient(ddg_fetcher=_fresh_fetcher(), tavily_api_key="", serper_api_key="")
    fake_atlas = FakeAtlasWithPriceChanges(price_change="increased", new_price=250.0)
    orch = TripOrchestrator(profile_store=store, atlas=fake_atlas, web_intel=web, llm_chat=None)

    async def flow():
        # 1. Start trip
        start_res = await orch.start(
            "Find and book a flight from BKK to SIN on 2026-09-28 for 1 person, flights only",
            user_id="user_price_test",
            search_confirmed=True,
        )
        trip_id = start_res if isinstance(start_res, str) else start_res["trip_id"]

        # If paused on scope clarification, resolve it
        state0 = orch.state(trip_id)
        if state0["status"] == "awaiting_approval" and state0["pending_approvals"] and state0["pending_approvals"][0]["node_name"] == "scope_clarification":
            scope_app_id = state0["pending_approvals"][0]["approval_id"]
            await orch.resolve(
                trip_id=trip_id,
                approval_id=scope_app_id,
                decision="flight_plus_booking",
                value={"choice": "flight_plus_booking"},
            )

        # 2. Verify it reached initial booking approval
        state1 = orch.state(trip_id)
        assert state1["status"] == "awaiting_approval"
        assert len(state1["pending_approvals"]) == 1
        init_app = state1["pending_approvals"][0]
        assert init_app["node_name"] == "approve_booking"
        init_app_id = init_app["approval_id"]
        first_opt = init_app["options"][0]
        opt_id = first_opt.get("id") or first_opt.get("offer_id")

        # 3. Resolve initial booking approval
        resolve_res = await orch.resolve(
            trip_id=trip_id,
            approval_id=init_app_id,
            decision="approve",
            value={"option_id": opt_id},
            idempotency_key="idemp_key_1",
        )

        # 4. Assert trip state is awaiting_approval with brand new price reapproval request
        state2 = orch.state(trip_id)
        assert state2["status"] == "awaiting_approval"
        assert len(state2["pending_approvals"]) == 1
        reapp = state2["pending_approvals"][0]
        assert reapp["approval_id"] != init_app_id
        assert reapp["purpose"] == "price_reapproval"
        assert reapp["is_price_increase"] is True
        assert reapp["old_price"]["amount"] == 210.0
        assert reapp["new_price"]["amount"] == 250.0
        assert "increased" in reapp["consequence"].lower()
        assert fake_atlas.order_calls == 0

        # 5. Resolving old approval ID is rejected
        with pytest.raises(TripApiError) as exc_info:
            await orch.resolve(
                trip_id=trip_id,
                approval_id=init_app_id,
                decision="approve",
                value={"option_id": opt_id},
                idempotency_key="idemp_key_2",
            )
        assert exc_info.value.code in ("unknown_approval", "already_resolved")

        # 6. Resolving with foreign trip ID is rejected
        with pytest.raises(TripApiError) as exc_info2:
            await orch.resolve(
                trip_id="foreign_trip_id",
                approval_id=reapp["approval_id"],
                decision="approve",
                value={"option_id": opt_id},
                idempotency_key="idemp_key_3",
            )
        assert exc_info2.value.code == "unknown_trip"

        # 7. Resolving with tampered/unknown option ID is rejected
        with pytest.raises(TripApiError) as exc_info3:
            await orch.resolve(
                trip_id=trip_id,
                approval_id=reapp["approval_id"],
                decision="approve",
                value={"option_id": "tampered_unknown_opt"},
                idempotency_key="idemp_key_4",
            )
        assert exc_info3.value.code == "unknown_option"

        # 8. Resolving the new approval confirms the bound booking context,
        # then creates exactly one order without re-verifying the offer.
        res_final = await orch.resolve(
            trip_id=trip_id,
            approval_id=reapp["approval_id"],
            decision="approve",
            value={"option_id": opt_id},
            idempotency_key="idemp_key_5",
        )
        state_final = orch.state(trip_id)
        assert state_final["status"] == "completed"
        assert fake_atlas.verify_calls == 1
        assert fake_atlas.confirm_calls == ["bkg_new_ctx_123"]
        assert fake_atlas.order_calls == 1
        booking = state_final["outputs"]["booking"]["booking"]
        assert booking["option"]["price"] == {
            "amount": 250.0, "currency": "USD"}
        assert fake_atlas.order_payloads == [(
            "bkg_new_ctx_123", {"name": "", "price_usd": 250.0})]

        # 9. Replay with same idempotency key returns exact same result
        res_replay = await orch.resolve(
            trip_id=trip_id,
            approval_id=reapp["approval_id"],
            decision="approve",
            value={"option_id": opt_id},
            idempotency_key="idemp_key_5",
        )
        assert res_replay["status"] == res_final["status"]
        assert fake_atlas.order_calls == 1

    asyncio.run(flow())
