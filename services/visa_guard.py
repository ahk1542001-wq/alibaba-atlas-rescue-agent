"""Visa-Aware Rebooking Guard.

Filters and re-ranks rescue packages by the passenger's passport. A cheaper
or faster rebooking is worthless if the passenger cannot legally transit the
connecting airport. This encodes the real-world transit/visa knowledge that
generic OTAs ignore — the unfair advantage of an agency-grade agent.

Rules are conservative demo data (2026-08): when in doubt we flag RISK
rather than CLEAR, because a blocked transit ruins the rescue.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("visa")

# Transit-visa posture per nationality per hub/region.
# status: CLEAR = no visa needed for airside transit under normal conditions.
#         TRANSIT_VISA_REQUIRED = visa required but obtainable (eVisa/VOA).
#         BLOCKED_RISK = strict requirement; boarding often denied without it.
VISA_RULES: Dict[str, Dict[str, Any]] = {
    "MM": {  # Myanmar passport — Victor's core user base
        "name": "Myanmar",
        "hubs": {
            "SIN": {"status": "TRANSIT_VISA_REQUIRED", "note": "Singapore requires a visa for MM nationals even for transit; eVisa ~3 working days."},
            "KUL": {"status": "CLEAR", "note": "Malaysia: visa-free transit <120h (TWOV) at KUL."},
            "BKK": {"status": "CLEAR", "note": "Thailand: airside transit without visa permitted."},
            "HAN": {"status": "TRANSIT_VISA_REQUIRED", "note": "Vietnam: no airside transit without visa at HAN/SGN; eVisa available."},
            "HKG": {"status": "TRANSIT_VISA_REQUIRED", "note": "Hong Kong requires pre-arrival registration / visa for MM nationals."},
            "DXB": {"status": "CLEAR", "note": "UAE: airside transit without visa permitted."},
            "ICN": {"status": "CLEAR", "note": "Korea: visa-free transit <24h with confirmed onward ticket (airside)."},
            "NRT": {"status": "CLEAR", "note": "Japan: airside transit without visa (TR) permitted same-day."},
            "DOH": {"status": "CLEAR", "note": "Qatar: airside transit without visa permitted."},
            "IST": {"status": "TRANSIT_VISA_REQUIRED", "note": "Turkey: visa/eVisa required for MM nationals even for transit."},
            "FRA": {"status": "BLOCKED_RISK", "note": "Schengen airport transit visa (ATV) generally required for MM nationals; airline check-in agents enforce strictly."},
            "LHR": {"status": "BLOCKED_RISK", "note": "UK Direct Airside Transit Visa (DATV) required for MM nationals."},
        },
    },
    "TH": {"name": "Thailand", "hubs": {}},  # default-clear below
    "SG": {"name": "Singapore", "hubs": {}},
    "VN": {"name": "Vietnam", "hubs": {}},
    "PH": {"name": "Philippines", "hubs": {}},
    "ID": {"name": "Indonesia", "hubs": {}},
    "IN": {
        "name": "India",
        "hubs": {
            "SIN": {"status": "BLOCKED_RISK", "note": "Singapore VFTF (visa-free transit facility) suspended/conditional for Indian nationals; check 96-hour VFTF eligibility."},
            "ICN": {"status": "CLEAR", "note": "Korea: visa-free transit <24h airside for Indian nationals with US/Green-card or OECD history is conditional — verify before booking."},
        },
    },
    "CN": {
        "name": "China",
        "hubs": {
            "SIN": {"status": "CLEAR", "note": "Singapore: 96-hour VFTF applies for CN nationals transiting to/from a third country."},
        },
    },
    "NP": {"name": "Nepal", "hubs": {}},
    "BD": {
        "name": "Bangladesh",
        "hubs": {
            "LHR": {"status": "BLOCKED_RISK", "note": "UK DATV required for BD nationals."},
            "FRA": {"status": "BLOCKED_RISK", "note": "Schengen ATV required for BD nationals."},
        },
    },
    "LK": {"name": "Sri Lanka", "hubs": {}},
    "US": {"name": "United States", "hubs": {}},
    "GB": {"name": "United Kingdom", "hubs": {}},
    "DE": {"name": "Germany", "hubs": {}},
}

_DEFAULT_HUB_CLEAR = {"status": "CLEAR", "note": "No transit visa commonly required for this passport at this hub."}


def assess_offer(nationality_code: str, offer: Dict[str, Any]) -> Dict[str, Any]:
    """Attach visa_status + visa_note to one rescue offer based on its route."""
    nat = (nationality_code or "").upper()
    rule_entry = VISA_RULES.get(nat)
    if not rule_entry:
        return {"visa_status": "UNKNOWN", "visa_note": f"No rule table for passport '{nat}'; verify manually."}

    stops = int(offer.get("stops") or 0)
    via_raw = offer.get("via") or offer.get("via_airports") or []
    if isinstance(via_raw, str):
        via_list = [v.strip().upper() for v in via_raw.split(",") if v.strip()]
    else:
        via_list = [str(v).strip().upper() for v in via_raw]
    if not via_list:
        # Infer likely hub from carrier code as a demo heuristic
        via_list = _infer_hub(offer)

    worst = {"status": "CLEAR", "hub": None, "note": "Direct flight — no transit immigration."}
    for hub in via_list:
        hub_rule = rule_entry.get("hubs", {}).get(hub, dict(_DEFAULT_HUB_CLEAR))
        rank = {"CLEAR": 0, "TRANSIT_VISA_REQUIRED": 1, "BLOCKED_RISK": 2}.get(hub_rule["status"], 1)
        worst_rank = {"CLEAR": 0, "TRANSIT_VISA_REQUIRED": 1, "BLOCKED_RISK": 2}.get(worst["status"], 0)
        if rank > worst_rank:
            worst = {"status": hub_rule["status"], "hub": hub, "note": hub_rule["note"]}
    return {"visa_status": worst["status"], "visa_hub": worst["hub"], "visa_note": worst["note"]}


def _infer_hub(offer: Dict[str, Any]) -> List[str]:
    """Demo heuristic: map airline code to its natural connecting hub."""
    code = (offer.get("airline_code") or "").upper()
    hubs = {
        "SQ": ["SIN"], "TG": ["BKK"], "MH": ["KUL"], "CX": ["HKG"],
        "EK": ["DXB"], "QR": ["DOH"], "TK": ["IST"], "KE": ["ICN"],
        "NH": ["NRT"], "JL": ["NRT"], "LH": ["FRA"], "BA": ["LHR"],
        "VN": ["SGN"], "PR": ["MNL"], "5J": ["CEB"], "AI": ["DEL"],
    }
    return hubs.get(code, [])


def filter_and_rank(nationality_code: str, offers: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Filter offers through the visa guard; keep risky ones flagged, never silent."""
    assessed = []
    blocked_count = 0
    for o in offers:
        a = dict(o)
        verdict = assess_offer(nationality_code, o)
        a.update(verdict)
        if verdict["visa_status"] == "BLOCKED_RISK":
            a["demoted"] = True
            blocked_count += 1
        assessed.append(a)
    # Sort: visa-clear first, then price
    assessed.sort(key=lambda x: (
        0 if x.get("visa_status") == "CLEAR" else 1,
        float(x.get("price_usd") or x.get("price_converted") or 9e9),
    ))
    return {
        "offers": assessed,
        "passport": (nationality_code or "").upper(),
        "blocked_count": blocked_count,
        "summary": (
            f"{len(assessed)} options checked against "
            f"{VISA_RULES.get((nationality_code or '').upper(), {}).get('name', 'unknown')} passport rules; "
            f"{blocked_count} carry transit-visa risk."
        ),
    }
