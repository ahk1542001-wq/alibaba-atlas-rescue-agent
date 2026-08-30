import asyncio
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from main import app
from tests.test_e2e_trip_journey import harness, FakeAtlas, _client, _run

from routers.v1.trip import get_trip_orchestrator
from services.skills.recovery_plan import RecoveryPlanSkill
from services.skills.itinerary import ItinerarySkill
from tests.test_e2e_trip_journey import _no_llm


class RecoveryAtlas(FakeAtlas):
    def __init__(self):
        super().__init__()
        self.search_count = 0
        self.create_count = 0

    async def search_flights(self, origin, destination, date_, passengers=1,
                             **kwargs):
        self.search_count += 1
        self.calls.append(("search", origin, destination, date_))
        recovery = self.search_count > 1
        return [{
            "offer_id": "off_recovery_2" if recovery else "off_initial_1",
            "airline_code": "SQ", "airline": "Singapore Airlines",
            "flight_number": "SQ714" if recovery else "SQ712",
            "origin": origin, "destination": destination,
            "departure_time": f"{date_} {'15:30' if recovery else '09:30'}",
            "arrival_time": f"{date_} {'17:00' if recovery else '11:00'}",
            "duration_minutes": 150,
            "price_usd": 230.0 if recovery else 210.0,
            "currency": "USD",
        }]

    async def create_booking_order(self, offer_id, passenger, **kwargs):
        self.create_count += 1
        self.calls.append(("create", offer_id))
        return {
            "order_id": f"ORD-{self.create_count}",
            "pnr": f"ATLAS-R{self.create_count:05d}",
            "status": "CONFIRMED", "offer_id": offer_id,
            "booking_timestamp": datetime.now(timezone.utc).isoformat(),
        }

# 1. API Missing Fields & Confirmations
def test_gap1_api_confirmations_and_plan(harness):
    harness()

    async def flow():
        async with _client() as client:
            user_id = "user_canonical"
            res = await client.post("/api/trips", json={
                "goal_text": "Book flight to Singapore on 2026-12-01 for 1 passenger",
                "user_id": user_id,
            })
            assert res.status_code == 200
            data = res.json()
            trip_id = data["trip_id"]

            assert data["missing_fields"] == [
                "origin_city", "passport_country", "home_city"]
            assert data["confirmation_chips"] == []

            before = (await client.get(f"/api/profile/{user_id}")).json()
            assert before["passport_country"] is None

            clarification = await client.post(
                f"/api/trips/{trip_id}/clarifications",
                json={"answers": {"passport_country": "MM"}},
            )
            assert clarification.status_code == 200, clarification.text
            pending = clarification.json()["confirmation_chips"]
            assert len(pending) == 1
            chip = pending[0]
            assert chip["field"] == "passport_country"
            assert chip["proposed_value"] == "MM"
            assert chip["state"] == "pending"

            still_before = (await client.get(f"/api/profile/{user_id}")).json()
            assert still_before["passport_country"] is None

            c_res = await client.post(
                f"/api/trips/{trip_id}/confirmations/{chip['chip_id']}",
                json={"decision": "confirm"},
            )
            assert c_res.status_code == 200, c_res.text
            confirmed = c_res.json()
            assert confirmed["status"] == "confirmed"
            assert confirmed["missing_fields"] == ["origin_city", "home_city"]

            after = (await client.get(f"/api/profile/{user_id}")).json()
            assert after["passport_country"]["value"] == "MM"

            c_res2 = await client.post(
                f"/api/trips/{trip_id}/confirmations/{chip['chip_id']}",
                json={"decision": "confirm"},
            )
            assert c_res2.status_code == 409

            origin = await client.post(
                f"/api/trips/{trip_id}/clarifications",
                json={"answers": {"origin_city": "BKK"}},
            )
            assert origin.status_code == 200, origin.text
            origin_chip = origin.json()["confirmation_chips"][0]
            assert origin_chip["field"] == "origin_city"
            assert origin_chip["proposed_value"] == "BKK"
            origin_confirm = await client.post(
                f"/api/trips/{trip_id}/confirmations/{origin_chip['chip_id']}",
                json={"decision": "confirm"},
            )
            assert origin_confirm.status_code == 200, origin_confirm.text

            p_res = await client.post(f"/api/trips/{trip_id}/plan")
            assert p_res.status_code == 200
            assert p_res.json()["status"] in ("completed", "failed", "awaiting_approval")

    _run(flow())


