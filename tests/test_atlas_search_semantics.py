"""Tests for Gate G4: Atlas Search Semantics, Opaque IDs, Currency Truth, and Flexible Dates."""

import pytest
import asyncio
from pydantic import ValidationError
from models.schemas import FlightSearchRequest
from services.atlas_client import AtlasClient
from services.skills.flight_search import FlightSearchSkill, normalize_offer


class FakeAtlasWithSearchVariants:
    def __init__(self, offers_by_date=None, multi_currency_offers=None):
        self.offers_by_date = offers_by_date or {}
        self.multi_currency_offers = multi_currency_offers or []
        self.searched_dates = []

    async def search_flights(self, origin, destination, date, passengers=1,
                             cabin_class="ECONOMY", currency="USD"):
        self.searched_dates.append(date)
        if self.multi_currency_offers:
            return self.multi_currency_offers
        if date in self.offers_by_date:
            return self.offers_by_date[date]
        return [
            {
                "offer_id": "OFFER_OPAQUE_ABC-123_XYZ#99",
                "search_id": "SEARCH_OPQ_987",
                "airline_code": "SQ",
                "airline": "Singapore Airlines",
                "flight_number": "SQ712",
                "origin": origin,
                "destination": destination,
                "departure_time": f"{date} 09:30",
                "arrival_time": f"{date} 11:00",
                "duration_minutes": 150,
                "price_usd": 210.0,
                "currency": "USD",
                "price_status": "live",
            }
        ]


def test_opaque_ids_preserved_exactly():
    raw_offer = {
        "offer_id": "OFFER_OPAQUE_ABC-123_XYZ#99",
        "search_id": "SEARCH_OPQ_987",
        "airline_code": "SQ",
        "flight_number": "SQ712",
        "origin": "BKK",
        "destination": "SIN",
        "departure_time": "2026-09-28 09:30",
        "arrival_time": "2026-09-28 11:00",
        "duration_minutes": 150,
        "price_usd": 210.0,
        "currency": "USD",
    }
    opt = normalize_offer(raw_offer)
    assert opt["id"] == "OFFER_OPAQUE_ABC-123_XYZ#99"
    assert opt["search_id"] == "SEARCH_OPQ_987"


def test_top_level_provider_search_id_is_bound_to_every_offer(monkeypatch):
    client = AtlasClient()

    async def provider_call(_args):
        return {
            "search_id": "SEARCH_TOP_LEVEL_123",
            "offers": [
                {"offer_id": "offer_1"},
                {"offer_id": "offer_2"},
            ],
        }

    monkeypatch.setattr(client, "_run_cli", provider_call)
    offers = asyncio.run(client.cli_search_flights(
        "BKK", "SIN", "2026-09-28", 1, "USD"))

    assert [offer["search_id"] for offer in offers] == [
        "SEARCH_TOP_LEVEL_123", "SEARCH_TOP_LEVEL_123"]


def test_mixed_currencies_grouped_or_not_falsely_equated():
    offers = [
        {
            "offer_id": "off_thb",
            "airline_code": "TG",
            "flight_number": "TG1",
            "origin": "BKK",
            "destination": "SIN",
            "departure_time": "2026-09-28 10:00",
            "arrival_time": "2026-09-28 11:30",
            "duration_minutes": 150,
            "price_usd": 6800.0,
            "currency": "THB",
        },
        {
            "offer_id": "off_usd",
            "airline_code": "SQ",
            "flight_number": "SQ1",
            "origin": "BKK",
            "destination": "SIN",
            "departure_time": "2026-09-28 09:30",
            "arrival_time": "2026-09-28 11:00",
            "duration_minutes": 150,
            "price_usd": 200.0,
            "currency": "USD",
        },
    ]
    fake = FakeAtlasWithSearchVariants(multi_currency_offers=offers)
    skill = FlightSearchSkill(atlas=fake)
    res = asyncio.run(skill.run({"origin": "BKK", "destination": "SIN", "date": "2026-09-28"}))
    options = res["options"]
    assert len(options) == 2
    # Ensure currencies are preserved and grouped without numeric conflation
    currencies = [opt["price"]["currency"] for opt in options]
    assert "THB" in currencies and "USD" in currencies
    for opt in options:
        if opt["price"]["currency"] == "THB":
            assert opt["price"]["amount"] == 6800.0
        if opt["price"]["currency"] == "USD":
            assert opt["price"]["amount"] == 200.0


def test_multi_date_execution_queries_each_date():
    fake = FakeAtlasWithSearchVariants()
    skill = FlightSearchSkill(atlas=fake)
    date_window = {"start": "2026-09-28", "end": "2026-09-30"}
    res = asyncio.run(skill.run({
        "origin": "BKK",
        "destination": "SIN",
        "date_window": date_window,
    }))
    assert len(fake.searched_dates) == 3
    assert fake.searched_dates == ["2026-09-28", "2026-09-29", "2026-09-30"]
    assert len(res["options"]) >= 1


