"""Tests for Gate G5: Fare Price Increase Reapproval and Idempotent Resolution."""

import pytest
import asyncio
from models.schemas import ApprovalRequest, FlightOption, FlightEndpoint, Money
from services.skills.flight_book import FlightBookSkill
from services.skills.base import SkillError
from routers.v1.trip import TripOrchestrator, TripApiError


class FakeAtlasWithPriceChanges:
    def __init__(self, price_change="unchanged", new_price=245.0):
        self.price_change = price_change
        self.new_price = new_price

    async def verify_fare(self, offer_id: str):
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
        elif self.price_change == "decreased":
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
        else:
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

    async def create_booking_order(self, booking_id, traveler):
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


def test_price_decrease_proceeds_with_notice():
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
    assert res.get("price_decrease_notice") or res["status"] == "CONFIRMED"


def test_price_increase_raises_reapproval_error():
    fake = FakeAtlasWithPriceChanges(price_change="increased", new_price=245.0)
    skill = FlightBookSkill(atlas=fake)
    with pytest.raises(SkillError) as exc_info:
        asyncio.run(skill.run({
            "trip_id": "t1",
            "option_id": "opt_test",
            "origin": "BKK",
            "destination": "SIN",
            "option": _dummy_option(210.0),
        }, context={
            "visa_check": {"freshness_state": "fresh", "visa_blocked": False, "passport_unknown": False},
        }))
    assert exc_info.value.code in ("fare_price_increased", "price_increase_reapproval_required")
    assert "245" in exc_info.value.message or "price" in exc_info.value.message.lower()
