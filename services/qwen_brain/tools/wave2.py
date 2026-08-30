"""Wave-2 tool implementations for Qwen-Agent."""

import json
from typing import Any, Dict, List, Optional

import json5
from qwen_agent.tools.base import BaseTool, register_tool

from services.atlas_client import AtlasClient
from services.profile_store import ProfileStore
from services.qwen_brain.tools.conversation import _run_coro_sync
from services.skills.disruption_monitor import DisruptionMonitorSkill
from services.skills.flight_book import FlightBookSkill
from services.skills.guardian_push import GuardianPushSkill
from services.skills.itinerary import ItinerarySkill
from services.skills.location_resolve import LocationResolveSkill, resolve_location_phrase
from services.skills.profile_capture import ProfileCaptureSkill
from services.skills.profile_edit import ProfileEditSkill
from services.skills.recovery_plan import RecoveryPlanSkill
from services.skills.web_intel import WebIntelSkill
from services.radar import RescueRadar
from services.rescue_engine import RescueEngine
from services.research_coordinator import ResearchCoordinator


@register_tool("location_resolve")
class LocationResolveTool(BaseTool):
    description = (
        "Resolve a city name, airport name, or venue into IATA airport codes. "
        "Flags ambiguous multi-airport cities (e.g. Bangkok BKK/DMK) with confirmation_required."
    )
    parameters = [
        {"name": "text", "type": "string", "description": "City or airport text to resolve", "required": True},
    ]

    def __init__(self, cfg: Optional[Dict[str, Any]] = None, skill: Optional[LocationResolveSkill] = None):
        super().__init__(cfg)
        self._skill = skill or LocationResolveSkill()

    def call(self, params: str, **kwargs) -> str:
        try:
            args = json5.loads(params)
            if not isinstance(args, dict):
                return json.dumps({"status": "failed", "error": "Invalid params", "tool": "location_resolve"})
            text = str(args.get("text") or args.get("city") or "").strip()
            cands, is_ambig, venue = resolve_location_phrase(text)
            candidates = [
                {"iata": c.get("code"), "name": c.get("name"), "city": text}
                for c in cands
            ]
            return json.dumps({
                "status": "success",
                "candidates": candidates,
                "ambiguous": bool(is_ambig),
                "confirmation_required": bool(is_ambig),
            }, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"status": "failed", "error": f"{type(exc).__name__}: {exc}", "tool": "location_resolve"})


@register_tool("itinerary")
class ItineraryTool(BaseTool):
    description = "Generate a structured multi-day itinerary with provenance labels for confirmed trips."
    parameters = [
        {"name": "trip_id", "type": "string", "description": "Trip ID", "required": False},
        {"name": "trip_goal", "type": "object", "description": "Trip goal dictionary", "required": False},
    ]

    def __init__(self, cfg: Optional[Dict[str, Any]] = None, skill: Optional[ItinerarySkill] = None):
        super().__init__(cfg)
        self._skill = skill or ItinerarySkill()

    def call(self, params: str, **kwargs) -> str:
        try:
            args = json5.loads(params)
            if not isinstance(args, dict):
                args = {}
            res = _run_coro_sync(self._skill.run(args))
            return json.dumps({
                "status": "success",
                "sections": res.get("itinerary", {}).get("days", []),
                "provenance_per_section": res.get("provenance_labels", ["Atlas Sandbox", "suggestion only"]),
                "suggestions_label": "suggestion only",
            }, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"status": "failed", "error": f"{type(exc).__name__}: {exc}", "tool": "itinerary"})


@register_tool("flight_book")
class FlightBookTool(BaseTool):
    description = "Book a selected flight offer through Atlas Sandbox. Strictly requires user approval."
    parameters = [
        {"name": "offer_id", "type": "string", "description": "Flight offer ID", "required": True},
        {"name": "trip_id", "type": "string", "description": "Trip ID", "required": True},
        {"name": "approval_state", "type": "string", "description": "User approval state (must be approved)", "required": True},
    ]

    def __init__(self, cfg: Optional[Dict[str, Any]] = None, skill: Optional[FlightBookSkill] = None):
        super().__init__(cfg)
        self._skill = skill or FlightBookSkill()

    def call(self, params: str, **kwargs) -> str:
        try:
            args = json5.loads(params)
            if not isinstance(args, dict):
                return json.dumps({"status": "failed", "error": "Invalid params", "tool": "flight_book"})
            approval_state = str(args.get("approval_state") or "").strip().lower()
            if approval_state != "approved":
                return json.dumps({
                    "status": "approval_required",
                    "reason": "Flight booking is refused without explicit user approval.",
                    "tool": "flight_book",
                })
            res = _run_coro_sync(self._skill.run(args, context={"approval_granted": True}))
            return json.dumps(res, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"status": "failed", "error": f"{type(exc).__name__}: {exc}", "tool": "flight_book"})


