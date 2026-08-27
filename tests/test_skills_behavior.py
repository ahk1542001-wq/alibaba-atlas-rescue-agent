"""G2 behavior tests for the 11 product skills (§4 S1–S11) + owner corrections.

Owner architecture corrections under test:
(A) profiles start EMPTY; clarify asks every missing required value; saves
    only after ConfirmationChip confirmation (silent-save impossible).
(B) intent-first routing per RequestedServices; unknown core scope emits the
    three-choice scope clarification; flight-only never runs hotel/activities/
    local-transport researchers.
(C) bounded research: fares REFRESHED + REVERIFIED immediately before booking;
    stale/unverified visa data BLOCKS booking with a recoverable error; every
    result carries provenance + freshness_state + honest degraded flags.

Atlas/LLM/web-intel are fakes injected through constructors — no network.
"""

import asyncio
import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from models.schemas import RequestedServices, TripGoal, TripIntent
from services.profile_store import ProfileStore
from services.skills.base import SkillError
from services.skills.clarify_loop import ClarifyLoopSkill
from services.skills.disruption_monitor import DisruptionMonitorSkill
from services.skills.flight_book import FlightBookSkill
from services.skills.flight_search import FlightSearchSkill
from services.skills.goal_intake import GoalIntakeSkill
from services.skills.guardian_push import GuardianPushSkill, sanitize_payload
from services.skills.itinerary import ItinerarySkill
from services.skills.profile_capture import ProfileCaptureSkill
from services.skills.rights_check import RightsCheckSkill
from services.skills.visa_check import VisaCheckSkill
from services.skills.web_intel import WebIntelSkill
from services.research_coordinator import ResearchCoordinator
from services.trip_graph import TripGraphExecutor, plan_trip


def _run(coro):
    return asyncio.run(coro)


# --- shared fakes ----------------------------------------------------------------

class FakeAtlas:
    def __init__(self, verified=True):
        self.calls = []
        self.verified = verified
        self.offer = {
            "offer_id": "off_test_1",
            "flight_number": "SQ712",
            "airline": "Singapore Airlines",
            "airline_code": "SQ",
            "origin": "BKK",
            "destination": "SIN",
            "departure_time": "2026-09-28 09:30",
            "arrival_time": "2026-09-28 11:00",
            "duration_minutes": 150,
            "price_usd": 210.0,
            "currency": "USD",
            "currency_symbol": "$",
        }

    async def search_flights(self, origin, destination, date, passengers=1,
                             cabin_class="ECONOMY", currency="USD"):
        self.calls.append("search")
        return [dict(self.offer)]

    async def verify_fare(self, offer_id):
        self.calls.append("verify")
        return {"verified": self.verified, "offer_id": offer_id,
                "fare_lock_expires_in_seconds": 900}

    async def create_booking_order(self, offer_id, passenger, baggage_addon=None,
                                   seat_selected="12A"):
        self.calls.append("create")
        return {"order_id": "ORD-TEST", "pnr": "ATLAS-TEST12", "status": "CONFIRMED",
                "offer_id": offer_id,
                "booking_timestamp": "2026-08-26T12:00:00+00:00"}


class FakeWebIntel:
    """Configurable web-intel fake; counts fetches."""

    def __init__(self, degraded=False, retrieved=None):
        self.degraded = degraded
        self.retrieved = retrieved or date.today().isoformat()
        self.fetch_count = 0

    async def fetch(self, query):
        self.fetch_count += 1
        if self.degraded:
            return {"provider": "static_fallback", "degraded": True, "offline": True,
                    "answers": [], "citations": []}
        return {"provider": "ddg_lite", "degraded": False, "offline": False,
                "answers": ["MM nationals: Singapore visa-free 30 days"],
                "citations": [{"url": "https://www.iatatravelcentre.com/MM.htm",
                               "title": "IATA Travel Centre — MM",
                               "retrieved_date": self.retrieved,
                               "snippet_max280": "visa-free 30 days"}]}


async def _no_llm(messages, **kwargs):
    return None  # force deterministic stub path


# --- S1 goal_intake: golden phrasings ----------------------------------------------

GOLDEN_PHRASINGS = [
    "I need to get to WiT Singapore, Marina Bay Sands, Sep 29-30 — plan my whole trip.",
    "Fly me from Bangkok to Singapore on September 28, 2026.",
    "RGN to BKK one way 5 October for 2 people please",
    "Yangon going Singapore, September 29 and 30, one person",
    "I want cheap flight BKK SIN September 28, budget 150 USD",
    "Help me travel to Singapore from Bangkok, 2026-09-28 to 2026-09-30, business meeting",
    "Mingalabar! My flight Yangon to Singapore I need, September 28 going, "
    "29-30 conference attending, please arrange whole trip lah.",
    "Book flights only Bangkok to Singapore Sep 28, no hotel needed",
    "Singapore trip full package: flights, hotel, activities, local transport. "
    "From BKK. Sep 28-30.",
    "need to attend WiT at Marina Bay Sands flying out of BKK on 28 Sep, "
    "coming back 30 Sep",
    "arrange my whole trip to Singapore for Web in Travel summit Sep 29-30, "
    "departing Bangkok",
]


def test_s1_golden_phrasings_parse_without_error():
    skill = GoalIntakeSkill(llm_chat=_no_llm)
    assert len(GOLDEN_PHRASINGS) >= 10
    for phrase in GOLDEN_PHRASINGS:
        out = _run(skill.run({"free_text": phrase}))
        goal = out["goal"]
        assert goal["raw_text"] == phrase
        assert goal["goal_id"]
        assert goal["passengers"] >= 1
        assert out["degraded"] is True  # LLM unavailable -> honest stub flag
        assert out["extraction"] == "deterministic_stub"


