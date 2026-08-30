"""Safety check tool for Qwen-Agent."""

import json
from typing import Any, Dict, Optional

import json5
from qwen_agent.tools.base import BaseTool, register_tool

from services.safety.policy import normalize_country
from services.skills.safety_research import SafetyResearchSkill
from services.qwen_brain.tools.conversation import _run_coro_sync


@register_tool("safety_check")
class SafetyCheckTool(BaseTool):
    description = (
        "Collect official travel advisories, health events, disaster/weather alerts "
        "and transport warnings for a destination country. Use when user asks about safety."
    )
    parameters = [
        {
            "name": "destination",
            "type": "string",
            "description": "Destination country name or ISO-2 code (e.g. SG, TH, Singapore)",
            "required": True,
        },
        {
            "name": "origin",
            "type": "string",
            "description": "Origin country or ISO-2 code (optional)",
            "required": False,
        },
    ]

    def __init__(self, cfg: Optional[Dict[str, Any]] = None, skill: Optional[SafetyResearchSkill] = None):
        super().__init__(cfg)
        self._skill = skill or SafetyResearchSkill()

    def call(self, params: str, **kwargs) -> str:
        try:
            args = json5.loads(params)
            if not isinstance(args, dict):
                return json.dumps({
                    "status": "failed",
                    "error": "Parameters must decode to a JSON object",
                    "tool": "safety_check",
                })
            dest_raw = str(args.get("destination", "")).strip()
            norm_dest = normalize_country(dest_raw) or dest_raw.upper()
            origin_raw = str(args.get("origin", "")).strip()
            norm_origin = normalize_country(origin_raw) if origin_raw else None

            payload = {
                "destination_country": norm_dest,
                "residence_country": norm_origin,
            }
            res = _run_coro_sync(self._skill.run(payload))
            assessment = res.get("assessment", {})
            evidence = res.get("evidence", [])
            return json.dumps({
                "status": "success",
                "assessment": assessment,
                "provenance_label": "official_government_advisories",
                "advisories": [
                    {
                        "source": e.get("source_id"),
                        "level": e.get("normalized_level"),
                        "summary": e.get("summary"),
                        "url": e.get("source_url"),
                    }
                    for e in evidence[:5]
                ],
            }, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({
                "status": "failed",
                "error": f"{type(exc).__name__}: {str(exc)}",
                "tool": "safety_check",
            }, ensure_ascii=False)