def test_confirmed_passport_rebuilds_visa_and_booking_snapshot(harness):
    atlas = FakeAtlas()
    harness(atlas=atlas)

    async def flow():
        async with _client() as client:
            start = await client.post("/api/trips", json={
                "goal_text": (
                    "Book a flight from BKK to SIN on 2026-09-29, flights only"
                ),
                "user_id": "confirmation-refresh",
            })
            assert start.status_code == 200, start.text
            trip_id = start.json()["trip_id"]

            proposal = await client.post(
                f"/api/trips/{trip_id}/clarifications",
                json={"answers": {"passport_country": "MM"}},
            )
            chip = next(c for c in proposal.json()["confirmation_chips"]
                        if c["field"] == "passport_country")
            confirmed = await client.post(
                f"/api/trips/{trip_id}/confirmations/{chip['chip_id']}",
                json={"decision": "confirm"},
            )
            assert confirmed.status_code == 200, confirmed.text
            plan_res = await client.post(f"/api/trips/{trip_id}/plan")
            assert plan_res.status_code == 200, plan_res.text
            state = plan_res.json()
            assert state["outputs"]["visa_check"]["passport_country"] == "MM"
            assert state["outputs"]["visa_check"]["passport_unknown"] is False
            approval = next(a for a in state["pending_approvals"]
                            if a["node_name"] == "approve_booking")
            assert approval["options"]
            assert all(o["dep"]["airport"] == "BKK"
                       and o["arr"]["airport"] == "SIN"
                       for o in approval["options"])
            assert any(n["name"] == "confirmation_replan"
                       for n in state["nodes"])

    _run(flow())


def test_gap3_initial_booking_atomic_idempotency(harness):
    atlas = FakeAtlas()
    harness(atlas=atlas)

    async def flow():
        async with _client() as client:
            user_id = "user_atomic"
            await client.put(
                f"/api/profile/{user_id}/passport_country",
                json={"value": "MM"},
            )
            start = await client.post("/api/trips", json={
                "goal_text": (
                    "Book a flight from BKK to SIN on 2026-09-29, flights only"
                ),
                "user_id": user_id,
            })
            assert start.status_code == 200, start.text
            trip_id = start.json()["trip_id"]
            plan_res = await client.post(f"/api/trips/{trip_id}/plan")
            assert plan_res.status_code == 200, plan_res.text
            approvals = (await client.get(
                f"/api/trips/{trip_id}/approvals")).json()["approvals"]
            gate = next(a for a in approvals
                        if a["node_name"] == "approve_booking")
            assert gate["purpose"] == "initial_booking"
            assert gate["trip_id"] == trip_id
            assert gate["expires_at"]
            assert gate["immutable_option"]["options"] == gate["options"]
            option_id = gate["options"][0]["id"]

            payload = {"decision": "approve",
                       "value": {"option_id": option_id}}
            missing = await client.post(
                f"/api/trips/{trip_id}/approvals/{gate['approval_id']}",
                json=payload,
            )
            assert missing.status_code == 422
            assert missing.json()["error"]["code"] == "missing_idempotency_key"

            atlas.calls.clear()
            headers = {"Idempotency-Key": "initial-booking-key-001"}

            async def approve_once():
                return await client.post(
                    f"/api/trips/{trip_id}/approvals/{gate['approval_id']}",
                    json=payload, headers=headers)

            first, replay = await asyncio.gather(approve_once(), approve_once())
            assert first.status_code == replay.status_code == 200
            assert first.json() == replay.json()
            creates = [c for c in atlas.calls if c[0] == "create"]
            assert len(creates) == 1
            assert first.json()["booking"]["booking"]["option"]["id"] == option_id

            conflict = await client.post(
                f"/api/trips/{trip_id}/approvals/{gate['approval_id']}",
                json={"decision": "approve",
                      "value": {"option_id": "different-option"}},
                headers=headers,
            )
            assert conflict.status_code == 409
            assert conflict.json()["error"]["code"] == "idempotency_conflict"

    _run(flow())


