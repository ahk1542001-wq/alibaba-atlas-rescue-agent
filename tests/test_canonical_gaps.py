import pytest
from httpx import ASGITransport, AsyncClient
from main import app
from tests.test_e2e_trip_journey import harness, FakeAtlas, _client, _run

from routers.v1.trip import get_trip_orchestrator
from services.skills.recovery_plan import RecoveryPlanSkill
from services.skills.itinerary import ItinerarySkill
from tests.test_e2e_trip_journey import _no_llm

# 1. API Missing Fields & Confirmations
def test_gap1_api_confirmations_and_plan(harness):
    harness()

    async def flow():
        async with _client() as client:
            user_id = "user_canonical"
            res = await client.post("/api/trips", json={
                "goal_text": "Find flights only to Singapore on 2026-12-01",
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
        

def test_gap2_and_gap3_recovery_rebooking_and_idempotency(harness):
    import uuid
    atlas = FakeAtlas()
    orch = harness(atlas=atlas)
    
    async def flow():
        async with _client() as client:
            await client.put("/api/profile/user_recovery/passport_country", json={"value": "SGP"})
            
    _run(flow())
    trip_id = _run(orch.start("Yangon to Singapore Oct 15", "user_recovery"))
    
    trip = orch.executor.get(trip_id)
    if trip.current == "scope_clarification":
        appr_id = trip.pending_approvals[0].approval_id
        _run(orch.resolve(trip_id, appr_id, "flight_only", None))
        
    if trip.current == "flight_book":
        appr_id = trip.pending_approvals[0].approval_id
        opts = trip.context.get("flight_search", {}).get("options", [])
        if opts:
            oid = opts[0]["id"]
            
            # GAP 3: Require Idempotency-Key
            with pytest.raises(Exception) as exc:
                _run(orch.resolve(trip_id, appr_id, "approve", {"option_id": oid}))
            assert "missing_idempotency_key" in str(exc.value)
            
            # Call with key
            ikey = str(uuid.uuid4())
            _run(orch.resolve(trip_id, appr_id, "approve", {"option_id": oid}, idempotency_key=ikey))
            
    # Trigger recovery
    trip.context["flight_book"] = {"booking": {"pnr": "PNR1", "option": {"flight_no": "TG100"}}}
    _run(orch.simulate_disruption(trip_id, {"flight_number": "TG100", "scenario": "cancellation", "simulated": True}))
    
    # Wait for recovery plan approval
    if trip.current == "recovery_booking":
        rec = trip.context.get("recovery", {})
        opts = rec.get("options", [])
        if opts:
            rec_oid = opts[0]["id"]
            appr_id = trip.pending_approvals[0].approval_id
            
            # Idempotency is required here too
            with pytest.raises(Exception) as exc:
                _run(orch.resolve(trip_id, appr_id, "approve", {"option_id": rec_oid}))
            assert "missing_idempotency_key" in str(exc.value)
            
            # Reset spy calls to isolate the recovery boundary
            atlas.calls.clear()
            
            ikey2 = str(uuid.uuid4())
            _run(orch.resolve(trip_id, appr_id, "approve", {"option_id": rec_oid}, idempotency_key=ikey2))
            
            # GAP 2: Must have called Atlas EXACTLY ONCE for booking creation
            creates = [c for c in atlas.calls if c[0] == "create"]
            assert len(creates) == 1
            
            # Check itinerary
            itin = trip.context.get("itinerary", {}).get("items", [])
            assert any(i.get("honesty_label") == "booked replacement flight (Atlas sandbox record)" for i in itin)


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
