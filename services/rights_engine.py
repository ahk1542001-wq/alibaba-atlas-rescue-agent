"""Passenger Rights Engine — the Claim Autopilot.

Multi-jurisdiction air-passenger-rights intelligence:
  - Detects which regime(s) apply to a disrupted itinerary (EU261, UK261,
    US DOT, Turkey SHY-Passenger).
  - Computes the exact cash entitlement by distance band.
  - Classifies the disruption cause via Qwen legal reasoning (own-crew
    strike = compensable; ATC / weather = extraordinary) with a
    deterministic keyword fallback when the LLM is unavailable.
  - Builds an evidence pack and drafts formal claim + appeal letters that
    cite the governing regulation article.

Research basis (2026-08): ~EUR 5.9B/year EU261 entitlement goes unclaimed;
airlines wrongfully reject ~52% of claims citing "extraordinary circumstances".
"""

import logging
from typing import Any, Dict, List, Optional

from services import llm

logger = logging.getLogger("rights")

# --------------------------------------------------------------------------
# Jurisdiction rule tables (grounded on published regulations)
# --------------------------------------------------------------------------

_COMPENSABLE_CAUSES = [
    "own-crew strike", "airline operational", "technical", "maintenance",
    "overbooking", "denied boarding", "crew rotation", "late inbound aircraft",
]

_EXTRAORDINARY_CAUSES = [
    "weather", "storm", "monsoon", "atc", "air traffic control", "security",
    "third-party strike", "ground handling strike", "bird strike",
    "airport closure", "political instability", "war",
]

JURISDICTIONS: Dict[str, Dict[str, Any]] = {
    "EU261": {
        "name": "EU Regulation 261/2004",
        "citation": "Regulation (EC) No 261/2004, Art. 5(1)(c) and Art. 7",
        "trigger": (
            "Flight departs from an EU/EEA airport (any carrier), or arrives "
            "in the EU/EEA on an EU-licensed carrier."
        ),
        "distance_bands_km": [
            {"max_km": 1500, "currency": "EUR", "amount": 250},
            {"max_km": 3500, "currency": "EUR", "amount": 400},
            {"max_km": None, "currency": "EUR", "amount": 600},
        ],
        "compensable_causes": _COMPENSABLE_CAUSES,
        "extraordinary_causes": _EXTRAORDINARY_CAUSES,
        "duty_of_care": "Meals after 2h; hotel + transfers overnight. Cause-blind.",
        "refund_or_reroute": "Refund or re-routing at passenger's choice. Cause-blind.",
    },
    "UK261": {
        "name": "UK Air Passenger Rights (retained EU261)",
        "citation": "UK retained Regulation EC 261/2004, Art. 5 & 7",
        "trigger": (
            "Flight departs from a UK airport (any carrier), or arrives in "
            "the UK on a UK-licensed carrier."
        ),
        "distance_bands_km": [
            {"max_km": 1500, "currency": "GBP", "amount": 220},
            {"max_km": 3500, "currency": "GBP", "amount": 350},
            {"max_km": None, "currency": "GBP", "amount": 520},
        ],
        "compensable_causes": _COMPENSABLE_CAUSES,
        "extraordinary_causes": _EXTRAORDINARY_CAUSES,
        "duty_of_care": "Mirrors EU261 duty-of-care tiers.",
        "refund_or_reroute": "Refund or re-routing at passenger's choice.",
    },
    "US_DOT": {
        "name": "US DOT Consumer Protection",
        "citation": "14 CFR Part 259; DOT automatic cash refund rule (2024)",
        "trigger": "Any flight segment operated within, to, or from the United States.",
        "cash_note": (
            "No fixed cash compensation for delays/cancellations. Mandatory full "
            "cash refund when the airline cancels or materially changes the flight "
            "and the passenger declines rebooking. Denied boarding: up to 400% of "
            "one-way fare, capped USD 2,150."
        ),
        "duty_of_care": "Tarmac-delay contingency plans (>3h domestic). No federal meal/hotel mandate.",
        "refund_or_reroute": "Automatic cash refund (2024 rule).",
    },
    "TURKEY_SHY": {
        "name": "Turkey SHY-Passenger Regulation",
        "citation": "SHY-Passenger (SGM 292), enforced by Turkish HSK",
        "trigger": (
            "Flights departing from Turkey on any carrier, or arriving in "
            "Turkey on a Turkish carrier."
        ),
        "distance_bands_km": [
            {"max_km": 1500, "currency": "EUR", "amount": 250},
            {"max_km": 4000, "currency": "EUR", "amount": 400},
            {"max_km": None, "currency": "EUR", "amount": 600},
        ],
        "compensable_causes": _COMPENSABLE_CAUSES,
        "extraordinary_causes": _EXTRAORDINARY_CAUSES,
        "duty_of_care": "Mirrors EU261 duty-of-care tiers.",
        "refund_or_reroute": "Refund or re-routing at passenger's choice.",
    },
}