def test_gap2_full_recovery_preserves_evidence_and_is_atomic(harness):
    atlas = RecoveryAtlas()
    harness(atlas=atlas)

    async def flow():
        async with _client() as client:
            user_id = "user_recovery_full"
            await client.put(
                f"/api/profile/{user_id}/passport_country",
                json={"value": "MM"},
            )
            start = await client.post("/api/trips", json={
                "goal_text": (
                    "Plan my complete trip from BKK to SIN on 2026-09-29"
                ),
                "user_id": user_id,
            })
            assert start.status_code == 200, start.text
            trip_id = start.json()["trip_id"]
            plan_res = await client.post(f"/api/trips/{trip_id}/plan")
            assert plan_res.status_code == 200, plan_res.text
            approvals = (await client.get(
                f"/api/trips/{trip_id}/approvals")).json()["approvals"]
            initial = next(a for a in approvals
                           if a["node_name"] == "approve_booking")
            initial_id = initial["options"][0]["id"]
            booked = await client.post(
                f"/api/trips/{trip_id}/approvals/{initial['approval_id']}",
                json={"decision": "approve",
                      "value": {"option_id": initial_id}},
                headers={"Idempotency-Key": "recovery-original-001"},
            )
            assert booked.status_code == 200, booked.text
            original = booked.json()["booking"]
            assert original["booking"]["option"]["id"] == initial_id

            disrupted = await client.post(
                f"/api/trips/{trip_id}/simulate-disruption",
                json={"scenario": "cancellation", "flight_number": "SQ712",
                      "reason": "Weather test"},
            )
            assert disrupted.status_code == 200, disrupted.text

            approvals = (await client.get(
                f"/api/trips/{trip_id}/approvals")).json()["approvals"]
            recovery = next(a for a in approvals
                            if a["node_name"] == "recovery_booking")
            assert recovery["purpose"] == "recovery_booking"
            assert recovery["trip_id"] == trip_id
            assert recovery["immutable_option"]["options"]
            assert recovery["price_snapshot"]["options"]
            assert recovery["expires_at"]
            recovery_id = recovery["options"][0]["id"]

            payload = {"decision": "approve",
                       "value": {"option_id": recovery_id}}
            missing = await client.post(
                f"/api/trips/{trip_id}/approvals/{recovery['approval_id']}",
                json=payload,
            )
            assert missing.status_code == 422
            assert missing.json()["error"]["code"] == "missing_idempotency_key"

            atlas.calls.clear()
            headers = {"Idempotency-Key": "recovery-booking-001"}

            async def approve_recovery():
                return await client.post(
                    f"/api/trips/{trip_id}/approvals/{recovery['approval_id']}",
                    json=payload, headers=headers)

            first, replay = await asyncio.gather(
                approve_recovery(), approve_recovery())
            assert first.status_code == replay.status_code == 200
            assert first.json() == replay.json()
            assert len([c for c in atlas.calls if c[0] == "create"]) == 1

            state = (await client.get(
                f"/api/trips/{trip_id}/state")).json()
            outputs = state["outputs"]
            replacement = outputs["recovery_booking"]
            assert replacement["booking"]["option"]["id"] == recovery_id
            receipts = outputs["recovery"]["receipts"]
            assert receipts["original"]["pnr"] == original["pnr"]
            assert receipts["replacement"]["pnr"] == replacement["pnr"]
            assert receipts["original"]["pnr"] != receipts["replacement"]["pnr"]
            assert outputs["rights"]["regime"] == "NONE"
            assert outputs["recovery"]["monitor"]["armed"] is True
            assert outputs["recovery"]["monitor"]["pnr"] == replacement["pnr"]

            flight_items = [i for i in outputs["itinerary"]["items"]
                            if i["kind"] == "flight"]
            assert any("cancelled/replaced" in i["honesty_label"]
                       for i in flight_items)
            assert any(i["honesty_label"] ==
                       "booked replacement flight (Atlas sandbox record)"
                       for i in flight_items)

    _run(flow())