def test_s1_burmese_flavored_english_extracts_route_and_scope():
    skill = GoalIntakeSkill(llm_chat=_no_llm)
    out = _run(skill.run({
        "free_text": "Mingalabar! My flight Yangon to Singapore I need, September 28 "
                     "going, 29-30 conference attending, please arrange whole trip lah."
    }))
    goal = out["goal"]
    assert goal["origin_city"] == "RGN"
    assert goal["dest_city"] == "SIN"
    assert goal["date_window"]["start"] == "2026-09-28"
    rs = out["requested_services"]
    assert rs["hotel"] == "requested"          # "whole trip"
    assert rs["flight_search"] == "requested"


def test_s1_flights_only_phrase_marks_hotel_not_requested():
    skill = GoalIntakeSkill(llm_chat=_no_llm)
    out = _run(skill.run({
        "free_text": "Book flights only Bangkok to Singapore Sep 28, no hotel needed"
    }))
    rs = out["requested_services"]
    assert rs["flight_search"] == "requested"
    assert rs["hotel"] == "not_requested"
    assert rs["activities"] == "not_requested"


def test_s1_ambiguous_text_leaves_scope_unknown():
    skill = GoalIntakeSkill(llm_chat=_no_llm)
    out = _run(skill.run({"free_text": "I need Singapore"}))
    rs = out["requested_services"]
    assert rs["hotel"] == "unknown"
    assert rs["flight_booking"] == "unknown"


def test_s1_adversarial_empty_and_garbage_never_raise():
    skill = GoalIntakeSkill(llm_chat=_no_llm)
    for text in ("", "   ", "####????", "x" * 5000):
        out = _run(skill.run({"free_text": text}))
        assert out["goal"]["raw_text"] == text
        assert out["degraded"] is True


# --- S2/L1 clarify_loop ---------------------------------------------------------------

@pytest.fixture()
def store(tmp_path: Path) -> ProfileStore:
    return ProfileStore(root=tmp_path)


def _complete_goal():
    return TripGoal(
        goal_id="g1", raw_text="BKK SIN", origin_city="BKK", dest_city="SIN",
        date_window={"start": "2026-09-28", "end": "2026-09-30"}, passengers=1,
    ).model_dump(mode="json")


def test_s2_empty_profile_asks_every_missing_required_value(store):
    skill = ClarifyLoopSkill(profile_store=store)
    out = _run(skill.run({
        "goal": _complete_goal(), "user_id": "victor",
        "requested_services": RequestedServices().model_dump(),
    }))
    fields = {q["field"] for q in out["questions"]}
    # empty profile -> identity facts asked; goal facts already known -> not asked
    assert {"passport_country", "home_city"} <= fields
    assert not {"origin_city", "dest_city", "date_window"} & fields


def test_s2_zero_redundant_questions_when_profile_complete(store):
    store.get_or_create("victor")
    store.set_identity("victor", passport_country="MM", home_city="Bangkok")
    rs = RequestedServices(flight_search="requested", flight_booking="requested",
                           visa_check="requested", hotel="not_requested",
                           activities="not_requested",
                           local_transport="not_requested").model_dump()
    skill = ClarifyLoopSkill(profile_store=store)
    out = _run(skill.run({"goal": _complete_goal(), "user_id": "victor",
                          "requested_services": rs}))
    assert out["questions"] == []
    assert out["scope_clarification"] is None
    assert out["complete"] is True


def test_s2_unknown_scope_emits_three_choice_clarification(store):
    skill = ClarifyLoopSkill(profile_store=store)
    store.set_identity("victor", passport_country="MM", home_city="Bangkok")
    out = _run(skill.run({
        "goal": _complete_goal(), "user_id": "victor",
        "requested_services": RequestedServices().model_dump(),
    }))
    assert out["scope_clarification"] is not None
    assert out["scope_clarification"]["choices"] == [
        "flight_only", "flight_plus_booking", "complete_trip"]
    assert out["complete"] is False


def test_s2_scope_choice_resolves_requested_services(store):
    skill = ClarifyLoopSkill(profile_store=store)
    out = _run(skill.run({
        "goal": _complete_goal(), "user_id": "victor",
        "requested_services": RequestedServices().model_dump(),
        "scope_choice": "flight_only",
    }))
    assert out["requested_services"]["flight_search"] == "requested"
    assert out["requested_services"]["flight_booking"] == "not_requested"
    assert out["requested_services"]["hotel"] == "not_requested"
    assert out["scope_clarification"] is None


# --- S2/S3 profile_capture: silent-save impossible --------------------------------------

def test_profile_capture_unconfirmed_save_raises(store):
    skill = ProfileCaptureSkill(profile_store=store)
    with pytest.raises(SkillError) as ei:
        _run(skill.run({"user_id": "victor", "field": "home_city",
                        "value": "Bangkok", "source": "ai_inferred"}))
    assert ei.value.code == "confirmation_required"
    assert ei.value.recoverable is True
    assert store.get_or_create("victor").fields == {}  # nothing saved


def test_profile_capture_rejected_chip_raises(store):
    skill = ProfileCaptureSkill(profile_store=store)
    with pytest.raises(SkillError) as ei:
        _run(skill.run({"user_id": "victor", "field": "home_city",
                        "value": "Bangkok", "source": "ai_inferred",
                        "confirmed": False}))
    assert ei.value.code == "confirmation_rejected"
    assert store.get_or_create("victor").fields == {}


