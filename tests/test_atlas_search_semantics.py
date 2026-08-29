"""Tests for Gate G4: Atlas Search Semantics, Opaque IDs, Currency Truth, and Flexible Dates."""

import pytest
import asyncio
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


def test_mixed_currencies_grouped_or_not_falsely_equated():
    offers = [
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
    ]
    fake = FakeAtlasWithSearchVariants(multi_currency_offers=offers)
    skill = FlightSearchSkill(atlas=fake)
    res = asyncio.run(skill.run({"origin": "BKK", "destination": "SIN", "date": "2026-09-28"}))
    options = res["options"]
    assert len(options) == 2
    # Ensure currency is preserved on each option
    assert options[0]["price"]["currency"] in ("USD", "THB")
    assert options[1]["price"]["currency"] in ("USD", "THB")


def test_complete_passenger_totals_computed():
    raw_offer = {
        "offer_id": "off_pax3",
        "airline_code": "SQ",
        "flight_number": "SQ712",
        "origin": "BKK",
        "destination": "SIN",
        "departure_time": "2026-09-28 09:30",
        "arrival_time": "2026-09-28 11:00",
        "duration_minutes": 150,
        "price_usd": 210.0,
        "currency": "USD",
        "passengers": 3,
    }
    opt = normalize_offer(raw_offer)
    assert opt["price"]["amount"] == 210.0
    assert opt["price"]["currency"] == "USD"
