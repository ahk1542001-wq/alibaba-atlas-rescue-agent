"""Flight search tool for Qwen-Agent."""

import json
from typing import Any, Dict, Optional

import json5
from qwen_agent.tools.base import BaseTool, register_tool

from services.atlas_client import AtlasClient
from services.qwen_brain.tools.conversation import _run_coro_sync

_OFFER_FIELDS = (
    "offer_id", "flight_number", "airline", "airline_code", "origin",
    "destination", "departure_time", "arrival_time", "duration_minutes",
    "stops", "via", "cabin_class", "price_usd", "seats_available",
)


@register_tool("flight_search")
class FlightSearchTool(BaseTool):
    description = (
        "Search real flight inventory on the Atlas Sandbox (official "
        "atlas-flight CLI, authenticated) for a route and date. Use this "
        "whenever the user asks for available flights."
    )
    parameters = [
        {
            "name": "origin",
            "type": "string",
            "description": "Origin IATA airport code, e.g. BKK",
            "required": True,
        },
        {
            "name": "destination",
            "type": "string",
            "description": "Destination IATA airport code, e.g. SIN",
            "required": True,
        },
        {
            "name": "date",
            "type": "string",
            "description": "Travel date, ISO format YYYY-MM-DD (a future date)",
            "required": True,
        },
    ]

    def __init__(self, cfg: Optional[Dict[str, Any]] = None, client: Optional[AtlasClient] = None):
        super().__init__(cfg)
        self._client = client or AtlasClient()

    def call(self, params: str, **kwargs) -> str:
        try:
            args = json5.loads(params)
            if not isinstance(args, dict):
                return json.dumps({
                    "status": "failed",
                    "error": "Parameters must decode to a JSON object",
                    "tool": "flight_search",
                })
            origin = str(args.get("origin", "")).strip().upper()
            destination = str(args.get("destination", "")).strip().upper()
            date_str = str(args.get("date", "")).strip()

            offers = _run_coro_sync(self._client.search_flights(origin, destination, date_str))
            trimmed = [
                {k: o.get(k) for k in _OFFER_FIELDS if k in o}
                for o in offers[:10]
            ]
            return json.dumps({
                "source": "atlas_sandbox",
                "provenance": "atlas_sandbox",
                "note": "Live Atlas Sandbox inventory via authenticated atlas-flight CLI (sandbox, not bookable).",
                "query": {"origin": origin, "destination": destination, "date": date_str},
                "offer_count": len(offers),
                "offers_returned": len(trimmed),
                "offers": trimmed,
            }, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({
                "status": "failed",
                "error": f"{type(exc).__name__}: {str(exc)}",
                "tool": "flight_search",
                "source": "atlas_sandbox",
            }, ensure_ascii=False)