def test_profile_capture_confirmed_saves_with_source_tag(store):
    skill = ProfileCaptureSkill(profile_store=store)
    out = _run(skill.run({"user_id": "victor", "field": "home_city",
                          "value": "Bangkok", "source": "ai_inferred",
                          "confirmed": True}))
    assert out["saved"] is True
    assert store.get_or_create("victor").fields["home_city"].value == "Bangkok"
    assert store.get_or_create("victor").fields["home_city"].source == "ai_inferred"


# --- S4 flight_search --------------------------------------------------------------------

def test_flight_search_wraps_atlas_with_sandbox_provenance():
    atlas = FakeAtlas()
    skill = FlightSearchSkill(atlas=atlas)
    out = _run(skill.run({"origin": "BKK", "destination": "SIN",
                          "date": "2026-09-28", "passengers": 1}))
    assert atlas.calls == ["search"]
    assert out["provenance"] == "sandbox"
    opt = out["options"][0]
    assert opt["sandbox_provenance"] is True
    assert opt["id"] == "off_test_1"
    assert opt["price"]["amount"] == 210.0
    assert opt["dep"]["airport"] == "BKK"
    assert out["retrieved_date"]  # research provenance stamped


def test_flight_search_invalid_input_raises_recoverable():
    skill = FlightSearchSkill(atlas=FakeAtlas())
    with pytest.raises(SkillError) as ei:
        _run(skill.run({"origin": "", "destination": "SIN"}))
    assert ei.value.recoverable is True


# --- S5 flight_book: idempotency, reverify, safety block ----------------------------------

def _book_payload(option_id="off_test_1"):
    return {
        "option_id": option_id,
        "origin": "BKK",
        "destination": "SIN",
        "passport_country": "MM",
        "passenger": {"name": "Test Traveler"},
        "option": {
            "id": option_id, "carrier": "SQ", "flight_no": "SQ712",
            "dep": {"airport": "BKK", "time": "2026-09-28 09:30"},
            "arr": {"airport": "SIN", "time": "2026-09-28 11:00"},
            "duration_min": 150, "price": {"amount": 210.0, "currency": "USD"},
        },
    }


def _fresh_visa_ctx():
    return {"visa_check": {"freshness_state": "fresh", "degraded": False,
                           "baseline_only": False, "requirements": []}}


def test_flight_book_reverifies_immediately_before_order():
    atlas = FakeAtlas()
    skill = FlightBookSkill(atlas=atlas)
    _run(skill.run(_book_payload(), context=_fresh_visa_ctx()))
    assert atlas.calls[-2:] == ["verify", "create"]  # refreshed+reverified then booked


def test_flight_book_idempotent_retry_returns_same_pnr():
    atlas = FakeAtlas()
    skill = FlightBookSkill(atlas=atlas)
    first = _run(skill.run(_book_payload(), context=_fresh_visa_ctx()))
    second = _run(skill.run(_book_payload(), context=_fresh_visa_ctx()))
    assert first["pnr"] == second["pnr"] == "ATLAS-TEST12"
    assert atlas.calls.count("create") == 1  # retry never double-books


def test_flight_book_unverified_fare_refuses():
    atlas = FakeAtlas(verified=False)
    skill = FlightBookSkill(atlas=atlas)
    with pytest.raises(SkillError) as ei:
        _run(skill.run(_book_payload(), context=_fresh_visa_ctx()))
    assert ei.value.code == "fare_unverified"
    assert "create" not in atlas.calls


def test_flight_book_stale_visa_blocks_international_booking():
    atlas = FakeAtlas()
    skill = FlightBookSkill(atlas=atlas)
    stale = {"visa_check": {"freshness_state": "stale", "degraded": False,
                            "baseline_only": False, "requirements": []}}
    with pytest.raises(SkillError) as ei:
        _run(skill.run(_book_payload(), context=stale))
    assert ei.value.code == "visa_data_stale_or_unverified"
    assert ei.value.recoverable is True
    assert atlas.calls == []  # nothing searched/verified/booked


def test_flight_book_baseline_only_visa_blocks_never_silent():
    atlas = FakeAtlas()
    skill = FlightBookSkill(atlas=atlas)
    unknown = {"visa_check": {"freshness_state": "unknown", "degraded": True,
                              "baseline_only": True, "requirements": []}}
    with pytest.raises(SkillError) as ei:
        _run(skill.run(_book_payload(), context=unknown))
    assert ei.value.code == "visa_data_stale_or_unverified"


def test_flight_book_missing_visa_context_blocks_international():
    skill = FlightBookSkill(atlas=FakeAtlas())
    with pytest.raises(SkillError) as ei:
        _run(skill.run(_book_payload(), context={}))
    assert ei.value.code == "visa_check_missing"


def test_flight_book_domestic_route_needs_no_visa_gate():
    atlas = FakeAtlas()
    skill = FlightBookSkill(atlas=atlas)
    payload = _book_payload()
    payload["origin"], payload["destination"] = "DMK", "BKK"  # both TH
    out = _run(skill.run(payload, context={}))
    assert out["pnr"] == "ATLAS-TEST12"


# --- S6 visa_check --------------------------------------------------------------------------

def test_s6_mm_fra_returns_schengen_atv_flag_with_citation():
    skill = VisaCheckSkill(web_intel=FakeWebIntel())
    out = _run(skill.run({"passport_country": "MM", "route": ["BKK", "FRA"]}))
    flags = " ".join(out["risk_flags"]).upper()
    assert "ATV" in flags or "SCHENGEN" in flags
    blocked = [r for r in out["requirements"] if r["risk_level"] == "block"]
    assert blocked, out
    assert out["citations"]
    assert out["citations"][0]["url"]