_EU_EEA = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
    "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK",
    "SI", "ES", "SE", "IS", "LI", "NO",
}


def detect_jurisdictions(
    origin_country: str, dest_country: str, carrier_country: str = ""
) -> List[Dict[str, Any]]:
    """Return every regime that plausibly covers this itinerary, best first."""
    o = (origin_country or "").upper()
    d = (dest_country or "").upper()
    c = (carrier_country or "").upper()
    found: List[Dict[str, Any]] = []

    if o in _EU_EEA or (d in _EU_EEA and c in _EU_EEA):
        found.append({"id": "EU261", **JURISDICTIONS["EU261"]})
    if o == "GB" or (d == "GB" and c == "GB"):
        found.append({"id": "UK261", **JURISDICTIONS["UK261"]})
    if o == "TR" or (d == "TR" and c == "TR"):
        found.append({"id": "TURKEY_SHY", **JURISDICTIONS["TURKEY_SHY"]})
    if o == "US" or d == "US":
        found.append({"id": "US_DOT", **JURISDICTIONS["US_DOT"]})
    return found


def compute_entitlement(jurisdiction_id: str, distance_km: int) -> Dict[str, Any]:
    """Distance-band cash entitlement under one regime."""
    j = JURISDICTIONS.get(jurisdiction_id)
    if not j or "distance_bands_km" not in j:
        return {
            "jurisdiction": jurisdiction_id,
            "fixed_cash_compensation": None,
            "note": j.get("cash_note") if j else "Unknown jurisdiction",
        }
    for band in j["distance_bands_km"]:
        if band["max_km"] is None or distance_km <= band["max_km"]:
            return {
                "jurisdiction": jurisdiction_id,
                "fixed_cash_compensation": {
                    "currency": band["currency"],
                    "amount": band["amount"],
                    "band_max_km": band["max_km"],
                },
            }
    return {"jurisdiction": jurisdiction_id, "fixed_cash_compensation": None}


# --------------------------------------------------------------------------
# Cause classification (Qwen legal reasoning + deterministic fallback)
# --------------------------------------------------------------------------

_CLASSIFY_SYSTEM = (
    "You are an air-passenger-rights legal analyst. Given a disruption reason "
    "stated by an airline and the governing regulation context, classify the "
    "cause as COMPENSABLE or EXTRAORDINARY. Airline-internal problems (crew "
    "rotation, maintenance, own-crew strikes) are compensable. Weather, ATC, "
    "security, third-party strikes are extraordinary. Reply ONLY with compact JSON: "
    '{"classification": "COMPENSABLE" | "EXTRAORDINARY", "confidence": 0-100, '
    '"legal_reasoning": "<=40 words citing the regulation logic", '
    '"key_article": "e.g. Art. 5(3)"}'
)


def _fallback_classify(reason: str, jurisdiction_id: str) -> Dict[str, Any]:
    r = (reason or "").lower()
    comp_kw = ["maintenance", "hydraulic", "technical", "operational",
               "rotation", "crew", "overbook", "denied boarding"]
    extra_kw = ["storm", "weather", "monsoon", "atc", "air traffic",
                "security", "bird strike", "closure", "political", "war"]
    if any(k in r for k in extra_kw):
        cls, conf = "EXTRAORDINARY", 70
    elif any(k in r for k in comp_kw):
        cls, conf = "COMPENSABLE", 70
    else:
        cls, conf = "COMPENSABLE", 50  # burden of proof is on the airline
    return {
        "classification": cls,
        "confidence": conf,
        "legal_reasoning": (
            f"Deterministic keyword match under {jurisdiction_id}: airline-internal "
            "causes are compensable; the burden of proving extraordinary "
            "circumstances lies with the carrier."
        ),
        "key_article": JURISDICTIONS[jurisdiction_id]["citation"] if jurisdiction_id in JURISDICTIONS else "",
        "engine": "fallback-keywords",
    }


async def classify_cause(reason: str, jurisdiction_id: str) -> Dict[str, Any]:
    """Classify a stated disruption cause under one regime via Qwen."""
    j = JURISDICTIONS.get(jurisdiction_id)
    prompt = (
        f"Governing regime: {jurisdiction_id} ({j['name'] if j else 'unknown'}). "
        f"Cause list — compensable: {j['compensable_causes'] if j else []}; "
        f"extraordinary: {j['extraordinary_causes'] if j else []}. "
        f"Airline-stated disruption reason: \"{reason}\""
    )
    reply = await llm.chat(
        [{"role": "system", "content": _CLASSIFY_SYSTEM},
         {"role": "user", "content": prompt}],
        max_tokens=220,
        temperature=0.2,
    )
    parsed = llm.parse_json(reply)
    if isinstance(parsed, dict) and "classification" in parsed:
        parsed.setdefault("confidence", 60)
        parsed["engine"] = "qwen"
        return parsed
    logger.warning("rights: LLM classify failed, using fallback")
    return _fallback_classify(reason, jurisdiction_id)


