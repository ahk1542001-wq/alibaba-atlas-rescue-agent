"""LocationResolveSkill — §4 S12 (G2 behavior).

Resolves free-text city names, venues, and ambiguous airport references into
candidate IATA codes. For multi-airport cities like Bangkok (BKK + DMK), it
returns all candidate airports and flags confirmation_required = True without
ever silently auto-selecting.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from services.skills.base import SkillBase, SkillError

KNOWN_CITY_AIRPORTS: Dict[str, List[Dict[str, str]]] = {
    "BANGKOK": [
        {"code": "BKK", "name": "Suvarnabhumi Airport"},
        {"code": "DMK", "name": "Don Mueang International Airport"},
    ],
    "SINGAPORE": [
        {"code": "SIN", "name": "Singapore Changi Airport"},
    ],
    "YANGON": [
        {"code": "RGN", "name": "Yangon International Airport"},
    ],
    "FRANKFURT": [
        {"code": "FRA", "name": "Frankfurt Airport"},
    ],
    "PARIS": [
        {"code": "CDG", "name": "Charles de Gaulle Airport"},
        {"code": "ORY", "name": "Orly Airport"},
    ],
    "LONDON": [
        {"code": "LHR", "name": "Heathrow Airport"},
        {"code": "LGW", "name": "Gatwick Airport"},
        {"code": "LCY", "name": "London City Airport"},
        {"code": "STN", "name": "Stansted Airport"},
    ],
    "TOKYO": [
        {"code": "HND", "name": "Haneda Airport"},
        {"code": "NRT", "name": "Narita International Airport"},
    ],
    "NEW YORK": [
        {"code": "JFK", "name": "John F. Kennedy International Airport"},
        {"code": "EWR", "name": "Newark Liberty International Airport"},
        {"code": "LGA", "name": "LaGuardia Airport"},
    ],
    "HONG KONG": [
        {"code": "HKG", "name": "Hong Kong International Airport"},
    ],
    "KUALA LUMPUR": [
        {"code": "KUL", "name": "Kuala Lumpur International Airport"},
    ],
    "MANILA": [
        {"code": "MNL", "name": "Ninoy Aquino International Airport"},
    ],
    "DUBAI": [
        {"code": "DXB", "name": "Dubai International Airport"},
    ],
    "SYDNEY": [
        {"code": "SYD", "name": "Sydney Kingsford Smith Airport"},
    ],
}

KNOWN_VENUES: Dict[str, Dict[str, Any]] = {
    "MARINA BAY SANDS": {
        "city": "Singapore",
        "airports": [{"code": "SIN", "name": "Singapore Changi Airport"}],
        "venue": "Marina Bay Sands",
    },
    "SANDS EXPO": {
        "city": "Singapore",
        "airports": [{"code": "SIN", "name": "Singapore Changi Airport"}],
        "venue": "Marina Bay Sands Expo and Convention Centre",
    },
}

KNOWN_SINGLE_AIRPORTS: Dict[str, Dict[str, str]] = {
    "SUVARNABHUMI": {"code": "BKK", "name": "Suvarnabhumi Airport"},
    "DON MUEANG": {"code": "DMK", "name": "Don Mueang International Airport"},
    "CHANGI": {"code": "SIN", "name": "Singapore Changi Airport"},
    "HEATHROW": {"code": "LHR", "name": "Heathrow Airport"},
    "GATWICK": {"code": "LGW", "name": "Gatwick Airport"},
    "NARITA": {"code": "NRT", "name": "Narita International Airport"},
    "HANEDA": {"code": "HND", "name": "Haneda Airport"},
    "CHARLES DE GAULLE": {"code": "CDG", "name": "Charles de Gaulle Airport"},
}


class LocationResolveInput(BaseModel):
    origin_text: Optional[str] = Field(default=None)
    destination_text: Optional[str] = Field(default=None)
    venue: Optional[str] = Field(default=None)


class LocationCandidate(BaseModel):
    code: str
    name: str


class LocationResolveResult(BaseModel):
    origin_candidates: List[LocationCandidate] = Field(default_factory=list)
    destination_candidates: List[LocationCandidate] = Field(default_factory=list)
    confirmed_origin: Optional[str] = None
    confirmed_destination: Optional[str] = None
    confirmation_required: bool = False
    ambiguity_reason: Optional[str] = None
    venue: Optional[str] = None


def resolve_location_phrase(text: Optional[str]) -> Tuple[List[Dict[str, str]], bool, Optional[str]]:
    """Resolves a free-text location phrase to (candidates, is_ambiguous, venue)."""
    if not text:
        return [], False, None
    clean = text.strip().upper()
    # 1. Exact 3-letter IATA code
    if re.fullmatch(r"[A-Z]{3}", clean):
        return [{"code": clean, "name": f"{clean} Airport"}], False, None

    # 2. Known venue check
    for vname, vdata in KNOWN_VENUES.items():
        if vname in clean:
            return vdata["airports"], len(vdata["airports"]) > 1, vdata.get("venue")

    # 3. Known specific airport check
    for ap_name, ap_data in KNOWN_SINGLE_AIRPORTS.items():
        if ap_name in clean:
            return [ap_data], False, None

    # 4. Known city check
    for city_name, ap_list in KNOWN_CITY_AIRPORTS.items():
        if city_name in clean or clean in city_name:
            is_ambig = len(ap_list) > 1
            return ap_list, is_ambig, None

    # 5. Default fallback: treat as unmapped single candidate if alphanumeric
    return [{"code": clean[:3], "name": f"{clean} Airport"}], False, None


class LocationResolveSkill(SkillBase):
    name = "location_resolve"
    when_to_use = (
        "when the goal contains a city, venue, or ambiguous airport; resolves "
        "to candidate IATA codes and requests confirmation for multi-airport cities"
    )
    capabilities = frozenset({"network_read", "llm_call"})
    input_model = LocationResolveInput
    output_model = LocationResolveResult

    async def run(self, payload: Dict[str, Any],
                  context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        origin_text = str(payload.get("origin_text") or payload.get("origin") or "").strip()
        dest_text = str(payload.get("destination_text") or payload.get("destination") or "").strip()
        venue_text = str(payload.get("venue") or "").strip() or None

        origin_cands, origin_ambig, _ = resolve_location_phrase(origin_text)
        dest_cands, dest_ambig, resolved_venue = resolve_location_phrase(dest_text)

        if not resolved_venue and venue_text:
            _, _, resolved_venue = resolve_location_phrase(venue_text)
            if not resolved_venue:
                resolved_venue = venue_text

        ambig_reasons = []
        if origin_ambig:
            ambig_reasons.append(f"Origin '{origin_text}' has multiple airports ({', '.join(c['code'] for c in origin_cands)})")
        if dest_ambig:
            ambig_reasons.append(f"Destination '{dest_text}' has multiple airports ({', '.join(c['code'] for c in dest_cands)})")

        conf_req = origin_ambig or dest_ambig
        res = LocationResolveResult(
            origin_candidates=[LocationCandidate(**c) for c in origin_cands],
            destination_candidates=[LocationCandidate(**c) for c in dest_cands],
            confirmed_origin=origin_cands[0]["code"] if (origin_cands and not origin_ambig) else None,
            confirmed_destination=dest_cands[0]["code"] if (dest_cands and not dest_ambig) else None,
            confirmation_required=conf_req,
            ambiguity_reason="; ".join(ambig_reasons) if ambig_reasons else None,
            venue=resolved_venue,
        )
        return res.model_dump(mode="json")