def test_s6_offline_returns_baseline_only_marker():
    skill = VisaCheckSkill(web_intel=FakeWebIntel(degraded=True))
    out = _run(skill.run({"passport_country": "MM", "route": ["BKK", "SIN"]}))
    assert out["baseline_only"] is True
    assert out["degraded"] is True
    assert out["freshness_state"] == "unknown"  # honest: never 'fresh' offline
    assert out["requirements"]  # baseline still answers


def test_s6_fresh_web_intel_marks_fresh():
    skill = VisaCheckSkill(web_intel=FakeWebIntel())
    out = _run(skill.run({"passport_country": "MM", "route": ["BKK", "SIN"]}))
    assert out["baseline_only"] is False
    assert out["freshness_state"] == "fresh"


def test_s6_stale_citation_marks_stale():
    old = (date.today() - timedelta(days=30)).isoformat()
    skill = VisaCheckSkill(web_intel=FakeWebIntel(retrieved=old), max_age_hours=24)
    out = _run(skill.run({"passport_country": "MM", "route": ["BKK", "SIN"]}))
    assert out["freshness_state"] == "stale"


# --- G2-DA remediation: sub-day freshness aging on real timestamps (finding 9) ----

def test_s6_yesterday_date_only_citation_is_stale_under_24h_policy():
    """Day-granular aging treated yesterday as fresh; real aging must not."""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    skill = VisaCheckSkill(web_intel=FakeWebIntel(retrieved=yesterday),
                           max_age_hours=24)
    out = _run(skill.run({"passport_country": "MM", "route": ["BKK", "SIN"]}))
    assert out["freshness_state"] == "stale"


class StampedWebIntel:
    """Citations carrying a real sub-day fetched_at timestamp."""

    def __init__(self, fetched_at):
        self.fetched_at = fetched_at

    async def fetch(self, query):
        return {"provider": "ddg_lite", "degraded": False, "offline": False,
                "answers": ["ok"],
                "citations": [{"url": "https://iata.example",
                               "title": "t",
                               "retrieved_date": date.today().isoformat(),
                               "fetched_at": self.fetched_at,
                               "snippet_max280": "s"}]}


def test_s6_freshness_honors_subday_fetched_at():
    now = datetime.now(timezone.utc)
    fresh_skill = VisaCheckSkill(
        web_intel=StampedWebIntel((now - timedelta(hours=2)).isoformat()),
        max_age_hours=24)
    out = _run(fresh_skill.run({"passport_country": "MM", "route": ["BKK", "SIN"]}))
    assert out["freshness_state"] == "fresh"     # 2h old < 24h policy
    stale_skill = VisaCheckSkill(
        web_intel=StampedWebIntel((now - timedelta(hours=25)).isoformat()),
        max_age_hours=24)
    out = _run(stale_skill.run({"passport_country": "MM", "route": ["BKK", "SIN"]}))
    assert out["freshness_state"] == "stale"     # 25h old > 24h policy, same day


def test_s6_baseline_latency_under_50ms():
    skill = VisaCheckSkill(web_intel=FakeWebIntel(degraded=True))
    start = time.perf_counter()
    _run(skill.run({"passport_country": "MM", "route": ["BKK", "SIN"]}))
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert elapsed_ms < 50, f"baseline took {elapsed_ms:.1f}ms"


def test_s6_unknown_passport_is_honest_not_invented():
    skill = VisaCheckSkill(web_intel=FakeWebIntel(degraded=True))
    out = _run(skill.run({"passport_country": "XX", "route": ["BKK", "SIN"]}))
    assert out["requirements"] == [] or all(
        r["risk_level"] in ("info", "warn", "block") for r in out["requirements"])
    assert out["degraded"] is True


# --- S7 web_intel skill ---------------------------------------------------------------------

def test_s7_cache_hit_counted():
    skill = WebIntelSkill(client=FakeWebIntel())
    first = _run(skill.run({"query": "q", "ttl_hours": 24}))
    second = _run(skill.run({"query": "q", "ttl_hours": 24}))
    assert skill.client.fetch_count == 1
    assert first["citations"] == second["citations"]


def test_s7_offline_degrades_null():
    skill = WebIntelSkill(client=FakeWebIntel(degraded=True))
    out = _run(skill.run({"query": "anything"}))
    assert out["degraded"] is True
    assert out["answers"] == []


# --- S8 itinerary -----------------------------------------------------------------------------

def _booking_record():
    return {
        "pnr": "ATLAS-TEST12",
        "option": {
            "id": "off_test_1", "carrier": "SQ", "flight_no": "SQ712",
            "dep": {"airport": "BKK", "time": "2026-09-28 09:30"},
            "arr": {"airport": "SIN", "time": "2026-09-28 11:00"},
            "duration_min": 150, "price": {"amount": 210.0, "currency": "USD"},
            "sandbox_provenance": True,
        },
        "status": "CONFIRMED", "booked_at": "2026-08-26T12:00:00+00:00",
        "monitor_armed": True,
    }


def test_s8_flight_item_tagged_atlas_real(tmp_path):
    skill = ItinerarySkill(hotels_path=tmp_path / "absent.json")
    out = _run(skill.run({"booking": _booking_record()}))
    flight = out["items"][0]
    assert flight["source"] == "atlas_real"
    assert flight["kind"] == "flight"