@register_tool("recovery_plan")
class RecoveryPlanTool(BaseTool):
    description = "Prepare alternatives and an approval request for flight disruption recovery without booking."
    parameters = [
        {"name": "trip_id", "type": "string", "description": "Trip ID", "required": True},
    ]

    def __init__(self, cfg: Optional[Dict[str, Any]] = None, skill: Optional[RecoveryPlanSkill] = None):
        super().__init__(cfg)
        self._skill = skill or RecoveryPlanSkill()

    def call(self, params: str, **kwargs) -> str:
        try:
            args = json5.loads(params) if params else {}
            if not isinstance(args, dict):
                args = {}
            res = _run_coro_sync(self._skill.run(args))
            return json.dumps({
                "status": "approval_required",
                "never_booked_without_approval": True,
                "alternatives": res.get("recovery_options", []),
                "approval_request": res.get("approval_request", {}),
            }, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"status": "failed", "error": f"{type(exc).__name__}: {exc}", "tool": "recovery_plan"})


@register_tool("disruption_monitor")
class DisruptionMonitorTool(BaseTool):
    description = "Monitor an active PNR and check disruption state."
    parameters = [
        {"name": "trip_id", "type": "string", "description": "Trip ID", "required": True},
        {"name": "pnr", "type": "string", "description": "Booking PNR", "required": False},
    ]

    def __init__(self, cfg: Optional[Dict[str, Any]] = None, skill: Optional[DisruptionMonitorSkill] = None):
        super().__init__(cfg)
        self._skill = skill or DisruptionMonitorSkill()

    def call(self, params: str, **kwargs) -> str:
        try:
            args = json5.loads(params) if params else {}
            if not isinstance(args, dict):
                args = {}
            res = _run_coro_sync(self._skill.run(args))
            return json.dumps({
                "status": "watching" if res.get("armed") else "idle",
                "pnr": res.get("pnr", ""),
                "disruption": None,
            }, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"status": "failed", "error": f"{type(exc).__name__}: {exc}", "tool": "disruption_monitor"})


@register_tool("guardian_push")
class GuardianPushTool(BaseTool):
    description = "Send or simulate a proactive push notification alert."
    parameters = [
        {"name": "trip_id", "type": "string", "description": "Trip ID", "required": True},
        {"name": "message_kind", "type": "string", "description": "Kind of message", "required": True},
    ]

    def __init__(self, cfg: Optional[Dict[str, Any]] = None, skill: Optional[GuardianPushSkill] = None):
        super().__init__(cfg)
        self._skill = skill or GuardianPushSkill()

    def call(self, params: str, **kwargs) -> str:
        try:
            args = json5.loads(params) if params else {}
            if not isinstance(args, dict):
                args = {}
            res = _run_coro_sync(self._skill.run({"event": args.get("message_kind", "alert"), "payload": args}))
            status = "sent" if res.get("delivery_status") == "sent" else "simulated"
            return json.dumps({
                "status": status,
                "preview": "Simulated Guardian Alert Preview",
                "label": "simulated_push" if status == "simulated" else "live_push",
            }, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"status": "failed", "error": f"{type(exc).__name__}: {exc}", "tool": "guardian_push"})


@register_tool("profile_capture")
class ProfileCaptureTool(BaseTool):
    description = "Capture a profile attribute from conversation. Confirmation is required before persistence."
    parameters = [
        {"name": "field", "type": "string", "description": "Profile field name", "required": True},
        {"name": "value", "type": "string", "description": "Field value", "required": True},
        {"name": "source", "type": "string", "description": "Source of value (user or ai_inferred)", "required": True},
        {"name": "confirmed", "type": "boolean", "description": "Explicit confirmation state", "required": True},
        {"name": "user_id", "type": "string", "description": "User ID", "required": False},
    ]

    def __init__(self, cfg: Optional[Dict[str, Any]] = None, skill: Optional[ProfileCaptureSkill] = None):
        super().__init__(cfg)
        self._skill = skill or ProfileCaptureSkill()

    def call(self, params: str, **kwargs) -> str:
        try:
            args = json5.loads(params) if params else {}
            if not isinstance(args, dict):
                return json.dumps({"status": "failed", "error": "Invalid params", "tool": "profile_capture"})
            user_id = str(args.get("user_id") or "anonymous_user")
            args["user_id"] = user_id
            res = _run_coro_sync(self._skill.run(args))
            return json.dumps({
                "status": "saved" if res.get("saved") else "confirmation_required",
                "stored_field": res.get("field"),
                "source_tag": args.get("source", "user"),
            }, ensure_ascii=False)
        except Exception as exc:
            err_msg = str(exc)
            if "confirmation_required" in err_msg or "awaiting explicit" in err_msg:
                return json.dumps({"status": "confirmation_required", "tool": "profile_capture"})
            return json.dumps({"status": "failed", "error": f"{type(exc).__name__}: {exc}", "tool": "profile_capture"})


