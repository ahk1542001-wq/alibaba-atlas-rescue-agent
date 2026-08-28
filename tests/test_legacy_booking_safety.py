"""Regression coverage for the legacy Rescue Hub booking boundary.

The canonical trip flow already has purpose-bound approval idempotency.  The
legacy UI remains reachable, so its booking route must provide the same basic
retry safety: a required caller key, exact replay, conflict detection, one
provider call under concurrency, and a retryable failure path.
"""

import asyncio

import httpx
import pytest

from main import app
from routers.v1 import bookings


BOOKING = {
    "offer_id": "off_legacy_safe_1",
    "passenger_name": "Demo Traveler",
    "price_usd": 210.0,
    "baggage_addon": "30kg Priority Included",
    "seat_selected": "12A",
}


class CountingAtlas:
    def __init__(self, *, fail_first: bool = False, slow: bool = False,
                 verified: bool = True):
        self.fail_first = fail_first
        self.slow = slow
        self.verified = verified
        self.verify_calls = 0
        self.order_calls = 0
        self.booking_ids = []

    async def verify_fare(self, offer_id):
        self.verify_calls += 1
        return {"verified": self.verified, "offer_id": offer_id,
                "booking_id": f"book_{offer_id}"}

    async def create_booking_order(self, booking_id, passenger, **kwargs):
        self.order_calls += 1
        self.booking_ids.append(booking_id)
        if self.slow:
            await asyncio.sleep(0.05)
        if self.fail_first and self.order_calls == 1:
            raise RuntimeError("SENTINEL_PROVIDER_SECRET")
        return {
            "order_id": "ORD-LEGACY-1",
            "pnr": "ATLAS-LEG1",
            "status": "CONFIRMED",
            "booking_id": booking_id,
        }


@pytest.fixture(autouse=True)
def isolated_booking_state(monkeypatch):
    for name in ("_rescue_locks", "_rescue_booking_locks",
                 "_rescue_booking_ledger"):
        state = getattr(bookings, name, None)
        if hasattr(state, "clear"):
            state.clear()
    fake = CountingAtlas()
    monkeypatch.setattr(bookings, "atlas_client", fake)
    return fake


async def _post(payload, key=None):
    headers = {"Idempotency-Key": key} if key else {}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post("/api/rescue/book", json=payload,
                                 headers=headers)


def test_legacy_booking_requires_explicit_idempotency_key(isolated_booking_state):
    response = asyncio.run(_post(BOOKING))
    assert response.status_code == 422
    assert "Idempotency-Key" in response.json()["detail"]
    assert isolated_booking_state.order_calls == 0


def test_legacy_booking_replays_exact_response_without_second_provider_call(
    isolated_booking_state,
):
    async def flow():
        first = await _post(BOOKING, "legacy-replay-1")
        second = await _post(BOOKING, "legacy-replay-1")
        return first, second

    first, second = asyncio.run(flow())
    assert first.status_code == second.status_code == 200
    assert second.json() == first.json()
    assert isolated_booking_state.order_calls == 1
    assert isolated_booking_state.booking_ids == ["book_off_legacy_safe_1"]


def test_legacy_booking_rejects_same_key_with_altered_payload(
    isolated_booking_state,
):
    async def flow():
        first = await _post(BOOKING, "legacy-conflict-1")
        altered = {**BOOKING, "seat_selected": "14C"}
        second = await _post(altered, "legacy-conflict-1")
        return first, second

    first, second = asyncio.run(flow())
    assert first.status_code == 200
    assert second.status_code == 409
    assert "different booking payload" in second.json()["detail"]
    assert isolated_booking_state.order_calls == 1


def test_legacy_booking_serializes_concurrent_same_key_to_one_provider_order(
    monkeypatch,
):
    fake = CountingAtlas(slow=True)
    monkeypatch.setattr(bookings, "atlas_client", fake)

    async def flow():
        return await asyncio.gather(
            _post(BOOKING, "legacy-concurrent-1"),
            _post(BOOKING, "legacy-concurrent-1"),
        )

    first, second = asyncio.run(flow())
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert fake.order_calls == 1


def test_legacy_booking_provider_failure_does_not_poison_retry_or_leak_error(
    monkeypatch,
):
    fake = CountingAtlas(fail_first=True)
    monkeypatch.setattr(bookings, "atlas_client", fake)

    async def flow():
        failed = await _post(BOOKING, "legacy-retry-1")
        retried = await _post(BOOKING, "legacy-retry-1")
        return failed, retried

    failed, retried = asyncio.run(flow())
    assert failed.status_code == 502
    assert "SENTINEL_PROVIDER_SECRET" not in failed.text
    assert retried.status_code == 200
    assert fake.order_calls == 2


def test_legacy_booking_refuses_unverified_fare_before_order(monkeypatch):
    fake = CountingAtlas(verified=False)
    monkeypatch.setattr(bookings, "atlas_client", fake)
    response = asyncio.run(_post(BOOKING, "legacy-unverified-1"))
    assert response.status_code == 409
    assert "fare could not be re-verified" in response.json()["detail"]
    assert fake.order_calls == 0