def test_s8_researched_mock_file_tagged_with_as_of_chip(tmp_path):
    path = tmp_path / "mock_hotels_sg.json"
    path.write_text(json.dumps({"hotels": [
        {"name": "Marina Bay Sands", "type": "hotel", "price_range_sgd": [450, 900],
         "stars": 5, "distance_to_mbs_km_approx": 0.0,
         "source_url": "https://example.org/mbs", "researched_as_of": "2026-08-26"},
        {"name": "BAD ENTRY"},  # unverifiable -> dropped, never invented
    ]}), encoding="utf-8")
    skill = ItinerarySkill(hotels_path=path)
    out = _run(skill.run({"booking": _booking_record()}))
    hotels = [i for i in out["items"] if i["kind"] == "hotel"]
    assert len(hotels) == 1  # invalid entry dropped
    assert hotels[0]["source"] == "researched_mock"
    assert "2026-08-26" in hotels[0]["honesty_label"]
    assert hotels[0]["provenance"]["source_url"] == "https://example.org/mbs"


def test_s8_organizer_provider_wins_chain(tmp_path):
    async def organizer():
        return [{"name": "Organizer Hotel", "type": "hotel"}]

    skill = ItinerarySkill(hotels_path=tmp_path / "absent.json", organizer=organizer)
    out = _run(skill.run({"booking": _booking_record()}))
    hotels = [i for i in out["items"] if i["kind"] == "hotel"]
    assert hotels[0]["source"] == "organizer"
    assert hotels[0]["honesty_label"] == "live data"


def test_s8_corrupt_file_degrades_honestly(tmp_path):
    path = tmp_path / "mock_hotels_sg.json"
    path.write_text("{not json", encoding="utf-8")
    skill = ItinerarySkill(hotels_path=path)
    out = _run(skill.run({"booking": _booking_record()}))
    assert [i for i in out["items"] if i["kind"] == "hotel"] == []
    assert any("researched_mock" in p for p in out["providers_tried"])


# --- S9 rights_check -----------------------------------------------------------------------------

def test_s9_no_regime_returns_honest_none():
    skill = RightsCheckSkill()
    out = _run(skill.run({"origin_airport": "BKK", "destination_airport": "RGN"}))
    assert out["regime"] == "NONE"
    assert out["amount"] is None
    assert "no applicable regime" in out["note"].lower()


def test_s9_eu_departure_cites_eu261():
    skill = RightsCheckSkill()
    out = _run(skill.run({"origin_airport": "FRA", "destination_airport": "BKK"}))
    assert out["regime"] == "EU261"
    assert out["legal_citation"]
    assert out["distance_km"] > 0


def test_s9_unknown_airports_honest():
    skill = RightsCheckSkill()
    out = _run(skill.run({"origin_airport": "ZZZ", "destination_airport": "QQQ"}))
    assert out["regime"] == "NONE"


# --- S10 guardian_push -----------------------------------------------------------------------------