def test_gap4_itinerary_replace_section():
    items = [
        {
            "item_id": "i1", "name": "SQ 712", "kind": "flight",
            "source": "atlas_real", "booked": True,
            "details": {
                "dep_time": "2026-09-28T09:30:00+07:00",
                "arr_time": "2026-09-28T13:00:00+08:00",
            },
        },
        {
            "item_id": "i2", "name": "Old Hotel", "kind": "hotel",
            "source": "researched_mock", "booked": False,
            "price_range_sgd": [120, 180],
            "details": {
                "start_time": "2026-09-28T15:00:00+08:00",
                "end_time": "2026-09-30T11:00:00+08:00",
            },
        },
        {
            "item_id": "i3", "name": "Gardens", "kind": "activity",
            "source": "organizer", "booked": False,
            "details": {
                "start_time": "2026-09-29T10:00:00+08:00",
                "end_time": "2026-09-29T12:00:00+08:00",
            },
        },
    ]
    summary = ItinerarySkill.summarize(items, "Asia/Singapore")
    assert summary["timezone"] == "Asia/Singapore"
    assert summary["budget"]["total_range_sgd"] == [120.0, 180.0]
    assert summary["budget"]["by_category"]["hotel"] == [120.0, 180.0]
    assert summary["validation"]["invalid_ranges"] == []

    # reject replacing booked flights
    res1 = ItinerarySkill.replace_section(items, "i1", {})
    assert res1.get("error") == "booked_section_immutable"

    # replace unbooked
    before_first = dict(items[0])
    before_last = dict(items[2])
    res2 = ItinerarySkill.replace_section(items, "i2", {
        "name": "New Hotel",
        "kind": "hotel",
        "price_range_sgd": [150, 210],
        "details": {
            "start_time": "2026-09-28T15:00:00+08:00",
            "end_time": "2026-09-30T11:00:00+08:00",
        },
    }, timezone_name="Asia/Singapore")
    assert res2.get("replaced", {}).get("before", {}).get("item_id") == "i2"
    assert res2["items"][1]["name"] == "New Hotel"
    assert "user-replaced section" in res2["items"][1]["honesty_label"]
    assert res2["items"][0] == before_first
    assert res2["items"][2] == before_last
    assert res2["timezone"] == "Asia/Singapore"
    assert res2["budget"]["total_range_sgd"] == [150.0, 210.0]
    assert res2["validation"]["overlaps"]


def test_gap4_itinerary_overlap_uses_real_iso_instants():
    items = [
        {
            "item_id": "a", "name": "A", "kind": "activity",
            "details": {
                "start_time": "2026-09-29T09:00:00+08:00",
                "end_time": "2026-09-29T10:00:00+08:00",
            },
        },
        {
            "item_id": "b", "name": "B", "kind": "activity",
            "details": {
                "start_time": "2026-09-29T02:30:00+00:00",
                "end_time": "2026-09-29T03:30:00+00:00",
            },
        },
    ]
    result = ItinerarySkill.summarize(items, "Asia/Singapore")
    assert result["validation"]["overlaps"] == []


def test_gap5_recovery_plan_no_sq999_fabrication():
    # Setup mock atlas that returns no results
    class EmptyAtlas:
        async def search_flights(self, *args, **kwargs):
            return []
            
    skill = RecoveryPlanSkill(EmptyAtlas(), _no_llm)
    trip_ctx = {
        "flight_book": {"booking": {"option": {"dep": {"airport": "BKK"}, "arr": {"airport": "SIN"}}}}
    }
    out = _run(skill.run({"original_flight": "TG1", "disruption": {}}, trip_ctx))
    # Must NOT fabricate SQ999, must return empty
    assert out["status"] == "no_alternatives_available"
    assert len(out["recovery_options"]) == 0


def test_gap6_forged_rejection_overwritten_by_server_decision(harness):
    atlas = FakeAtlas()
    harness(atlas=atlas)

    async def flow():
        async with _client() as client:
            user_id = "user_forged_rejection"
            await client.put(
                f"/api/profile/{user_id}/passport_country",
                json={"value": "MM"},
            )
            start = await client.post("/api/trips", json={
                "goal_text": "Plan my complete trip from BKK to SIN on 2026-09-29",
                "user_id": user_id,
            })
            assert start.status_code == 200, start.text
            trip_id = start.json()["trip_id"]
            plan_res = await client.post(f"/api/trips/{trip_id}/plan")
            assert plan_res.status_code == 200, plan_res.text

            orch = get_trip_orchestrator()
            trip = orch._trip_or_404(trip_id)
            approval = next(a for a in trip.pending_approvals
                            if a.node_name == "approve_booking")
            option_id = approval.options[0]["id"]

            atlas.calls.clear()
            payload = {
                "decision": "reject",
                "value": {"approved": True, "option_id": option_id},
            }
            res = await client.post(
                f"/api/trips/{trip_id}/approvals/{approval.approval_id}",
                json=payload,
            )
            assert res.status_code == 200
            assert approval.resolved_value.get("approved") is False
            creates = [c for c in atlas.calls if c[0] == "create"]
            assert len(creates) == 0

    _run(flow())
