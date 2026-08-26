"""rights_check skill — §4 S9 (G2 behavior).

Jurisdiction is resolved SERVER-SIDE from the airport pair via the frozen
rights_engine (haversine distance + country tables, import-only — never
modified). Regime, amount band and legal citation come exclusively from the
frozen regime tables; nothing is invented. No-applicable-regime returns an
honest NONE opinion instead of a guess (F6).
"""

from typing import Any, Dict, Optional

from services.rights_engine import (
    JURISDICTIONS,
    airports_to_countries,
    compute_entitlement,
    detect_jurisdictions,
    route_distance_km,
)
from services.skills.base import SkillBase


class RightsCheckSkill(SkillBase):
    name = "rights_check"
    when_to_use = (
        "when a disruption is confirmed or the user asks about entitlements; "
        "jurisdiction chosen server-side from the airport pair, regime cited"
    )
    capabilities = frozenset()  # local rights_engine tables only; no external caps

    async def run(self, payload: Dict[str, Any],
                  context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        origin = str(payload.get("origin_airport") or "").upper()
        destination = str(payload.get("destination_airport") or "").upper()

        distance = route_distance_km(origin, destination)
        o_country, d_country, _carrier = airports_to_countries(origin, destination)
        candidates = detect_jurisdictions(o_country, d_country)

        if not candidates:
            return {
                "regime": "NONE",
                "amount": None,
                "currency": None,
                "legal_citation": "",
                "distance_km": distance,
                "note": (f"No applicable regime for {origin}→{destination} "
                         "under the frozen rights_engine tables (no EU/UK/TR/US "
                         "jurisdiction trigger). Honesty over guessing."),
            }

        top = candidates[0]
        regime_id = top["id"]
        entitlement = compute_entitlement(regime_id, distance)
        cash = entitlement.get("fixed_cash_compensation")
        return {
            "regime": regime_id,
            "amount": cash["amount"] if cash else None,
            "currency": cash["currency"] if cash else None,
            "legal_citation": top.get("citation")
            or JURISDICTIONS.get(regime_id, {}).get("citation", ""),
            "distance_km": distance,
            "note": (entitlement.get("note")
                     or f"{top.get('name', regime_id)} applies; distance band "
                        f"resolved at {distance} km. Claim requires a confirmed "
                        "disruption; cause classification handled separately."),
            "candidates": [c["id"] for c in candidates],
        }