def test_s10_token_absent_skipped_not_failed(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    skill = GuardianPushSkill()
    out = _run(skill.run({"event": "disruption", "payload": {"pnr": "ABC123"}}))
    assert out["delivery_status"] == "skipped_not_failed"
    assert out["simulated"] is True


def test_s10_payload_never_carries_passport_number(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    skill = GuardianPushSkill()
    out = _run(skill.run({"event": "booking", "payload": {
        "pnr": "ABC123", "passport_number": "SENTINEL-PASS-001", "passport_no": "SENTINEL-PASS-001",
        "name": "Victor"}}))
    assert "SENTINEL-PASS-001" not in json.dumps(out)


# --- S11 disruption_monitor ---------------------------------------------------------------------------

def test_s11_arms_watch_and_simulated_hook_mounts_subgraph_within_2s():
    ex = TripGraphExecutor(registry=[], allow_unmanifested_skills=True)
    from services.trip_graph import NodeSpec
    from tests.test_trip_graph import EchoSkill
    ex.register_skill("echo", EchoSkill())
    ex.start_trip("trip-sim", [NodeSpec(name="a", skill_ref="echo", edges=[])],
                  context={})
    _run(ex.run("trip-sim"))
    skill = DisruptionMonitorSkill(trip_registry=ex)
    out = _run(skill.run({"pnr": "ATLAS-TEST12", "flight_ids": ["SQ712"],
                          "trip_id": "trip-sim"}))
    assert out["armed"] is True
    before = len(ex.get("trip-sim").trace)
    start = time.monotonic()
    event = _run(skill.simulate_disruption({"flight_number": "SQ712",
                                            "status": "CANCELLED"}))
    elapsed = time.monotonic() - start
    assert elapsed < 2.0
    assert event["mounted"] is True
    assert len(ex.get("trip-sim").trace) == before + 1
    assert ex.get("trip-sim").trace[-1].name == "RecoverySubgraph"


def test_s11_no_trip_id_arms_without_mounting():
    skill = DisruptionMonitorSkill(trip_registry=None)
    out = _run(skill.run({"pnr": "ATLAS-TEST12", "flight_ids": ["SQ712"]}))
    assert out["armed"] is True
    assert out["subgraph_mounted"] is False


# --- (C) bounded ResearchCoordinator ------------------------------------------------------------------

def _rs(**kw):
    return RequestedServices(**kw)


def test_coordinator_flight_only_skips_leisure_researchers():
    coord = ResearchCoordinator(atlas=FakeAtlas())
    domains = coord.plan_research(_rs(flight_search="requested",
                                      flight_booking="not_requested",
                                      visa_check="not_requested",
                                      hotel="not_requested",
                                      activities="not_requested",
                                      local_transport="not_requested"),
                                  international=False, booking=False)
    assert set(domains) == {"flight"}


def test_coordinator_international_booking_adds_visa_safety():
    coord = ResearchCoordinator(atlas=FakeAtlas())
    domains = coord.plan_research(_rs(flight_search="requested",
                                      flight_booking="requested",
                                      visa_check="not_requested",
                                      hotel="not_requested",
                                      activities="not_requested",
                                      local_transport="not_requested"),
                                  international=True, booking=True)
    assert "visa" in domains and "flight" in domains


def test_coordinator_complete_mounts_all_domains():
    coord = ResearchCoordinator(atlas=FakeAtlas())
    domains = coord.plan_research(_rs(flight_search="requested",
                                      flight_booking="requested",
                                      visa_check="requested",
                                      hotel="requested",
                                      activities="requested",
                                      local_transport="requested"),
                                  international=True, booking=True)
    assert set(domains) == {"flight", "visa", "hotel", "activities", "local_transport"}


def test_coordinator_flight_result_carries_provenance_and_freshness():
    coord = ResearchCoordinator(atlas=FakeAtlas())
    result = _run(coord.run_domain("flight", {"origin": "BKK", "destination": "SIN",
                                              "date": "2026-09-28"}))
    assert result["provenance"] == "atlas_sandbox"
    assert result["freshness_state"] == "fresh"
    assert result["retrieved_date"]
    assert result["degraded"] is False


def test_coordinator_reverifies_fare_immediately_before_booking():
    atlas = FakeAtlas()
    coord = ResearchCoordinator(atlas=atlas)
    out = _run(coord.refresh_and_verify("off_test_1"))
    assert atlas.calls[-2:] == ["search", "verify"]
    assert out["verified"] is True
    assert out["freshness_state"] == "fresh"


# --- full journey through the real graph with real skills ----------------------------------------------

def _journey_executor(tmp_path):
    from services.skills.goal_intake import GoalIntakeSkill
    from services.trip_graph import NodeSpec  # noqa: F401
    atlas = FakeAtlas()
    # allow_unmanifested_skills=True: journey harness registers real skills
    # against an empty test registry; production default stays fail-closed
    ex = TripGraphExecutor(registry=[], allow_unmanifested_skills=True)
    ex.register_skill("goal_intake", GoalIntakeSkill(llm_chat=_no_llm))
    ex.register_skill("clarify_loop", ClarifyLoopSkill(ProfileStore(root=tmp_path)))
    ex.register_skill("flight_search", FlightSearchSkill(atlas=atlas))
    ex.register_skill("visa_check", VisaCheckSkill(web_intel=FakeWebIntel()))
    ex.register_skill("flight_book", FlightBookSkill(atlas=atlas))
    ex.register_skill("disruption_monitor", DisruptionMonitorSkill(trip_registry=ex))
    return ex, atlas


def test_full_journey_goal_to_booking_with_gate(tmp_path):
    ex, atlas = _journey_executor(tmp_path)
    intent = TripIntent(
        intent_id="i1", raw_text="plan my whole trip BKK to Singapore Sep 28-30",
        goal=TripGoal(goal_id="g1",
                      raw_text="plan my whole trip BKK to Singapore Sep 28-30",
                      origin_city="BKK", dest_city="SIN",
                      date_window={"start": "2026-09-28", "end": "2026-09-30"},
                      passengers=1),
        requested_services=RequestedServices(
            flight_search="requested", flight_booking="requested",
            visa_check="requested", hotel="not_requested",
            activities="not_requested", local_transport="not_requested"),
        scope_clarified=True)
    plan = plan_trip(intent)
    ex.start_trip(
        "journey", plan.nodes,
        context={
            "raw_text": intent.raw_text,
            "user_id": "victor",
            "profile": {"passport_country": "MM", "home_city": "Bangkok"},
            "requested_services": intent.requested_services.model_dump(),
        })
    _run(ex.run("journey"))
    trip = ex.get("journey")
    assert trip.status == "awaiting_approval"
    approval = trip.pending_approvals[0]
    _run(ex.resolve_approval("journey", approval.approval_id,
                             {"approved": True, "option_id": "off_test_1"}))
    trip = ex.get("journey")
    assert trip.status == "completed"
    assert trip.context["flight_book"]["pnr"] == "ATLAS-TEST12"
    names = [n.name for n in trip.trace]
    assert names.index("visa_check") < names.index("approve_booking")
    assert atlas.calls[-2:] == ["verify", "create"]


def test_full_journey_stale_visa_blocks_booking_recoverably(tmp_path):
    ex, atlas = _journey_executor(tmp_path)
    ex.register_skill("visa_check", VisaCheckSkill(web_intel=FakeWebIntel(degraded=True)))
    intent = TripIntent(
        intent_id="i2", raw_text="BKK SIN",
        goal=TripGoal(goal_id="g2", raw_text="BKK SIN", origin_city="BKK",
                      dest_city="SIN",
                      date_window={"start": "2026-09-28", "end": "2026-09-30"},
                      passengers=1),
        requested_services=RequestedServices(
            flight_search="requested", flight_booking="requested",
            visa_check="requested", hotel="not_requested",
            activities="not_requested", local_transport="not_requested"),
        scope_clarified=True)
    plan = plan_trip(intent)
    ex.start_trip("blocked", plan.nodes, context={
        "raw_text": intent.raw_text, "user_id": "victor",
        "profile": {"passport_country": "MM"},
        "requested_services": intent.requested_services.model_dump(),
    })
    _run(ex.run("blocked"))
    trip = ex.get("blocked")
    assert trip.status == "awaiting_approval"
    approval = trip.pending_approvals[0]
    _run(ex.resolve_approval("blocked", approval.approval_id,
                             {"approved": True, "option_id": "off_test_1"}))
    trip = ex.get("blocked")
    assert trip.status == "failed"
    failed = trip.trace[-1]
    assert failed.name == "flight_book"
    assert failed.status == "FAILED"
    assert failed.details["error_code"] == "visa_data_stale_or_unverified"
    assert failed.details["recoverable"] is True
    assert "create" not in atlas.calls  # never silently permitted


# --- G2-DA remediation: per-trip idempotency AFTER safety gates (finding 1) ------

class SequencedAtlas(FakeAtlas):
    """Issues a DISTINCT PNR per create call so foreign-PNR replay is visible."""

    def __init__(self):
        super().__init__()
        self._n = 0

    async def create_booking_order(self, offer_id, passenger, **kwargs):
        self._n += 1
        self.calls.append("create")
        return {"order_id": f"ORD-{self._n}", "pnr": f"PNR-{self._n}",
                "status": "CONFIRMED", "offer_id": offer_id,
                "booking_timestamp": "2026-08-26T12:00:00+00:00"}


def test_flight_book_cross_trip_reuse_with_stale_visa_hits_gate_not_replay():
    atlas = SequencedAtlas()
    skill = FlightBookSkill(atlas=atlas)
    _run(skill.run(_book_payload(),
                   context={**_fresh_visa_ctx(), "trip_id": "trip-A"}))
    stale = {"visa_check": {"freshness_state": "stale", "degraded": False,
                            "baseline_only": False, "requirements": []},
             "trip_id": "trip-B"}
    with pytest.raises(SkillError) as ei:
        _run(skill.run(_book_payload(), context=stale))
    assert ei.value.code == "visa_data_stale_or_unverified"
    assert atlas.calls.count("create") == 1  # trip B never replayed trip A's PNR


def test_flight_book_cross_trip_reuse_books_own_pnr_not_foreign():
    atlas = SequencedAtlas()
    skill = FlightBookSkill(atlas=atlas)
    first = _run(skill.run(_book_payload(),
                           context={**_fresh_visa_ctx(), "trip_id": "trip-A"}))
    second = _run(skill.run(_book_payload(),
                            context={**_fresh_visa_ctx(), "trip_id": "trip-B"}))
    assert first["pnr"] == "PNR-1"
    assert second["pnr"] == "PNR-2"           # own booking, never trip A's PNR
    assert second["idempotent_replay"] is False
    assert atlas.calls.count("create") == 2


def test_flight_book_same_trip_retry_still_idempotent():
    atlas = SequencedAtlas()
    skill = FlightBookSkill(atlas=atlas)
    first = _run(skill.run(_book_payload(),
                           context={**_fresh_visa_ctx(), "trip_id": "trip-A"}))
    retry = _run(skill.run(_book_payload(),
                           context={**_fresh_visa_ctx(), "trip_id": "trip-A"}))
    assert retry["pnr"] == first["pnr"] == "PNR-1"
    assert retry["idempotent_replay"] is True
    assert atlas.calls.count("create") == 1


# --- G2-DA remediation: unknown passport blocks booking (finding 5) --------------

def test_visa_check_empty_passport_is_blocking_unknown():
    skill = VisaCheckSkill(web_intel=FakeWebIntel())  # FRESH citations on purpose
    out = _run(skill.run({"passport_country": "", "route": ["BKK", "SIN"]}))
    assert out["passport_unknown"] is True
    assert out["freshness_state"] == "unknown"  # freshness cannot rescue it


def test_visa_check_unrecognized_passport_marks_unknown():
    skill = VisaCheckSkill(web_intel=FakeWebIntel())
    out = _run(skill.run({"passport_country": "XX", "route": ["BKK", "SIN"]}))
    assert out["passport_unknown"] is True


def test_unknown_passport_with_fresh_citations_never_books():
    atlas = SequencedAtlas()
    skill = FlightBookSkill(atlas=atlas)
    visa = {"freshness_state": "fresh", "degraded": False, "baseline_only": False,
            "passport_unknown": True, "requirements": []}
    with pytest.raises(SkillError) as ei:
        _run(skill.run(_book_payload(), context={"visa_check": visa,
                                                 "trip_id": "t"}))
    assert ei.value.code == "passport_unknown"
    assert ei.value.recoverable is True
    assert atlas.calls == []  # nothing verified, nothing booked


# --- LEADER ADDENDUM: visa BLOCKED_RISK refuses booking, no override --------------

def test_visa_check_blocked_route_returns_blocking_state_with_provenance():
    skill = VisaCheckSkill(web_intel=FakeWebIntel())
    out = _run(skill.run({"passport_country": "MM", "route": ["BKK", "FRA"]}))
    assert out["visa_blocked"] is True
    assert out["block_reasons"]           # block visible with reasons
    assert out["citations"]               # provenance still attached


def test_blocked_route_never_books_even_with_fresh_citations():
    atlas = SequencedAtlas()
    skill = FlightBookSkill(atlas=atlas)
    visa = {"freshness_state": "fresh", "degraded": False, "baseline_only": False,
            "passport_unknown": False, "visa_blocked": True,
            "block_reasons": ["FRA BLOCKED_RISK: Schengen ATV"], "requirements": []}
    with pytest.raises(SkillError) as ei:
        _run(skill.run(_book_payload(), context={"visa_check": visa,
                                                 "trip_id": "t"}))
    assert ei.value.code == "visa_route_blocked"
    assert ei.value.recoverable is False  # no user override of a hard block
    assert atlas.calls == []


def test_blocked_route_journey_reroutes_and_never_completes_booking(tmp_path):
    """§3.1 replan edge: VisaCheck ✗ -> back to FlightSearch; booking never fires."""
    ex, atlas = _journey_executor(tmp_path)
    phrase = "Fly me from BKK to Frankfurt on September 28, 2026."
    intent = TripIntent(
        intent_id="i3", raw_text=phrase,
        goal=TripGoal(goal_id="g3", raw_text=phrase, origin_city="BKK",
                      dest_city="FRA",
                      date_window={"start": "2026-09-28", "end": "2026-09-30"},
                      passengers=1),
        requested_services=RequestedServices(
            flight_search="requested", flight_booking="requested",
            visa_check="requested", hotel="not_requested",
            activities="not_requested", local_transport="not_requested"),
        scope_clarified=True)
    plan = plan_trip(intent)
    names = [n.name for n in plan.nodes]
    assert "flight_book" in names  # the plan still offers the chain...
    visa_node = next(n for n in plan.nodes if n.name == "visa_check")
    assert any(e.to == "flight_search" for e in visa_node.edges)  # ...with replan edge
    ex.start_trip("blocked-route", plan.nodes, context={
        "raw_text": intent.raw_text, "user_id": "victor",
        "profile": {"passport_country": "MM"},
        "requested_services": intent.requested_services.model_dump(),
    })
    _run(ex.run("blocked-route"))
    trip = ex.get("blocked-route")
    trace_names = [n.name for n in trip.trace]
    assert trace_names.count("flight_search") >= 2   # reroute back to search visible
    assert "flight_book" not in trace_names           # booking node never executed
    assert not trip.pending_approvals                 # no approval offered on block
    assert trip.status == "failed"                    # block visible, not "completed"
    assert trip.context.get("visa_check", {}).get("visa_blocked") is True
    assert "create" not in atlas.calls


# --- G2-DA remediation: sanitize recurses into lists (finding 6) ------------------

def test_sanitize_payload_recurses_into_lists_and_tuples():
    safe = sanitize_payload({
        "pnr": "ABC123",
        "passengers": [{"passport_no": "SENTINEL-PASS-001", "name": "Victor"},
                       {"passport_number": "SENTINEL-PASS-002", "name": "Vera"}],
        "docs": ({"national_id": "SENTINEL-NID-42"}, "plain"),
        "deep": {"rows": [{"nested": [{"document_number": "SENTINEL-DOC-1"}]}]},
    })
    dumped = json.dumps(safe, default=str)
    for secret in ("SENTINEL-PASS-001", "SENTINEL-PASS-002", "SENTINEL-NID-42", "SENTINEL-DOC-1"):
        assert secret not in dumped
    assert safe["passengers"][0]["name"] == "Victor"  # innocent fields survive
    assert safe["pnr"] == "ABC123"


# --- G2-DA remediation: per-trip disruption watches (finding 7) -------------------

def test_s11_arming_trip_b_does_not_overwrite_trip_a_watch():
    ex = TripGraphExecutor(registry=[], allow_unmanifested_skills=True)
    from services.trip_graph import NodeSpec
    from tests.test_trip_graph import EchoSkill
    ex.register_skill("echo", EchoSkill())
    for tid in ("tripA", "tripB"):
        ex.start_trip(tid, [NodeSpec(name="n", skill_ref="echo", edges=[])], {})
        _run(ex.run(tid))
    skill = DisruptionMonitorSkill(trip_registry=ex)
    _run(skill.run({"pnr": "P1", "flight_ids": ["f1"], "trip_id": "tripA"}))
    _run(skill.run({"pnr": "P2", "flight_ids": ["f2"], "trip_id": "tripB"}))
    before_a = len(ex.get("tripA").trace)
    before_b = len(ex.get("tripB").trace)
    out = _run(skill.simulate_disruption({"status": "CANCELLED"}, trip_id="tripA"))
    assert out["mounted"] is True
    assert out["trip_id"] == "tripA"
    assert len(ex.get("tripA").trace) == before_a + 1   # routed to A...
    assert len(ex.get("tripB").trace) == before_b       # ...never to B


def test_s11_simulate_disruption_validates_target_trip():
    ex = TripGraphExecutor(registry=[], allow_unmanifested_skills=True)
    from services.trip_graph import NodeSpec
    from tests.test_trip_graph import EchoSkill
    ex.register_skill("echo", EchoSkill())
    ex.start_trip("tripA", [NodeSpec(name="n", skill_ref="echo", edges=[])], {})
    _run(ex.run("tripA"))
    skill = DisruptionMonitorSkill(trip_registry=ex)
    _run(skill.run({"pnr": "P1", "flight_ids": ["f1"], "trip_id": "tripA"}))
    ghost = _run(skill.simulate_disruption({"status": "DELAYED"}, trip_id="ghost"))
    assert ghost["mounted"] is False            # unknown target refused
    _run(skill.run({"pnr": "P2", "flight_ids": ["f2"], "trip_id": "tripA"}))
    _run(skill.run({"pnr": "P3", "flight_ids": ["f3"], "trip_id": "tripA"}))
    # still a single trip armed -> implicit targeting remains deterministic
    out = _run(skill.simulate_disruption({"status": "CANCELLED"}))
    assert out["mounted"] is True and out["trip_id"] == "tripA"
