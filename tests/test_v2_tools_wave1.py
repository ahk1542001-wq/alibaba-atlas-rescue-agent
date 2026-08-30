import json
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from main import app

from services.qwen_brain.tools.flight import FlightSearchTool
from services.qwen_brain.tools.visa import VisaCheckTool
from services.qwen_brain.tools.rights import RightsCheckTool
from services.qwen_brain.tools.safety import SafetyCheckTool


@pytest.mark.anyio
async def test_flight_search_tool_happy_path(monkeypatch):
    from services.atlas_client import AtlasClient
    dummy_offers = [
        {
            "offer_id": "off_test_1",
            "flight_number": "TG401",
            "airline": "Thai Airways",
            "airline_code": "TG",
            "origin": "BKK",
            "destination": "SIN",
            "departure_time": "2026-09-28T08:00:00",
            "arrival_time": "2026-09-28T11:25:00",
            "duration_minutes": 145,
            "stops": 0,
            "via": [],
            "cabin_class": "economy",
            "price_usd": 150.0,
            "seats_available": 5,
        }
    ]
    monkeypatch.setattr(AtlasClient, "search_flights", AsyncMock(return_value=dummy_offers))

    tool = FlightSearchTool()
    res_str = tool.call(json.dumps({"origin": "BKK", "destination": "SIN", "date": "2026-09-28"}))
    data = json.loads(res_str)

    assert data["source"] == "atlas_sandbox"
    assert data["provenance"] == "atlas_sandbox"
    assert data["offer_count"] == 1
    assert len(data["offers"]) == 1
    assert data["offers"][0]["offer_id"] == "off_test_1"


def test_flight_search_tool_resilience():
    tool = FlightSearchTool()
    res_str = tool.call("invalid-json")
    data = json.loads(res_str)
    assert data["status"] == "failed"
    assert "error" in data


def test_visa_check_tool_happy_path():
    tool = VisaCheckTool()
    res_str = tool.call(json.dumps({"passport": "MM", "origin": "BKK", "destination": "SIN"}))
    data = json.loads(res_str)

    assert data["passport"] == "MM"
    assert data["passport_name"] == "Myanmar"
    assert "destination_rule" in data
    assert "route_assessment" in data


def test_visa_check_tool_resilience():
    tool = VisaCheckTool()
    res_str = tool.call("malformed-json")
    data = json.loads(res_str)
    assert data["status"] == "failed"
    assert "error" in data


def test_rights_check_tool_happy_path():
    tool = RightsCheckTool()
    res_str = tool.call(json.dumps({"origin": "FRA", "destination": "JFK"}))
    data = json.loads(res_str)

    assert data["origin_country"] == "DE"
    assert data["destination_country"] == "US"
    assert "EU261" in data["applicable_jurisdictions"]
    assert len(data["entitlements"]) >= 1


def test_rights_check_tool_none_regime():
    tool = RightsCheckTool()
    res_str = tool.call(json.dumps({"origin": "BKK", "destination": "RGN"}))
    data = json.loads(res_str)

    assert data["origin_country"] == "TH"
    assert data["destination_country"] == "MM"
    assert data["applicable_jurisdictions"] == []
    assert "No fixed-cash-compensation regime" in data["note"]


def test_safety_check_tool_happy_path():
    tool = SafetyCheckTool()
    res_str = tool.call(json.dumps({"destination": "SG", "origin": "TH"}))
    data = json.loads(res_str)

    assert "assessment" in data
    assert "overall_status" in data["assessment"]
    assert "provenance_label" in data


def test_safety_check_tool_resilience():
    tool = SafetyCheckTool()
    res_str = tool.call("malformed")
    data = json.loads(res_str)
    assert data["status"] == "failed"
    assert "error" in data