# --------------------------------------------------------------------------
# Evidence pack + claim letter + appeal letter
# --------------------------------------------------------------------------

def build_evidence_pack(claim: Dict[str, Any]) -> Dict[str, Any]:
    """Checklist of documents that win the claim + formal claim letter."""
    jur_id = claim.get("jurisdiction_id", "")
    j = JURISDICTIONS.get(jur_id, {})
    docs = [
        {"item": "Booking confirmation / PNR", "why": "Proves contract of carriage"},
        {"item": "Boarding pass (original)", "why": "Proves you were checked in and denied/cancelled"},
        {"item": "Cancellation / delay notification (screenshot)", "why": "Primary evidence of disruption + stated reason"},
        {"item": "Rebooking or refund receipt", "why": "Supports duty-of-care and refund claims"},
        {"item": "Receipts for meals/hotel during delay", "why": f"Duty of care: {j.get('duty_of_care', 'per regulation')}"},
        {"item": "Correspondence with airline", "why": "Locks the airline to its stated cause"},
    ]
    ent = claim.get("entitlement") or {}
    cash = ent.get("fixed_cash_compensation") if ent else None
    amount_line = (
        f"{cash['currency']} {cash['amount']}" if cash
        else (cash.get("note") if isinstance(cash, dict) else None) or "per regulation"
    )
    letter = (
        f"To: {claim.get('airline', 'Airline Customer Relations')}\n\n"
        f"Subject: Compensation claim under {j.get('citation', jur_id)} — "
        f"flight {claim.get('flight_number', '')}, {claim.get('date', '')}\n\n"
        "Dear Sir or Madam,\n\n"
        f"My flight {claim.get('flight_number', '')} on {claim.get('date', '')} was "
        f"{claim.get('disruption_type', 'disrupted')} due to \"{claim.get('reason', '')}\". "
        f"This cause is {str(claim.get('classification', '')).lower()} and therefore not an "
        "extraordinary circumstance exempt from compensation.\n\n"
        f"Under {j.get('citation', jur_id)}, I am entitled to {amount_line}. "
        f"I request payment within 14 days.\n\n"
        "Yours faithfully,\n"
        f"{claim.get('passenger_name', 'Passenger')}"
    )
    return {
        "checklist": docs,
        "claim_letter": letter,
        "citation": j.get("citation", jur_id),
        "requested_amount": cash,
    }


async def draft_appeal(claim: Dict[str, Any], rejection_reason: str) -> Dict[str, Any]:
    """Qwen-drafted appeal letter countering an airline rejection."""
    jur_id = claim.get("jurisdiction_id", "EU261")
    j = JURISDICTIONS.get(jur_id, JURISDICTIONS["EU261"])
    system = (
        "You write firm, polite air-passenger-rights appeal letters. You cite the "
        "regulation article, rebut the airline's stated ground for rejection, note "
        "that the burden of proof for extraordinary circumstances lies with the "
        "carrier, mention escalation to the competent enforcement body / ADR "
        "scheme, and demand payment within 14 days. Plain text only, <=200 words."
    )
    user_prompt = (
        f"Regime: {j['name']} ({j['citation']}).\n"
        f"Flight {claim.get('flight_number','')} on {claim.get('date','')}; "
        f"passenger {claim.get('passenger_name','')}.\n"
        f"Disruption reason: \"{claim.get('reason','')}\"; classified "
        f"{claim.get('classification','COMPENSABLE')}.\n"
        f"Airline rejection said: \"{rejection_reason}\"."
    )
    reply = await llm.chat(
        [{"role": "system", "content": system},
         {"role": "user", "content": user_prompt}],
        max_tokens=400,
        temperature=0.4,
    )
    if not (reply or "").strip():
        reply = (
            f"Dear {claim.get('airline', 'Customer Relations')},\n\n"
            f"I dispute your rejection of my compensation claim for flight "
            f"{claim.get('flight_number','')} ({claim.get('date','')}). Under {j['citation']}, "
            f"the burden of proving extraordinary circumstances rests with the carrier. "
            f"Your cited ground (\"{rejection_reason}\") does not establish this. "
            f"I request payment within 14 days, failing which I will escalate to the "
            f"competent national enforcement body.\n\n"
            f"Yours faithfully,\n{claim.get('passenger_name','Passenger')}"
        )
    return {"appeal_letter": reply.strip(), "citation": j["citation"], "engine": "qwen"}