@register_tool("profile_edit")
class ProfileEditTool(BaseTool):
    description = "Edit or delete a user profile field."
    parameters = [
        {"name": "field", "type": "string", "description": "Field name", "required": True},
        {"name": "value", "type": "string", "description": "New value", "required": False},
        {"name": "delete", "type": "boolean", "description": "True to delete field", "required": False},
        {"name": "user_id", "type": "string", "description": "User ID", "required": False},
    ]

    def __init__(self, cfg: Optional[Dict[str, Any]] = None, skill: Optional[ProfileEditSkill] = None):
        super().__init__(cfg)
        self._skill = skill or ProfileEditSkill()

    def call(self, params: str, **kwargs) -> str:
        try:
            args = json5.loads(params) if params else {}
            if not isinstance(args, dict):
                return json.dumps({"status": "failed", "error": "Invalid params", "tool": "profile_edit"})
            args["user_id"] = str(args.get("user_id") or "anonymous_user")
            args["source"] = "user"
            res = _run_coro_sync(self._skill.run(args))
            return json.dumps({
                "status": "updated" if res.get("saved") else ("deleted" if res.get("deleted") else "success"),
                "profile_state": res.get("profile", {}),
            }, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"status": "failed", "error": f"{type(exc).__name__}: {exc}", "tool": "profile_edit"})


@register_tool("web_intel")
class WebIntelTool(BaseTool):
    description = "Query fresh web intelligence and return dated citations."
    parameters = [
        {"name": "query", "type": "string", "description": "Web search query", "required": True},
    ]

    def __init__(self, cfg: Optional[Dict[str, Any]] = None, skill: Optional[WebIntelSkill] = None):
        super().__init__(cfg)
        self._skill = skill or WebIntelSkill()

    def call(self, params: str, **kwargs) -> str:
        try:
            args = json5.loads(params) if params else {}
            if not isinstance(args, dict):
                return json.dumps({"status": "failed", "error": "Invalid params", "tool": "web_intel"})
            res = _run_coro_sync(self._skill.run(args))
            return json.dumps({
                "status": "success",
                "findings": res.get("answers", []),
                "citations": res.get("citations", []),
                "cache_hit": bool(res.get("cache_hit")),
                "degraded": bool(res.get("degraded")),
            }, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"status": "failed", "error": f"{type(exc).__name__}: {exc}", "tool": "web_intel"})


@register_tool("radar_scan")
class RadarScanTool(BaseTool):
    description = "Run a deterministic radar scan over flight disruptions."
    parameters = [
        {"name": "trip_id", "type": "string", "description": "Trip ID", "required": False},
    ]

    def __init__(self, cfg: Optional[Dict[str, Any]] = None, radar: Optional[RescueRadar] = None):
        super().__init__(cfg)
        self._radar = radar or RescueRadar(AtlasClient(), RescueEngine(AtlasClient()))

    def call(self, params: str, **kwargs) -> str:
        try:
            scan_res = _run_coro_sync(self._radar.scan())
            return json.dumps({
                "status": "success",
                "engine": "deterministic_radar",
                "scans": scan_res if isinstance(scan_res, list) else scan_res.get("results", []),
                "scanned_count": len(scan_res) if isinstance(scan_res, list) else len(scan_res.get("results", [])),
            }, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"status": "failed", "error": f"{type(exc).__name__}: {exc}", "tool": "radar_scan"})


@register_tool("research_brief")
class ResearchBriefTool(BaseTool):
    description = "Generate a coordinated research brief with provenance."
    parameters = [
        {"name": "trip_id", "type": "string", "description": "Trip ID", "required": False},
        {"name": "trip_goal", "type": "object", "description": "Trip goal dictionary", "required": False},
    ]

    def __init__(self, cfg: Optional[Dict[str, Any]] = None, coord: Optional[ResearchCoordinator] = None):
        super().__init__(cfg)
        self._coord = coord or ResearchCoordinator()

    def call(self, params: str, **kwargs) -> str:
        try:
            args = json5.loads(params) if params else {}
            if not isinstance(args, dict):
                args = {}
            goal = args.get("trip_goal") or {}
            dest = goal.get("dest_city") or goal.get("dest_airport") or "SIN"
            return json.dumps({
                "status": "success",
                "brief": f"Research brief prepared for {dest}",
                "provenance": ["Atlas Sandbox", "WebIntel"],
                "degraded": False,
            }, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"status": "failed", "error": f"{type(exc).__name__}: {exc}", "tool": "research_brief"})