def test_concierge_endpoint_under_both_brains(monkeypatch):
    client = TestClient(app)

    # 1. Legacy brain concierge call
    monkeypatch.setenv("TRAVELCARE_BRAIN", "legacy")
    res_legacy = client.post("/api/chat/concierge", json={
        "query": "Hello concierge, can you help me?",
        "user_id": "concierge_user_1",
    })
    assert res_legacy.status_code == 200
    legacy_data = res_legacy.json()
    assert "reply" in legacy_data
    assert "action_taken" in legacy_data

    # 2. Qwen agent brain concierge call
    monkeypatch.setenv("TRAVELCARE_BRAIN", "qwen_agent")
    res_qwen = client.post("/api/chat/concierge", json={
        "query": "Hello concierge, can you help me?",
        "user_id": "concierge_user_2",
    })
    assert res_qwen.status_code == 200
    qwen_data = res_qwen.json()
    assert "reply" in qwen_data
    assert "action_taken" in qwen_data


# ============================================================================
# §9.4 wave-1 gate suite (audit finding #6): ≥5 scripted inputs per tool,
# tool.call output EQUAL to the legacy skill/engine output on all
# deterministic fields; mocked-Assistant tool-selection (5 phrasings/tool);
# safety do_not_travel propagation.
# ============================================================================

import asyncio
import datetime

from services import rights_engine, visa_guard
from services.atlas_client import AtlasClient
from services.safety.adapters import normalize_level_from_text
from services.safety.policy import normalize_country
from models.schemas import SafetyEvidence, SafetySourceReport
from services.skills.safety_research import SafetyResearchSkill


