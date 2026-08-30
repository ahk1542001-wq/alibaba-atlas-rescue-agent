"""Visa check tool for Qwen-Agent."""

import datetime
import json
from typing import Any, Dict, Optional

import json5
from qwen_agent.tools.base import BaseTool, register_tool

from services import visa_guard


@register_tool("visa_check")
class VisaCheckTool(BaseTool):
    description = (
        "Assess the visa/transit posture for a passport on a route and destination. "
        "Use when the user asks about visa requirements or passport transit rules."
    )
    parameters = [
        {
            "name": "passport",
            "type": "string",
            "description": "2-letter passport/nationality ISO code, e.g. MM for Myanmar",
            "required": True,
        },
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
    ]

    def call(self, params: str, **kwargs) -> str:
        try:
            args = json5.loads(params)
            if not isinstance(args, dict):
                return json.dumps({
                    "status": "failed",
                    "error": "Parameters must decode to a JSON object",
                    "tool": "visa_check",
                })
            passport = str(args.get("passport", "")).strip().upper()
            origin = str(args.get("origin", "")).strip().upper()
            destination = str(args.get("destination", "")).strip().upper()

            rule_entry = visa_guard.VISA_RULES.get(passport)
            destination_rule = (rule_entry or {}).get("hubs", {}).get(destination)
            offer = {
                "origin": origin,
                "destination": destination,
                "stops": 0,
                "via": [destination],
            }
            route_assessment = visa_guard.assess_offer(passport, offer)
            today = datetime.date.today().isoformat()
            
            return json.dumps({
                "status": "success",
                "passport": passport,
                "passport_name": (rule_entry or {}).get("name") or passport,
                "destination_rule": destination_rule or {
                    "status": "UNKNOWN",
                    "note": "No explicit rule for this destination; verify manually.",
                },
                "route_assessment": route_assessment,
                "as_of": today,
                "citations": [
                    {
                        "source_url": "baseline://visa_guard",
                        "retrieved_date": today,
                    }
                ],
            }, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({
                "status": "failed",
                "error": f"{type(exc).__name__}: {str(exc)}",
                "tool": "visa_check",
            }, ensure_ascii=False)