def test_multi_date_partial_failure_resilience():
    class PartialFailAtlas(FakeAtlasWithSearchVariants):
        async def search_flights(self, origin, destination, date, passengers=1, **kwargs):
            self.searched_dates.append(date)
            if date == "2026-09-29":
                from services.atlas_client import AtlasProviderError
                raise AtlasProviderError("sandbox timeout on single date")
            return await super().search_flights(origin, destination, date, passengers, **kwargs)

    fake = PartialFailAtlas()
    skill = FlightSearchSkill(atlas=fake)
    res = asyncio.run(skill.run({
        "origin": "BKK",
        "destination": "SIN",
        "date_window": {"start": "2026-09-28", "end": "2026-09-30"},
    }))
    # Does not crash on single-date provider error; returns options from successful dates
    assert len(res["options"]) >= 1
    assert "2026-09-28" in fake.searched_dates
    assert "2026-09-29" in fake.searched_dates
    assert "2026-09-30" in fake.searched_dates
    assert res["partial_failure"] is True
    assert res["failed_dates"] == ["2026-09-29"]


def test_multi_date_bounded_range_safety_cap():
    fake = FakeAtlasWithSearchVariants()
    skill = FlightSearchSkill(atlas=fake)
    # 30 day range provided
    date_window = {"start": "2026-09-01", "end": "2026-09-30"}
    res = asyncio.run(skill.run({
        "origin": "BKK",
        "destination": "SIN",
        "date_window": date_window,
    }))
    # Capped at safety max (8 dates: day 0 to 7)
    assert len(fake.searched_dates) <= 8
    assert res["date_window_truncated"] is True
    assert res["searched_dates"] == fake.searched_dates


def test_complete_passenger_totals_computed():
    fake = FakeAtlasWithSearchVariants()
    skill = FlightSearchSkill(atlas=fake)

    result = asyncio.run(skill.run({
        "origin": "BKK",
        "destination": "SIN",
        "date": "2026-09-28",
        "passengers": 3,
    }))

    option = result["options"][0]
    assert option["price_per_passenger"] == {"amount": 210.0, "currency": "USD"}
    assert option["price"] == {"amount": 630.0, "currency": "USD"}
    assert option["passenger_count"] == 3


def test_provider_trip_total_is_not_multiplied_again():
    offer = {
        "offer_id": "off_total",
        "search_id": "search_total",
        "airline_code": "SQ",
        "flight_number": "SQ712",
        "origin": "BKK",
        "destination": "SIN",
        "departure_time": "2026-09-28 09:30",
        "arrival_time": "2026-09-28 11:00",
        "duration_minutes": 150,
        "price_usd": 600.0,
        "currency": "USD",
        "price_scope": "trip_total",
        "price_status": "reference",
    }

    option = normalize_offer(offer, passengers=3)

    assert option["price"] == {"amount": 600.0, "currency": "USD"}
    assert option["price_per_passenger"] == {"amount": 200.0, "currency": "USD"}
    assert option["price_status"] == "reference"


def test_non_usd_cli_amount_uses_converted_value_without_relabeling():
    client = AtlasClient()
    raw = client._normalize_cli_offer(
        {
            "offer_id": "off_thb_total",
            "search_id": "search_thb",
            "total_price": 100.0,
            "price_status": "reference",
            "segments": [{
                "departure_airport": "BKK",
                "arrival_airport": "SIN",
                "departure_time": "202609280930",
                "arrival_time": "202609281100",
                "carrier": "SQ",
                "flight_number": "SQ712",
                "duration_minutes": 150,
            }],
        },
        rate=35.4,
        symbol="฿",
        display_currency="THB",
        passengers=2,
    )

    option = normalize_offer(raw, passengers=2)

    assert option["price"] == {"amount": 3540.0, "currency": "THB"}
    assert option["price_per_passenger"] == {
        "amount": 1770.0, "currency": "THB"}


def test_unsupported_display_currency_is_rejected_at_request_boundary():
    with pytest.raises(ValidationError):
        FlightSearchRequest(
            origin="BKK",
            destination="SIN",
            date="2026-09-28",
            currency="BTC",
        )


def test_unsupported_currency_is_rejected_before_provider_search(monkeypatch):
    client = AtlasClient()
    provider_calls = []

    async def provider_call(*_args, **_kwargs):
        provider_calls.append((_args, _kwargs))
        return []

    monkeypatch.setattr(client, "cli_search_flights", provider_call)

    with pytest.raises(ValueError, match="Unsupported display currency"):
        asyncio.run(client.search_flights(
            "BKK", "SIN", "2026-09-28", passengers=1, currency="BTC"))

    assert provider_calls == []
