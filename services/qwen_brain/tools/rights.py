"""Air passenger rights check tool for Qwen-Agent."""

import json
from typing import Any, Dict, Optional

import json5
from qwen_agent.tools.base import BaseTool, register_tool

from services import rights_engine


@register_tool("rights_check")
class RightsCheckTool(BaseTool):
    description = (
        "Compute applicable air-passenger-rights jurisdictions (EU261, UK261, "
        "US DOT, Turkey SHY) and entitlement amounts for a flight route. "
        "Use when user asks about disruption compensation or passenger rights."
    )
    parameters = [
        {
            "name": "origin",
            "type": "string",
            "description": "Origin IATA airport code, e.g. FRA",
            "required": True,
        },
        {
            "name": "destination",
            "type": "string",
            "description": "Destination IATA airport code, e.g. JFK",
            "required": True,
        },
    ]

    def call(self, params: str, **kwargs) -> str:
        try:
            args = json5.loads(params)
            if not isinstance(args, dict):
                return json.dumps({
                    "status": "failed",
                    "error": "Parameters must decode to a JSON object",
                    "tool": "rights_check",
                })
            origin = str(args.get("origin", "")).strip().upper()
            destination = str(args.get("destination", "")).strip().upper()

            o_country, d_country, _ = rights_engine.airports_to_countries(origin, destination)
            jurisdictions = rights_engine.detect_jurisdictions(o_country, d_country)
            distance_km = rights_engine.route_distance_km(origin, destination)
            entitlements = [
                rights_engine.compute_entitlement(j["id"], distance_km)
                for j in jurisdictions
            ]
            note = (
                "No fixed-cash-compensation regime (EU261/UK261/US DOT/Turkey SHY) "
                "covers this route; airline duty-of-care and contract terms still apply."
                if not jurisdictions else
                "Fixed compensation applies only if the disruption cause is compensable."
            )
            return json.dumps({
                "status": "success",
                "origin_country": o_country,
                "destination_country": d_country,
                "route_distance_km": distance_km,
                "applicable_jurisdictions": [j["id"] for j in jurisdictions],
                "entitlements": entitlements,
                "note": note,
            }, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({
                "status": "failed",
                "error": f"{type(exc).__name__}: {str(exc)}",
                "tool": "rights_check",
            }, ensure_ascii=False)