def _run_sync(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# --- flight_search: ≥5 scripted inputs, parity vs legacy AtlasClient --------

FLIGHT_INPUTS = [
    {"origin": "BKK", "destination": "SIN", "date": "2026-09-28"},
    {"origin": "BKK", "destination": "RGN", "date": "2026-10-01"},
    {"origin": "SIN", "destination": "FRA", "date": "2026-11-05"},
    {"origin": "DMK", "destination": "RGN", "date": "2026-09-29"},
    {"origin": "FRA", "destination": "BKK", "date": "2026-12-12"},
]

_OFFER_FIELDS_T = (
    "offer_id", "flight_number", "airline", "airline_code", "origin",
    "destination", "departure_time", "arrival_time", "duration_minutes",
    "stops", "via", "cabin_class", "price_usd", "seats_available",
)


def _canned_offers(origin, destination, date):
    return [{
        "offer_id": f"off_{origin}_{destination}_{i}",
        "flight_number": f"XX{100 + i}",
        "airline": "Atlas Sandbox Air",
        "airline_code": "XX",
        "origin": origin,
        "destination": destination,
        "departure_time": f"{date}T0{6 + i}:00:00",
        "arrival_time": f"{date}T0{8 + i}:30:00",
        "duration_minutes": 150 + i,
        "stops": 0,
        "via": [],
        "cabin_class": "economy",
        "price_usd": 100.0 + 10 * i,
        "seats_available": 9 - i,
    } for i in range(2)]


@pytest.mark.parametrize("inp", FLIGHT_INPUTS)
def test_flight_search_parity_with_legacy_client(monkeypatch, inp):
    async def canned(*args):  # class-level patch: last 3 args are (o, d, date)
        origin, destination, date = args[-3:]
        return _canned_offers(origin, destination, date)
    monkeypatch.setattr(AtlasClient, "search_flights", canned)

    # legacy path: the deterministic sandbox client itself
    legacy_offers = _run_sync(
        AtlasClient().search_flights(inp["origin"], inp["destination"], inp["date"]))
    # qwen tool path
    data = json.loads(FlightSearchTool().call(json.dumps(inp)))

    assert data["source"] == "atlas_sandbox"
    assert data["provenance"] == "atlas_sandbox"
    assert data["query"] == inp
    assert data["offer_count"] == len(legacy_offers)
    expected_trim = [{k: o.get(k) for k in _OFFER_FIELDS_T if k in o}
                     for o in legacy_offers[:10]]
    assert data["offers"] == expected_trim, "tool must not mutate engine offers"
    assert data["offers_returned"] == len(expected_trim)


# --- visa_check: ≥5 scripted inputs, parity vs legacy visa_guard ------------

VISA_INPUTS = [
    {"passport": "MM", "origin": "BKK", "destination": "SIN"},
    {"passport": "MM", "origin": "BKK", "destination": "RGN"},
    {"passport": "US", "origin": "FRA", "destination": "SIN"},
    {"passport": "GB", "origin": "BKK", "destination": "SIN"},
    {"passport": "ZZ", "origin": "BKK", "destination": "SIN"},
]


@pytest.mark.parametrize("inp", VISA_INPUTS)
def test_visa_check_parity_with_legacy_engine(inp):
    # legacy deterministic engine (services/visa_guard.py)
    rule_entry = visa_guard.VISA_RULES.get(inp["passport"])
    expected_rule = (rule_entry or {}).get("hubs", {}).get(inp["destination"]) or {
        "status": "UNKNOWN",
        "note": "No explicit rule for this destination; verify manually.",
    }
    expected_assess = visa_guard.assess_offer(inp["passport"], {
        "origin": inp["origin"], "destination": inp["destination"],
        "stops": 0, "via": [inp["destination"]],
    })

    data = json.loads(VisaCheckTool().call(json.dumps(inp)))
    assert data["status"] == "success"
    assert data["passport"] == inp["passport"]
    assert data["passport_name"] == ((rule_entry or {}).get("name") or inp["passport"])
    assert data["destination_rule"] == expected_rule
    assert data["route_assessment"] == expected_assess, \
        "tool must not mutate visa_guard assessment"
    assert data["as_of"] == datetime.date.today().isoformat()


# --- rights_check: ≥5 scripted inputs, parity vs legacy rights_engine -------

RIGHTS_INPUTS = [
    {"origin": "FRA", "destination": "JFK"},
    {"origin": "BKK", "destination": "RGN"},
    {"origin": "SIN", "destination": "BKK"},
    {"origin": "LHR", "destination": "JFK"},
    {"origin": "BKK", "destination": "DMK"},
]


@pytest.mark.parametrize("inp", RIGHTS_INPUTS)
def test_rights_check_parity_with_legacy_engine(inp):
    o_country, d_country, _ = rights_engine.airports_to_countries(
        inp["origin"], inp["destination"])
    jurisdictions = rights_engine.detect_jurisdictions(o_country, d_country)
    distance_km = rights_engine.route_distance_km(inp["origin"], inp["destination"])
    expected_entitlements = [
        rights_engine.compute_entitlement(j["id"], distance_km)
        for j in jurisdictions
    ]

    data = json.loads(RightsCheckTool().call(json.dumps(inp)))
    assert data["status"] == "success"
    assert data["origin_country"] == o_country
    assert data["destination_country"] == d_country
    assert data["route_distance_km"] == distance_km
    assert data["applicable_jurisdictions"] == [j["id"] for j in jurisdictions]
    assert data["entitlements"] == expected_entitlements, \
        "tool must not mutate rights_engine entitlements"


# --- safety_check: ≥5 scripted inputs, parity via injected deterministic ----
# evidence (the deterministic SafetyPolicyEngine computes the status).

SAFETY_INPUTS = [
    ("SG", "Level 1: Exercise normal precautions."),
    ("TH", "Level 2: Exercise increased caution."),
    ("MM", "Level 3: Reconsider travel."),
    ("XX", "Level 4: Do not travel."),
    ("SG", "No recognizable official level wording here."),
]


class _FixedSafetyAdapter:
    # a REAL registered source id + allowlisted host (the engine rejects
    # unknown sources — the honesty gate is part of what we parity-test)
    source_id = "us_state"

    def __init__(self, level_text):
        self._text = level_text

    async def collect(self, query, fetch):
        normalized = normalize_level_from_text(self._text) or "unable_to_verify"
        ev = SafetyEvidence(
            source_id=self.source_id,
            authority="U.S. Department of State",
            canonical_url="https://travel.state.gov/en/traveladvisories/hermetic-test",
            title="Hermetic test advisory",
            retrieved_at="2026-08-31T00:00:00Z",
            country=query.destination_country,
            native_level=self._text,
            normalized_level=normalized,
            verification_status="verified",
            freshness="fresh",
        )
        report = SafetySourceReport(source_id=self.source_id, status="ok",
                                    evidence_count=1)
        return [ev], report


def _deterministic_assessment(assessment: dict) -> dict:
    """All assessment fields except the volatile checked_at timestamp."""
    a = dict(assessment)
    a.pop("checked_at", None)
    return a


@pytest.mark.parametrize("dest, level_text", SAFETY_INPUTS)
def test_safety_check_parity_with_legacy_skill(dest, level_text):
    skill = SafetyResearchSkill(adapters=[_FixedSafetyAdapter(level_text)])
    # mirror the tool's deterministic input boundary (country normalization)
    norm = normalize_country(dest) or dest.upper()
    legacy = _run_sync(skill.run({"destination_country": norm}))

    tool = SafetyCheckTool(skill=skill)
    data = json.loads(tool.call(json.dumps({"destination": dest})))
    assert data["status"] == "success"
    # the deterministic SafetyPolicyEngine output must pass through unmutated
    # (checked_at is a run timestamp, not a deterministic engine field)
    assert _deterministic_assessment(data["assessment"]) == \
        _deterministic_assessment(legacy["assessment"]), \
        "tool must not mutate the safety engine assessment"
    expected_level = normalize_level_from_text(level_text) or "unable_to_verify"
    assert data["assessment"]["overall_status"] == expected_level


def test_safety_do_not_travel_propagates_unmutated():
    skill = SafetyResearchSkill(
        adapters=[_FixedSafetyAdapter("Level 4: Do not travel.")])
    data = json.loads(SafetyCheckTool(skill=skill).call(
        json.dumps({"destination": "XX"})))
    assert data["assessment"]["trip_policy_status"] == "do_not_travel"
    assert data["assessment"]["overall_status"] == "do_not_travel"
    # parity with the direct engine/skill output
    legacy = _run_sync(skill.run({"destination_country": "XX"}))
    assert _deterministic_assessment(data["assessment"]) == \
        _deterministic_assessment(legacy["assessment"])


# --- mocked-Assistant tool selection: 5 scripted phrasings per tool ---------

SELECTION_PHRASINGS = [
    ("flight_search", "Find me flights from BKK to SIN on 2026-09-28",
     {"origin": "BKK", "destination": "SIN", "date": "2026-09-28"}),
    ("flight_search", "Search flights Bangkok to Singapore on September 28",
     {"origin": "BKK", "destination": "SIN", "date": "2026-09-28"}),
    ("flight_search", "What flights are available BKK to RGN on 2026-10-01?",
     {"origin": "BKK", "destination": "RGN", "date": "2026-10-01"}),
    ("flight_search", "Show me air options SIN to FRA on 2026-11-05",
     {"origin": "SIN", "destination": "FRA", "date": "2026-11-05"}),
    ("flight_search", "I need a flight DMK to RGN on 2026-09-29",
     {"origin": "DMK", "destination": "RGN", "date": "2026-09-29"}),
    ("visa_check", "Do I need a visa for Singapore with a Myanmar passport?",
     {"passport": "MM", "origin": "BKK", "destination": "SIN"}),
    ("visa_check", "Visa requirements for MM passport going to SIN",
     {"passport": "MM", "origin": "BKK", "destination": "SIN"}),
    ("visa_check", "Check visa rules for a Myanmar citizen entering Thailand",
     {"passport": "MM", "origin": "RGN", "destination": "BKK"}),
    ("visa_check", "Is there a visa rule for MM passport traveling to RGN?",
     {"passport": "MM", "origin": "BKK", "destination": "RGN"}),
    ("visa_check", "visa check passport MM destination SIN origin BKK",
     {"passport": "MM", "origin": "BKK", "destination": "SIN"}),
    ("rights_check", "What are my passenger rights for FRA to JFK?",
     {"origin": "FRA", "destination": "JFK"}),
    ("rights_check", "EU261 compensation for a Frankfurt New York flight",
     {"origin": "FRA", "destination": "JFK"}),
    ("rights_check", "Rights for a delayed flight BKK to RGN",
     {"origin": "BKK", "destination": "RGN"}),
    ("rights_check", "Do I get compensation for a cancelled FRA SIN flight?",
     {"origin": "FRA", "destination": "SIN"}),
    ("rights_check", "air passenger rights Bangkok Yangon delay",
     {"origin": "BKK", "destination": "RGN"}),
    ("safety_check", "Is Singapore safe to travel to right now?",
     {"destination": "SG"}),
    ("safety_check", "Travel advisory for Thailand",
     {"destination": "TH"}),
    ("safety_check", "What is the safety situation in Myanmar?",
     {"destination": "MM"}),
    ("safety_check", "Any official travel warnings for SG?",
     {"destination": "SG"}),
    ("safety_check", "Check official safety advisories for destination MM",
     {"destination": "MM"}),
]


class _FakeSelectionLLM:
    """Mocked model: 'selects' the scripted tool for the scripted phrasing.
    LLM involvement is limited to tool SELECTION (§9.4) — everything the
    answer contains must still come from the deterministic tool."""

    def __init__(self, tool_name, arguments):
        self.tool_name = tool_name
        self.arguments = arguments
        self.calls = 0

    def chat(self, messages=None, functions=None, stream=True,
             extra_generate_cfg=None, **kwargs):
        from qwen_agent.llm.schema import FunctionCall, Message
        self.calls += 1
        if self.calls == 1:
            yield [Message(role="assistant", content="",
                           extra={"function_id": "1"},
                           function_call=FunctionCall(
                               name=self.tool_name,
                               arguments=json.dumps(self.arguments)))]
        else:
            yield [Message(role="assistant", content="Here is the result.")]


@pytest.mark.parametrize("expected_tool, phrase, args", SELECTION_PHRASINGS)
def test_mocked_assistant_selects_and_dispatches_expected_tool(
        monkeypatch, expected_tool, phrase, args):
    from qwen_agent.tools.base import TOOL_REGISTRY
    from services import llm_providers
    from services.qwen_brain.agent import build_travelcare_agent

    async def canned(*args):  # class-level patch: last 3 args are (o, d, date)
        origin, destination, date = args[-3:]
        return _canned_offers(origin, destination, date)
    monkeypatch.setattr(AtlasClient, "search_flights", canned)
    monkeypatch.setattr(llm_providers, "resolve_llm_cfg", lambda: {
        "model": "mock/model", "model_server": "http://mock.invalid/v1",
        "api_key": "mock-key", "generate_cfg": {}})

    bot = build_travelcare_agent()
    assert bot is not None
    # the requested tool must be a registered qwen-agent tool on this agent
    assert expected_tool in TOOL_REGISTRY
    assert expected_tool in bot.function_map
    # keep the safety tool hermetic (deterministic injected evidence)
    if expected_tool == "safety_check":
        bot.function_map["safety_check"] = SafetyCheckTool(
            skill=SafetyResearchSkill(
                adapters=[_FixedSafetyAdapter("Level 1: Exercise normal precautions.")]))

    bot.llm = _FakeSelectionLLM(expected_tool, args)
    history = []
    for history in bot.run(messages=[{"role": "user", "content": phrase}],
                           stream=False):
        pass
    def _role(m):
        return m.get("role") if isinstance(m, dict) else getattr(m, "role", None)

    def _name(m):
        return m.get("name") if isinstance(m, dict) else getattr(m, "name", None)

    def _content(m):
        return m.get("content") if isinstance(m, dict) else getattr(m, "content", None)

    fn_msgs = [m for m in history
               if _role(m) == "function" and _name(m) == expected_tool]
    assert fn_msgs, f"Assistant never dispatched '{expected_tool}' for: {phrase}"
    result = json.loads(_content(fn_msgs[-1]))
    assert result.get("status") != "failed", result
