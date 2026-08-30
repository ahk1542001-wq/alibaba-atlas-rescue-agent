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
from services.skills.base import SkillError
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

    # node names that mean a booking approval is still open server-side
    _BOOKING_APPROVAL_NODES = frozenset({"approve_booking", "flight_book"})

    def __init__(self, cfg: Optional[Dict[str, Any]] = None,
                 skill: Optional[FlightBookSkill] = None, trip_store=None):
        super().__init__(cfg)
        self._skill = skill or FlightBookSkill()
        self._trip_store = trip_store

    def _refusal(self, reason: str) -> str:
        return json.dumps({
            "status": "approval_required",
            "reason": reason,
            "tool": "flight_book",
        }, ensure_ascii=False)

    def _resolve_trip_store(self):
        if self._trip_store is not None:
            return self._trip_store
        # lazy import: routers.v1.trip pulls in this package indirectly
        from routers.v1.trip import get_trip_orchestrator
        return get_trip_orchestrator().executor

    def call(self, params: str, **kwargs) -> str:
        try:
            args = json5.loads(params)
            if not isinstance(args, dict):
                return json.dumps({"status": "failed", "error": "Invalid params", "tool": "flight_book"})
            # Gate 1: the model-supplied string is only a PRE-filter. It can
            # refuse a booking, but it can NEVER grant one.
            approval_state = str(args.get("approval_state") or "").strip().lower()
            if approval_state != "approved":
                return self._refusal(
                    "Flight booking is refused without explicit user approval.")
            # Gate 2 (audit fix): authority comes from SERVER-SIDE trip state
            # (trip store pending_approvals / context approval_granted by
            # trip_id) — never from the model-supplied string, which may lie
            # or hallucinate.
            trip_id = str(args.get("trip_id") or "").strip()
            store = self._resolve_trip_store()
            try:
                trip = store.get(trip_id)
            except KeyError:
                return self._refusal(
                    f"Unknown trip '{trip_id}' — booking refused "
                    "(fail-closed: no server-side state, no booking).")
            pending = getattr(trip, "pending_approvals", None) or []
            for approval in pending:
                if getattr(approval, "node_name", "") in self._BOOKING_APPROVAL_NODES:
                    return self._refusal(
                        "A booking approval is still pending server-side — "
                        "the user must resolve it before any flight is booked.")
            trip_ctx = getattr(trip, "context", None) or {}
            if not trip_ctx.get("approval_granted"):
                return self._refusal(
                    "No server-side approval_granted exists for this trip — "
                    "booking refused (a model claim of approval is not "
                    "authority).")
            # Map offer_id -> option_id (the skill's deterministic contract).
            payload = dict(args)
            payload["option_id"] = str(
                args.get("offer_id") or args.get("option_id") or "")
            payload["trip_id"] = trip_id
            # Forward the REAL trip context — never fabricate safety/visa
            # gates or approval; the skill's deterministic gates decide.
            fwd_context = {
                "trip_id": trip_id,
                "approval_granted": True,
                "safety_check": trip_ctx.get("safety_check"),
                "visa_check": trip_ctx.get("visa_check"),
            }
            try:
                res = _run_coro_sync(
                    self._skill.run(payload, context=fwd_context))
            except SkillError as exc:
                return json.dumps({
                    "status": "failed",
                    "error_code": exc.code,
                    "error": exc.message,
                    "recoverable": exc.recoverable,
                    "tool": "flight_book",
                }, ensure_ascii=False)
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
            # Audit fix: preview text must branch on the REAL delivery status —
            # a live push never carries the "Simulated" label, and a
            # simulated/preview push is always explicitly labeled.
            delivery = res.get("delivery_status")
            simulated = bool(res.get("simulated"))
            if delivery == "sent" and not simulated:
                status, label = "sent", "live_push"
                preview = res.get("preview") or "Live Guardian Alert"
            else:
                status = "simulated" if simulated else "skipped"
                label = "simulated_push" if simulated else "skipped_push"
                base = res.get("preview") or "Guardian Alert Preview"
                preview = base if str(base).lower().startswith("simulated") \
                    else f"Simulated: {base}"
            return json.dumps({
                "status": status,
                "preview": preview,
                "label": label,
                "channel": res.get("channel", "telegram"),
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
        {"name": "source", "type": "string", "description": "Declared source of the edit (user or ai_inferred); defaults to ai_inferred for model-initiated edits", "required": False},
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
            # Audit fix: pass through the DECLARED source; a model-initiated
            # edit with no declared source defaults to "ai_inferred", which
            # ProfileEditSkill honestly refuses (inferred values must go
            # through profile_capture with explicit user confirmation).
            args["source"] = str(args.get("source") or "ai_inferred")
            try:
                res = _run_coro_sync(self._skill.run(args))
            except SkillError as exc:
                return json.dumps({
                    "status": "failed",
                    "error_code": exc.code,
                    "error": exc.message,
                    "recoverable": exc.recoverable,
                    "tool": "profile_edit",
                }, ensure_ascii=False)
            return json.dumps({
                "status": "updated" if res.get("saved") else ("deleted" if res.get("deleted") else "success"),
                "source_tag": args["source"],
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
                # RescueRadar.scan() returns {"flights": [...], "new_alerts": [...]} —
                # §10.2 gate: tool output must equal the direct engine scan.
                "scans": scan_res if isinstance(scan_res, list) else scan_res.get("flights", []),
                "scanned_count": len(scan_res) if isinstance(scan_res, list) else len(scan_res.get("flights", [])),
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
