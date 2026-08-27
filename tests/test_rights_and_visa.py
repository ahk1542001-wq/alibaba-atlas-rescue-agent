"""Tests for the Claim Autopilot (rights_engine) and visa_guard."""

import asyncio

import pytest

from services.rights_engine import (
    JURISDICTIONS,
    _fallback_classify,
    build_evidence_pack,
    compute_entitlement,
    detect_jurisdictions,
)
from services.visa_guard import filter_and_rank


# ---------------------------------------------------------------- jurisdiction

def test_departure_from_eu_any_carrier():
    regs = detect_jurisdictions("FR", "TH", "FR")
    assert [r["id"] for r in regs] == ["EU261"]


def test_eu_arrival_requires_eu_carrier():
    # TH carrier arriving DE: NOT covered by EU261 (Art. 3(1))
    assert detect_jurisdictions("TH", "DE", "TH") == []
    # EU carrier arriving DE: covered
    assert detect_jurisdictions("TH", "DE", "DE")[0]["id"] == "EU261"


def test_uk_and_us_and_turkey():
    assert detect_jurisdictions("GB", "SG", "GB")[0]["id"] == "UK261"
    assert {r["id"] for r in detect_jurisdictions("US", "FR", "FR")} >= {"EU261", "US_DOT"}
    assert detect_jurisdictions("TR", "MM", "TR")[0]["id"] == "TURKEY_SHY"


def test_intra_asia_no_regime():
    assert detect_jurisdictions("TH", "VN", "TH") == []


# ---------------------------------------------------------------- entitlement

@pytest.mark.parametrize("km,currency,amount", [
    (500, "EUR", 250),
    (2000, "EUR", 400),
    (6000, "EUR", 600),
])
def test_eu_bands(km, currency, amount):
    ent = compute_entitlement("EU261", km)
    assert ent["fixed_cash_compensation"]["currency"] == currency
    assert ent["fixed_cash_compensation"]["amount"] == amount


def test_uk_amounts():
    comp = compute_entitlement("UK261", 6000)["fixed_cash_compensation"]
    assert comp["amount"] == 520
    assert comp["currency"] == "GBP"


def test_us_dot_no_fixed_cash():
    ent = compute_entitlement("US_DOT", 9000)
    assert ent["fixed_cash_compensation"] is None
    assert "refund" in ent["note"].lower()


# ---------------------------------------------------------------- classifier

def test_fallback_compensable_maintenance():
    out = _fallback_classify("Aircraft Maintenance / Engine Hydraulics", "EU261")
    assert out["classification"] == "COMPENSABLE"


def test_fallback_extraordinary_storm():
    out = _fallback_classify("Severe Tropical Storm / Air Traffic Hold", "EU261")
    assert out["classification"] == "EXTRAORDINARY"


def test_fallback_unknown_defaults_to_compensable_low_confidence():
    out = _fallback_classify("Operational Disruption", "EU261")
    if out["classification"] == "COMPENSABLE":
        assert out["confidence"] <= 70  # burden of proof is on the airline


# ---------------------------------------------------------------- evidence pack

def test_evidence_pack_structure():
    claim = {
        "jurisdiction_id": "EU261",
        "airline": "Air France",
        "flight_number": "AF198",
        "date": "2026-08-20",
        "passenger_name": "Aung Hein Kyaw",
        "reason": "Aircraft Maintenance",
        "disruption_type": "CANCELLED",
        "classification": "COMPENSABLE",
        "entitlement": compute_entitlement("EU261", 9200),
    }
    pack = build_evidence_pack(claim)
    assert len(pack["checklist"]) >= 5
    assert all("item" in d and "why" in d for d in pack["checklist"])
    assert "No 261/2004" in pack["claim_letter"]
    assert "AF198" in pack["claim_letter"]
    assert "EUR 600" in pack["claim_letter"]
    assert "Aung Hein Kyaw" in pack["claim_letter"]


# ---------------------------------------------------------------- visa guard

OFFERS = [
    {"airline_code": "LH", "stops": 1, "via": ["FRA"], "price_usd": 300},
    {"airline_code": "EK", "stops": 1, "via": ["DXB"], "price_usd": 420},
    {"airline_code": "TG", "stops": 1, "via": ["FRA"], "price_usd": 350},
]


def test_mm_passport_blocks_schengen_transit():
    res = filter_and_rank("MM", OFFERS)
    assert res["blocked_count"] == 2
    # EK via DXB is clear and must rank first despite highest price
    assert res["offers"][0]["airline_code"] == "EK"
    assert res["offers"][0]["visa_status"] == "CLEAR"
    risky = [o for o in res["offers"] if o["visa_status"] == "BLOCKED_RISK"]
    assert {o["airline_code"] for o in risky} == {"LH", "TG"}
    assert any("ATV" in o["visa_note"] or "Schengen" in o["visa_note"] for o in risky)


def test_uk_passport_sees_no_risk():
    res = filter_and_rank("GB", OFFERS)
    assert res["blocked_count"] == 0
    assert all(o["visa_status"] == "CLEAR" for o in res["offers"])


def test_unknown_nationality_flagged_not_crashed():
    res = filter_and_rank("ZZ", OFFERS)
    assert all(o["visa_status"] == "UNKNOWN" for o in res["offers"])


def test_direct_flight_always_clear():
    res = filter_and_rank("MM", [{"airline_code": "TG", "stops": 0, "price_usd": 500}])
    assert res["offers"][0]["visa_status"] == "CLEAR"


# ---------------------------------------------------------------- guardian

def test_guardian_simulates_without_credentials(monkeypatch):
    from services import guardian

    monkeypatch.setattr(guardian.settings, "telegram_bot_token", "")
    monkeypatch.setattr(guardian.settings, "telegram_chat_id", "")
    out = asyncio.run(guardian.notify("t", "b"))
    assert out["simulated"] is True and out["sent"] is False


def test_guardian_requires_token_chat_and_live_flag_and_returns_preview(monkeypatch):
    from services import guardian

    monkeypatch.setattr(guardian.settings, "telegram_bot_token", "configured")
    monkeypatch.setattr(guardian.settings, "telegram_chat_id", "")
    monkeypatch.setattr(guardian.settings, "telegram_live_test", False)
    out = asyncio.run(guardian.notify("Trip alert", "Route BKK-SIN"))
    assert out["channel"] == "telegram"
    assert out["simulated"] is True and out["sent"] is False
    assert out["preview"] == "🛟 Trip alert\n\nRoute BKK-SIN"
    assert "mocked_text" not in out
    assert "live" in out["reason"].lower()


def test_rule_tables_consistent():
    for jid in ("EU261", "UK261", "TURKEY_SHY"):
        bands = JURISDICTIONS[jid]["distance_bands_km"]
        assert bands[-1]["max_km"] is None
        amounts = [b["amount"] for b in bands]
        assert amounts == sorted(amounts)
