"""Trip API router (§6 contracts) + trip orchestration glue.

Endpoints:
- POST /api/trip/start                    {goal_text,user_id} -> {trip_id,graph_state_url}
- GET  /api/trip/{id}/state               telemetry snapshot (nodes[], current_state, total_latency_ms)
- GET  /api/trip/{id}/stream              SSE step events (StreamingResponse, radar.py pattern)
- GET  /api/trip/{id}/approvals           list pending approvals
- POST /api/trip/{id}/approvals/{aid}     {decision,value?} -> resume result
- GET  /api/trip/{id}/simulate-disruption demo hook; 403 unless ?allow_sim=1

Architecture corrections enforced end-to-end from this layer:
(a) new/generic users start with an EMPTY profile — nothing auto-loads the
    opt-in demo fixture; (b) intent-first routing — ambiguous scope pauses
    with the exactly-three-choice scope clarification exposed via
    state/approvals; (c)+(d)+(e) delegate to the frozen/G2 services and are
    surfaced through the §6 error contract {error:{code,message,recoverable}}
    with actionable hints on recoverable failures.

Error mapping is defensive against the executor contract: GraphError /
GraphApprovalError instances are translated by their `code` (including the
optional approval-expiry code) instead of by exception type only.
"""

import asyncio
import json
import logging
import re
import time
import uuid
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, ValidationError

from models.schemas import (
    ApprovalRequest,
    BookingRecord,
    ConfirmationChip,
    DateWindow,
    GraphNodeStateV2,
    ItineraryReplacementRequest,
    RequestedServices,
    SafetyQuery,
    TripGoal,
    TripIntent,
)
from routers.v1.profile import TripApiError, get_profile_store
from services.atlas_client import AtlasClient
from services.research_coordinator import ResearchCoordinator
from services.rights_engine import airports_to_countries
from services.safety.policy import normalize_country
from services.skills import load_skill_registry
from services.skills.base import SkillBase, SkillError
from services.skills.clarify_loop import ClarifyLoopSkill
from services.skills.disruption_monitor import DisruptionMonitorSkill
from services.skills.flight_book import FlightBookSkill
from services.skills.flight_search import FlightSearchSkill
from services.skills.goal_intake import GoalIntakeSkill, _extract_dates, \
    _find_city
from services.skills.guardian_push import GuardianPushSkill
from services.skills.itinerary import ItinerarySkill
from services.skills.location_resolve import LocationResolveSkill
from services.skills.profile_edit import ProfileEditSkill
from services.skills.recovery_plan import RecoveryPlanSkill
from services.skills.rights_check import RightsCheckSkill
from services.skills.safety_monitor import SafetyMonitorSkill
from services.skills.safety_research import SafetyResearchSkill
from services.conversation_controller import project_conversation_turn
from services.brain import is_qwen_brain
from services.readiness import assess_readiness
from services.skills.visa_check import VisaCheckSkill
from services.trip_graph import (
    SCOPE_CHOICES,
    GraphCapabilityViolation,
    GraphError,
    TripGraphExecutor,
    plan_trip,
    resolve_scope_choice,
)
from services.web_intel_client import WebIntelClient
from services import llm as llm_service

logger = logging.getLogger("trip")

router = APIRouter(prefix="/api/trip", tags=["Trip"])
trips_router = APIRouter(prefix="/api/trips", tags=["Trips"])

# SSE stream bounds (G3-DA fix F7): a never-resolved approval must not keep
# the stream open forever — idle (no new events) and absolute lifetime caps
# emit a final status event and terminate; the trip itself stays paused.
STREAM_IDLE_TIMEOUT_SECONDS = 90.0
STREAM_MAX_LIFETIME_SECONDS = 600.0

# user_id boundary check (§9.3): identical charset to ProfileStore._path so
# invalid ids are refused BEFORE any goal parsing touches them (G3-DA fix F3)
_USER_ID_RE = re.compile(r"[A-Za-z0-9_-]+")

# research adapter domains + the write-capability vocabulary that boot-time
# manifest governance refuses to run unmanifested (G3-DA fix F5, §14.4)
_RESEARCH_DOMAINS = ("hotel", "activities", "local_transport")
_WRITE_CAPABILITIES = frozenset(
    {"profile_write", "telegram_send", "atlas_call", "network_read"})

_SCOPE_LABELS = {
    "flight_only": "Search flights only (no booking, no hotels/activities)",
    "flight_plus_booking": "Search flights and book through the Atlas Sandbox",
    "complete_trip": "Complete trip: flights, booking, hotels, activities, "
                     "local transport",
}

# clarify fields that belong to the TRIP GOAL (not the profile). Confirming
# them persists into the paused/failed trip's goal and resumes it
# (G4-DA-fix F4 — previously the chip confirm was a silent no-op).
_TRIP_GOAL_FIELDS = ("origin_city", "dest_city", "date_window", "passengers", "search_now")
_PROFILE_CLARIFY_FIELDS = ("passport_country", "home_city")
_AIRPORT_CONFIRM_FIELDS = (
    "confirmed_origin_airport", "confirmed_destination_airport")
_RESUMABLE_ROUTE_ERRORS = ("missing_route", "missing_dates")
_IATA_RE = re.compile(r"[A-Z]{3}")

# actionable hints for recoverable failures (error contract §6)
_HINTS = {
    "visa_data_stale_or_unverified":
        "visa/entry data is stale or unverified — refresh web-intel "
        "citations (retry later or restore connectivity) before booking",
    "visa_check_missing":
        "international routes need a visa/entry check first — restart the "
        "trip so the safety dependency runs",
    "unknown_passport":
        "set your passport country via PUT /api/profile/{user_id}/"
        "passport_country, then start a new trip",
    "unknown_visa_freshness":
        "visa data freshness could not be verified — refresh web-intel "
        "citations before booking",
    "fare_unverified":
        "the fare changed during re-verification — re-search and pick a "
        "fresh option",
    "missing_option":
        "include option_id (from the approval options) in the approval "
        "value",
    "visa_block_requires_reroute":
        "a blocked transit/entry risk was detected — reroute around the "
        "flagged hub or verify the requirement with official sources",
    "provider_failure":
        "an upstream provider failed — retry shortly; the trip degrades, "
        "it does not fabricate results",
    "atlas_ticketing_unavailable":
        "Your plan is safe. Atlas Sandbox ticketing is not enabled for this account, "
        "so no booking or ticket was created.",
    "ticketing_activation_required":
        "Your plan is safe. Atlas Sandbox ticketing is not enabled for this account, "
        "so no booking or ticket was created.",
    "atlas_traveler_data_required":
        "Atlas Sandbox requires an approved traveler data flow before creating an order.",
    # safety intelligence pipeline (Task #13)
    "safety_do_not_travel":
        "an official do-not-travel advisory applies — booking is blocked "
        "and approval does not remove the risk; consider the safer "
        "alternatives on the safety card",
    "safety_acknowledgement_required":
        "official advice says reconsider travel — post a separate risk "
        "acknowledgement (POST /api/trip/{id}/safety/acknowledge) before "
        "booking approval",
    "safety_unverified":
        "the destination's status could not be verified — use "
        "POST /api/trip/{id}/safety/recheck for a fresh verification "
        "before booking",
    "safety_disabled":
        "this orchestrator was started without the safety pipeline",
    "no_acknowledgement_required":
        "risk acknowledgement is only needed while advice is "
        "reconsider_travel",
    "monitoring_consent_required":
        "enable monitoring first (POST /api/trip/{id}/safety/monitor "
        "with {\"enabled\": true})",
}


# --- ddg-lite transport (web-intel tier, G3 wiring) -----------------------------

_DDG_RESULT_HREF = re.compile(
    r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL)
_DDG_SNIPPET = re.compile(
    r'class="result__snippet"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")


def _clean_ddg_href(href: str) -> Optional[str]:
    from urllib.parse import parse_qs, unquote, urlparse
    if href.startswith("//"):
        href = "https:" + href
    try:
        parsed = urlparse(href)
    except ValueError:
        return None
    if "duckduckgo.com" in (parsed.netloc or ""):
        uddg = parse_qs(parsed.query).get("uddg", [""])[0]
        return unquote(uddg) if uddg else None
    return href if parsed.scheme in ("http", "https") else None


async def ddg_lite_fetch(query: str) -> Optional[Dict[str, Any]]:
    """Keyless ddg_lite tier: tolerant HTML parse; anything unusable is
    dropped (never invented). Raises on transport failure so the client
    degrades honestly."""
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        resp = await client.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query[:400]},
            headers={"User-Agent": "Mozilla/5.0 (TravelCare web-intel)"})
        resp.raise_for_status()
    html = resp.text
    citations = []
    snippets = _DDG_SNIPPET.findall(html)
    for i, (href, title) in enumerate(_DDG_RESULT_HREF.findall(html)[:6]):
        url = _clean_ddg_href(href.strip())
        if not url:
            continue
        citations.append({
            "url": url,
            "title": _TAG.sub("", title).strip()[:200],
            "retrieved_date": date.today().isoformat(),
            "snippet_max280": _TAG.sub("", snippets[i]).strip()[:280]
            if i < len(snippets) else "",
        })
    return {"answers": [], "citations": citations}


# --- research adapter skills (bounded coordinator, owner correction C) ----------


class DomainResearchSkill(SkillBase):
    """Runtime-registered helper wrapping ResearchCoordinator.run_domain;
    mounted only for explicitly requested leisure domains.

    Capability governance (G3-DA fix F5): these adapters are EXPLICITLY
    capability-empty and are registered in the executor's manifest registry
    as capability-empty entries at boot — the documented exemption that lets
    the production executor stay fail-closed (allow_unmanifested_skills=False).
    """

    capabilities = frozenset()

    def __init__(self, domain: str, coordinator: ResearchCoordinator) -> None:
        self.domain = domain
        self._coordinator = coordinator
        self.name = f"{domain}_research"
        self.when_to_use = (f"bounded {domain} research delegated to the "
                            "ResearchCoordinator (provenance + freshness on "
                            "every result)")

    async def run(self, payload: Dict[str, Any],
                  context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self._coordinator.run_domain(self.domain, payload)


# --- orchestrator ----------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(raw: Any) -> Optional[datetime]:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class SafetyService:
    """Task #13 glue: research skill + consent-gated monitor + push path.

    The LLM NEVER decides whether a country is safe — the deterministic
    SafetyPolicyEngine inside SafetyResearchSkill computes every status.
    Push alerts go through the existing guardian_push skill ONLY.
    """

    def __init__(self, research: Optional[SafetyResearchSkill] = None,
                 monitor: Optional[SafetyMonitorSkill] = None,
                 web_intel: Optional[Any] = None,
                 fetch: Optional[Any] = None) -> None:
        self.research = research or SafetyResearchSkill(
            web_intel=web_intel, fetch=fetch)
        self.monitor = monitor or SafetyMonitorSkill()
        self.push = GuardianPushSkill()


def _assert_manifest_governance(skills: Dict[str, Any],
                                registry_by_name: Dict[str, Dict[str, Any]]
                                ) -> None:
    """Boot-time governance assertion (§14.4, G3-DA fix F5): any registered
    skill declaring a write/network capability MUST have a manifest entry.
    Unmanifested skills are tolerated ONLY when explicitly capability-empty
    (embedded helpers, e.g. the research adapters). Refusing at boot beats a
    per-request fail-closed trip failure for a configuration error."""
    for name, skill in skills.items():
        declared = set(getattr(skill, "capabilities", frozenset()))
        if not (declared & _WRITE_CAPABILITIES):
            continue
        if name not in registry_by_name:
            raise RuntimeError(
                f"manifest governance violation: skill '{name}' declares "
                f"write/network capabilities {sorted(declared & _WRITE_CAPABILITIES)} "
                "but has no manifest entry — manifest it or strip the "
                "capabilities")


class TripOrchestrator:
    """Wires the frozen/G2 services onto the §6 trip API. All state lives in
    the TripGraphExecutor registry (cross-trip isolation is proven there)."""

    def __init__(self, profile_store=None, atlas=None, web_intel=None,
                 llm_chat=None, safety_service: Optional[Any] = None,
                 safety_ttl_seconds: float = 24 * 3600,
                 allow_mock_fallback: bool = False,
                 itinerary_skill: Optional[ItinerarySkill] = None) -> None:
        self.store = profile_store or get_profile_store()
        # G4.6-DA fix F3: a cached assessment older than this TTL never
        # gates a safety-critical booking decision — the precheck forces a
        # fresh verification instead (default = the 24h advisory window).
        self.safety_ttl_seconds = float(safety_ttl_seconds)
        # FAIL-CLOSED executor (G3-DA fix F5): the three runtime-registered
        # research adapters become explicit capability-empty registry entries
        # (documented exemption, §14.4), so allow_unmanifested_skills stays
        # False in production — every execution is manifest-governed.
        registry = load_skill_registry(include_internal=True) + [
            {"name": f"{domain}_research",
             "description": (f"bounded {domain} research delegated to the "
                             "ResearchCoordinator (capability-empty embedded "
                             "helper; documented fail-closed exemption)"),
             "allowed_tools": [],
             "module_path": "routers.v1.trip",
             "path": ""}
            for domain in _RESEARCH_DOMAINS
        ]
        self.safety = safety_service
        if safety_service is not None:
            # Task #13: documented exemption entries (manifests live in
            # services/safety/ because the frozen suite pins the loader
            # glob at exactly 11 entries) — still manifest-governed.
            registry += [
                {"name": "safety_research",
                 "description": "read-only safety researcher; the "
                                "deterministic SafetyPolicyEngine computes "
                                "the status (manifest: "
                                "services/safety/safety_research.SKILL.md)",
                 "allowed_tools": ["network_read"],
                 "module_path": "services.skills.safety_research",
                 "path": ""},
                {"name": "safety_monitor",
                 "description": "consent-gated safety monitor emitting "
                                "SafetyChangeEvents on material changes "
                                "(manifest: "
                                "services/safety/safety_monitor.SKILL.md)",
                 "allowed_tools": ["network_read"],
                 "module_path": "services.skills.safety_monitor",
                 "path": ""},
            ]
        self.executor = TripGraphExecutor(registry=registry)
        atlas_client = atlas or AtlasClient()
        self.atlas = atlas_client  # AJ: recovery replacement search reuses it
        self.web_intel = web_intel or WebIntelClient(
            ddg_fetcher=ddg_lite_fetch,
            tavily_api_key="", serper_api_key="")
        self.coordinator = ResearchCoordinator(atlas=atlas_client,
                                               web_intel=self.web_intel)
        ex = self.executor
        gi = GoalIntakeSkill(llm_chat=llm_chat or llm_service.chat)
        cl = ClarifyLoopSkill(self.store)
        pe = ProfileEditSkill(self.store)
        ex.register_skill("goal_intake", gi)
        ex.register_skill("clarify_loop", cl)
        ex.register_skill("profile_edit", pe)
        ex.register_skill("flight_search", FlightSearchSkill(atlas=atlas_client))
        ex.register_skill("visa_check", VisaCheckSkill(web_intel=self.web_intel))
        ex.register_skill("flight_book", FlightBookSkill(atlas=atlas_client))
        ex.register_skill("disruption_monitor",
                          DisruptionMonitorSkill(trip_registry=ex))
        ex.register_skill("itinerary", itinerary_skill or ItinerarySkill(allow_mock_fallback=allow_mock_fallback))
        ex.register_skill("location_resolve", LocationResolveSkill())
        ex.register_skill("recovery_plan", RecoveryPlanSkill(atlas=atlas_client))
        ex.register_skill("rights_check", RightsCheckSkill())
        if safety_service is not None:
            ex.register_skill("safety_research", safety_service.research)
            ex.register_skill("safety_monitor", safety_service.monitor)
            ex.register_skill("guardian_push", safety_service.push)
        for domain in ("hotel", "activities", "local_transport"):
            ex.register_skill(f"{domain}_research",
                              DomainResearchSkill(domain, self.coordinator))
        self.skills = {
            "goal_intake": gi,
            "clarify_loop": cl,
            "profile_edit": pe,
        }
        # boot governance: no write-capable skill may run unmanifested
        _assert_manifest_governance(ex._skills, ex._registry_by_name)
        # trip_id -> intent seed for scope-clarification resume
        self._seeds: Dict[str, Dict[str, Any]] = {}
        # (trip_id:approval_id:key) -> (payload_hash, stored_response)
        self._idempotency_ledger: Dict[str, Any] = {}
        self._idempotency_locks: Dict[str, asyncio.Lock] = {}

    # -- helpers -----------------------------------------------------------------

    @staticmethod
    def _record(trip, name: str, skill_ref: str, status: str,
                latency_ms: float, details: Dict[str, Any]) -> None:
        trip.trace.append(GraphNodeStateV2(
            node_id=f"node_{len(trip.trace) + 1:03d}", name=name,
            status=status, latency_ms=round(latency_ms, 2),
            timestamp=_now_iso(), details=details, skill_ref=skill_ref,
            citations=[]))

    def _profile_ctx(self, profile) -> Dict[str, Any]:
        """Trip context view of the profile — SAFE fields only (canonical
        §5/F17): passport country and home city. No passport number, legal
        identity, or payment data is ever collected or passed on."""
        return {
            "passport_country": profile.identity.passport_country,
            "home_city": profile.identity.home_city,
        }

    # -- safety intelligence pipeline (Task #13) ----------------------------
    # The LLM NEVER decides whether a destination is clear to travel — the
    # deterministic SafetyPolicyEngine computes every status. Missing
    # evidence is unable_to_verify, never a clearance.

    def _safety_query(self, trip) -> Optional[SafetyQuery]:
        goal = (trip.context.get("goal_intake") or {}).get("goal") or {}
        dest = str(goal.get("dest_city") or "").strip()
        origin = str(goal.get("origin_city") or "").strip()
        if not dest:
            return None
        _, d_country, _ = airports_to_countries(origin or dest, dest)
        country = normalize_country(d_country).title() if d_country \
            else normalize_country(dest).title()
        window_raw = goal.get("date_window") or {}
        travel_window = None
        if isinstance(window_raw, dict) and window_raw.get("start") \
                and window_raw.get("end"):
            try:
                travel_window = DateWindow(
                    start=date.fromisoformat(str(window_raw["start"])[:10]),
                    end=date.fromisoformat(str(window_raw["end"])[:10]))
            except ValueError:
                travel_window = None
        profile_ctx = trip.context.get("profile") or {}
        return SafetyQuery(
            trip_id=trip.trip_id,
            destination_country=country or dest,
            cities=[dest],
            transit_airports=[],
            travel_window=travel_window,
            passport_country=profile_ctx.get("passport_country") or None)

    async def _ensure_safety(self, trip, force: bool = False
                             ) -> Dict[str, Any]:
        """Run (or reuse) the deterministic safety assessment for this trip.
        force=True performs a fresh verification attempt."""
        if self.safety is None:
            return {}
        safety_ctx = trip.context.get("safety") or {}
        if safety_ctx.get("assessment") and not force:
            return safety_ctx
        query = self._safety_query(trip)
        if query is None:
            return safety_ctx
        out = await self.safety.research.run(
            query.model_dump(mode="json"), trip.context)
        assessment = out["assessment"]
        safety_ctx.update({
            "assessment": assessment,
            "source_reports": out["source_reports"],
            "query": out["query"],
            "checked_at": assessment.get("checked_at"),
        })
        safety_ctx.setdefault("risk_acknowledged", False)
        if force:
            # G4.6-DA fix F1: the flag records the OUTCOME of the fresh
            # verification attempt — a retry that still yields
            # unable_to_verify verified NOTHING and never clears the block.
            safety_ctx["verification_retried"] = (
                assessment.get("trip_policy_status") != "unable_to_verify")
        trip.context["safety"] = safety_ctx
        self._record(trip, "safety_check", "safety_research", "COMPLETED",
                     0.0, {"overall_status": assessment.get("overall_status"),
                           "checked_at": assessment.get("checked_at")})
        return safety_ctx

    @staticmethod
    def _safety_authority(assessment: Dict[str, Any]) -> Dict[str, Any]:
        for entry in assessment.get("assessments_per_source", []):
            if entry.get("applies") and entry.get("source_type") in (
                    "official_government", "official_multilateral"):
                return {"authority": entry.get("authority"),
                        "updated_at": entry.get("updated_at"),
                        "canonical_url": entry.get("canonical_url")}
        return {}

    def _safety_gate_ctx(self, trip) -> Dict[str, Any]:
        """The context dict injected for flight_book's deterministic safety
        gate (do_not_travel blocks; reconsider_travel needs a separate
        acknowledgement; unable_to_verify needs a fresh verification)."""
        safety_ctx = trip.context.get("safety") or {}
        assessment = safety_ctx.get("assessment") or {}
        authority = self._safety_authority(assessment)
        return {
            "trip_policy_status": assessment.get("trip_policy_status"),
            "risk_acknowledged": bool(safety_ctx.get("risk_acknowledged")),
            "verification_retried":
                bool(safety_ctx.get("verification_retried")),
            "unverified_sources": assessment.get("unverified_sources") or [],
            **authority,
        }

    async def _booking_safety_precheck(self, trip) -> None:
        """Runs BEFORE a booking approval resolves. do_not_travel blocks
        outright (approval never makes the risk go away); reconsider_travel
        halts until the separate risk acknowledgement exists; unable_to_
        verify gets ONE bounded fresh-verification retry and BLOCKS when
        the retry fails — a failed retry is not a clearance (G4.6-DA fix
        F1). A cached assessment older than safety_ttl_seconds never gates
        a booking decision (F3); missing evidence is never a pass (F4)."""
        if self.safety is None:
            return
        safety_ctx = await self._ensure_safety(trip)
        assessment = safety_ctx.get("assessment") or {}
        # F3: staleness guard — refresh BEFORE trusting the cached status
        checked_at = _parse_iso(safety_ctx.get("checked_at"))
        if assessment and checked_at is not None:
            age = (datetime.now(timezone.utc) - checked_at).total_seconds()
            if age > self.safety_ttl_seconds:
                safety_ctx = await self._ensure_safety(trip, force=True)
                assessment = safety_ctx.get("assessment") or {}
        # F4: safety pipeline enabled but nothing was assessable (e.g. the
        # route is still unknown) — missing evidence blocks, never passes.
        if not assessment:
            raise TripApiError(
                422, "safety_unverified",
                "Booking paused: the destination's safety status could not "
                "be checked because no destination is known for this trip "
                "yet. Missing evidence never counts as a clearance.",
                recoverable=True, hint=_HINTS["safety_unverified"])
        status = assessment.get("trip_policy_status")
        if status == "unable_to_verify" \
                and not safety_ctx.get("verification_retried"):
            safety_ctx = await self._ensure_safety(trip, force=True)
            assessment = safety_ctx.get("assessment") or {}
            status = assessment.get("trip_policy_status")
        trip.context["safety_check"] = self._safety_gate_ctx(trip)
        if status == "do_not_travel":
            authority = self._safety_authority(assessment)
            raise TripApiError(
                422, "safety_do_not_travel",
                "Booking blocked: an official do-not-travel advisory "
                "applies to this destination or region. Approval does not "
                "remove the risk and there is no override. Authority: "
                f"{authority.get('authority') or 'official authority'} "
                f"(updated {authority.get('updated_at') or 'date unknown'})."
                " See the safer alternatives on the safety card.",
                recoverable=False,
                hint=_HINTS["safety_do_not_travel"])
        if status == "reconsider_travel" \
                and not safety_ctx.get("risk_acknowledged"):
            raise TripApiError(
                422, "safety_acknowledgement_required",
                "Booking paused: official advice says reconsider travel. A "
                "separate, explicit risk acknowledgement is required before "
                "booking approval. Acknowledging this warning does not "
                "remove the risk.", recoverable=True,
                hint=_HINTS["safety_acknowledgement_required"])
        if status == "unable_to_verify":
            # G4.6-DA fix F1: the bounded retry FAILED — still unverified.
            unverified = ", ".join(assessment.get("unverified_sources")
                                   or []) or "official sources unavailable"
            raise TripApiError(
                422, "safety_unverified",
                "Booking paused: the destination's status could not be "
                f"verified (unverified: {unverified}). A fresh "
                "verification was attempted and also failed — the booking "
                "stays blocked until the status can actually be verified. "
                "Try again later via the safety card.",
                recoverable=True, hint=_HINTS["safety_unverified"])

    def _trip_or_404(self, trip_id: str):
        try:
            return self.executor.get(trip_id)
        except KeyError:
            raise TripApiError(404, "unknown_trip",
                               f"trip '{trip_id}' does not exist",
                               recoverable=True,
                               hint="start a trip via POST /api/trip/start")

    def _graph_error(self, exc: GraphError) -> TripApiError:
        """Translate executor errors by `code` (defensive against the
        post-fix contract, incl. the optional approval-expiry code)."""
        code_status = {"unknown_approval": 404,
                       "already_resolved": 409,
                       "approval_expired": 410}
        status = code_status.get(exc.code,
                                 422 if exc.recoverable else 500)
        hint = _HINTS.get(exc.code) or getattr(exc, "hint", None) \
            or ("retry with a fresh approval" if exc.code == "approval_expired"
                else None)
        return TripApiError(status, exc.code, exc.message,
                            recoverable=exc.recoverable, hint=hint)

    async def _run_guarded(self, trip_id: str) -> str:
        """Run the graph; provider/upstream failures degrade into a recorded
        recoverable FAILED state instead of escaping as raw 500s."""
        trip = self.executor.get(trip_id)
        # AJ(G4.5): profile details saved mid-trip through the question
        # cards (e.g. passport country) must reach the graph — the seed
        # snapshot taken at /start would otherwise stay stale and
        # visa_check/flight_book would refuse an answered passport.
        uid = trip.context.get("user_id")
        if uid:
            trip.context["profile"] = self._profile_ctx(
                self.store.get_or_create(uid))
        try:
            return await self.executor.run(trip_id)
        except GraphError as exc:
            if exc.recoverable:
                self._record(trip, trip.current or "graph", "graph",
                             "FAILED", 0.0, {"error_code": exc.code,
                                              "message": exc.message,
                                              "recoverable": True})
                trip.status = "failed"
                return trip.status
            raise
        except Exception as exc:  # noqa: BLE001 — hostile upstream boundary
            self._record(trip, trip.current or "graph", "graph",
                         "FAILED", 0.0,
                         {"error_code": "provider_failure",
                          "message": f"{type(exc).__name__}: {exc}"[:400],
                          "recoverable": True})
            trip.status = "failed"
            return trip.status

    def _build_plan_rest(self, seed: Dict[str, Any],
                         rs: RequestedServices):
        intent = TripIntent(
            intent_id=f"intent_{uuid.uuid4().hex[:8]}",
            raw_text=seed["raw_text"],
            goal=TripGoal(**seed["goal"]),
            requested_services=rs,
            scope_clarified=True)
        plan = plan_trip(intent)
        if [n.name for n in plan.nodes[:2]] == ["goal_intake", "clarify_loop"]:
            return plan.nodes[2:]  # stage 1 already ran (recorded in trace)
        return plan.nodes

    # -- lifecycle ---------------------------------------------------------------

    def _enforce_stage1_capabilities(self, skill_ref: str) -> None:
        """Same fail-closed contract as the executor's _enforce_capabilities,
        applied to the stage-1 skills that run skill-direct — enforcement is
        never skipped on the direct-run path (G3-DA fix F5)."""
        skill = self.skills[skill_ref]
        declared = set(getattr(skill, "capabilities", frozenset()))
        entry = self.executor._registry_by_name.get(skill_ref)
        if entry is None:
            raise GraphCapabilityViolation(
                f"skill '{skill_ref}' has no manifest entry — stage-1 "
                "execution refused (fail-closed)")
        exceeding = declared - set(entry.get("allowed_tools", []))
        if exceeding:
            raise GraphCapabilityViolation(
                f"skill '{skill_ref}' exceeds declared capabilities: "
                f"{sorted(exceeding)}")

    async def start(self, goal_text: str, user_id: str, search_confirmed: bool = False) -> str:
        try:
            profile = self.store.get_or_create(user_id)
        except ValidationError:
            # unreadable-on-disk profile degrades to a recoverable envelope
            # (never a bare 500, never mislabeled; G3-DA fix F1)
            raise TripApiError(
                400, "profile_unreadable",
                f"the stored profile for '{user_id}' could not be read",
                recoverable=True,
                hint="the stored profile is unreadable — contact support or "
                     "start fresh with a different user_id")
        trip_id = f"trip_{uuid.uuid4().hex[:12]}"
        ctx = {"raw_text": goal_text, "user_id": user_id,
               "profile": self._profile_ctx(profile)}

        # stage 1 runs skill-direct so the graph mounts exactly one plan —
        # but capability enforcement still applies (G3-DA fix F5)
        self._enforce_stage1_capabilities("goal_intake")
        self._enforce_stage1_capabilities("clarify_loop")
        # Audit #9: honor the flag only if the qwen-agent package is really
        # importable; otherwise serve a LABELED legacy fallback (never a 500).
        use_qwen = is_qwen_brain()
        brain_fallback = None
        if use_qwen:
            from services.brain import qwen_brain_available
            if not qwen_brain_available():
                use_qwen = False
                brain_fallback = "legacy_fallback"
                logger.warning(
                    "TRAVELCARE_BRAIN=qwen_agent but the qwen-agent package is "
                    "absent; serving labeled legacy fallback")

        t0 = time.perf_counter()
        if use_qwen:
            from services.qwen_brain.conversation import run_qwen_goal_intake
            goal_out, clarify_out = await run_qwen_goal_intake(
                goal_text, user_id, ctx,
                goal_intake_skill=self.skills.get("goal_intake"),
                clarify_loop_skill=self.skills.get("clarify_loop"),
            )
            # missing_fields derivation (below) and the UI question stepper
            # consume the FULL legacy question list; §13.3's single next
            # question stays on the tool contract for the LLM conversation
            # surface. Restore the full list carried by the tool.
            if clarify_out.get("questions_all"):
                clarify_out["questions"] = clarify_out["questions_all"]
            t1 = time.perf_counter()
            t2 = t1
        else:
            goal_out = await self.skills["goal_intake"].run(
                {"free_text": goal_text}, ctx)
            t1 = time.perf_counter()
            clarify_out = await self.skills["clarify_loop"].run(
                {"goal": goal_out["goal"], "user_id": user_id,
                 "requested_services": goal_out["requested_services"]}, ctx)
            t2 = time.perf_counter()

        if search_confirmed:
            goal_out["goal"]["search_confirmed"] = True

        goal_out["goal"]["missing_fields"] = [
            q["field"] for q in (clarify_out.get("questions") or [])
            if q.get("field")]

        seed = {"raw_text": goal_text, "goal": goal_out["goal"],
                "requested_services": clarify_out["requested_services"],
                "clarify": clarify_out}
        self._seeds[trip_id] = seed

        scope = clarify_out.get("scope_clarification")
        trip = self.executor.start_trip(trip_id, [], ctx)
        trip.context["goal_intake"] = goal_out
        trip.context["clarify_loop"] = clarify_out
        goal_intake_details = {"degraded": goal_out.get("degraded")}
        if brain_fallback:
            goal_intake_details["brain"] = brain_fallback
        self._record(trip, "goal_intake", "goal_intake", "COMPLETED",
                     (t1 - t0) * 1000, goal_intake_details)
        self._record(trip, "clarify_loop", "clarify_loop", "COMPLETED",
                     (t2 - t1) * 1000,
                     {"questions": len(clarify_out.get("questions") or []),
                      "scope_clarification": bool(scope)})

        if scope:
            # GATE_PAUSE before any irreversible work: exactly three choices
            approval = ApprovalRequest(
                approval_id=f"{trip_id}:001",
                node_name="scope_clarification",
                options=[{"choice": c, "label": _SCOPE_LABELS.get(c, c)}
                         for c in scope["choices"]],
                created_at=_now_iso())
            trip.pending_approvals.append(approval)
            trip.status = "awaiting_approval"
            trip.current = "scope_clarification"
            self._record(trip, "scope_clarification", "scope_clarification",
                         "PAUSED", 0.0,
                         {"approval_id": approval.approval_id,
                          "choices": list(scope["choices"])})
            return trip_id

        # Phase 2: Authoritative readiness assessment
        readiness = assess_readiness(
            goal=goal_out["goal"],
            profile=profile,
            requested_services=clarify_out["requested_services"],
            clarify_data=clarify_out,
        )
        if not readiness.ready_for_search or readiness.requires_search_confirmation:
            trip.status = "clarifying" if (clarify_out.get("questions") or not clarify_out.get("complete")) else "in_progress"
            return trip_id

        rs = RequestedServices(**clarify_out["requested_services"])
        trip.context["requested_services"] = rs.model_dump()
        rest = self._build_plan_rest(seed, rs)
        trip.nodes = rest
        trip.nodes_by_name = {n.name: n for n in rest}
        if rest:
            await self._run_guarded(trip_id)
        else:
            trip.status = "completed"
        return trip_id

    async def resolve_scope(self, trip, approval: ApprovalRequest,
                            choice: str) -> None:
        seed = self._seeds.get(trip.trip_id) or {}
        rs = resolve_scope_choice(
            RequestedServices(**seed["requested_services"]), choice)
        # persist the scoped services so later goal updates (clarify answers)
        # rebuild the SAME scope instead of re-pausing (G4-DA-fix F4)
        seed["requested_services"] = rs.model_dump()
        async with trip.lock:
            if approval not in trip.pending_approvals:
                raise TripApiError(409, "already_resolved",
                                   "this scope clarification was already "
                                   "resolved", recoverable=True,
                                   hint="check GET /api/trip/{id}/state")
            trip.pending_approvals.remove(approval)
            approval.resolved_value = {"choice": choice}
            self._record(trip, "scope_clarification", "scope_clarification",
                         "COMPLETED", 0.0, {"resolved_value": {"choice": choice}})

            # Re-evaluate clarify loop with updated scope
            clarify_out = await self.skills["clarify_loop"].run(
                {"goal": seed["goal"], "user_id": trip.context.get("user_id", ""),
                 "requested_services": rs.model_dump(), "scope_choice": choice}, trip.context)
            trip.context["clarify_loop"] = clarify_out
            seed["clarify"] = clarify_out

            profile = self.store.get_or_create(str(trip.context.get("user_id") or ""))
            readiness = assess_readiness(
                goal=seed["goal"],
                profile=profile,
                requested_services=rs.model_dump(),
                clarify_data=clarify_out,
            )

            trip.context["requested_services"] = rs.model_dump()
            trip.nodes = []
            trip.nodes_by_name = {}

            if not readiness.ready_for_search:
                trip.status = "clarifying" if clarify_out.get("questions") else "in_progress"
                trip.current = None
                return

            seed["goal"]["search_confirmed"] = False
            trip.status = "in_progress"
            trip.current = None
            return

    async def resolve(self, trip_id: str, approval_id: str,
                      decision: str, value: Any,
                      idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        if not idempotency_key:
            return await self._resolve_once(
                trip_id, approval_id, decision, value, idempotency_key)
        lock_key = f"{trip_id}:{approval_id}:{idempotency_key}"
        lock = self._idempotency_locks.setdefault(lock_key, asyncio.Lock())
        async with lock:
            return await self._resolve_once(
                trip_id, approval_id, decision, value, idempotency_key)

    async def _resolve_once(self, trip_id: str, approval_id: str,
                            decision: str, value: Any,
                            idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        trip = self._trip_or_404(trip_id)
        
        # Fast path for idempotency replay
        ledger_key = None
        payload_hash = None
        if idempotency_key:
            import hashlib
            payload_str = json.dumps({"decision": decision, "value": value}, sort_keys=True, default=str)
            payload_hash = hashlib.sha256(payload_str.encode()).hexdigest()
            
            for ns in ("approvals", "recovery"):
                lk = f"POST:/api/trips/{trip_id}/{ns}/{approval_id}:{idempotency_key}"
                if lk in self._idempotency_ledger:
                    stored_hash, stored_resp = self._idempotency_ledger[lk]
                    if stored_hash == payload_hash:
                        return stored_resp
                    raise TripApiError(
                        409, "idempotency_conflict",
                        f"Idempotency-Key '{idempotency_key}' was already used with a different request payload",
                        recoverable=True,
                        hint="reuse the original payload for identical retry, or provide a new Idempotency-Key")

        approval = next((a for a in trip.pending_approvals
                         if a.approval_id == approval_id), None)
        if approval is None:
            if trip.status != "awaiting_approval":
                raise TripApiError(409, "already_resolved",
                                   f"trip '{trip_id}' has no pending approval "
                                   f"'{approval_id}' (status={trip.status})",
                                   recoverable=True,
                                   hint="approvals resolve exactly once — "
                                        "list pending via GET "
                                        "/api/trip/{id}/approvals")
            raise TripApiError(404, "unknown_approval",
                               f"approval '{approval_id}' not found for trip "
                               f"'{trip_id}' (cross-trip approval ids are "
                               "rejected)", recoverable=True,
                               hint="list this trip's pending approvals via "
                                    "GET /api/trip/{id}/approvals")

        # Gap 3: Enforce Idempotency-Key for booking approvals
        is_booking_approval = approval.purpose in (
            "initial_booking", "recovery_booking") or approval.node_name in (
                "approve_booking", "flight_book", "recovery_booking")
        if is_booking_approval and decision == "approve" and not idempotency_key:
            raise TripApiError(
                422, "missing_idempotency_key",
                "Idempotency-Key header is required for booking approvals",
                recoverable=True,
                hint="provide a unique UUID in the Idempotency-Key header")
        
        if idempotency_key:
            namespace = "recovery" if approval.node_name == "recovery_booking" else "approvals"
            ledger_key = f"POST:/api/trips/{trip_id}/{namespace}/{approval_id}:{idempotency_key}"

        if approval.node_name == "scope_clarification":
            choice = None
            if isinstance(value, dict):
                choice = value.get("choice")
            if not choice and decision in SCOPE_CHOICES:
                choice = decision
            if choice not in SCOPE_CHOICES:
                raise TripApiError(
                    422, "invalid_scope_choice",
                    f"scope choice '{choice}' is not one of the three "
                    "clarification choices", recoverable=True,
                    hint=f"choose one of: {', '.join(SCOPE_CHOICES)}")
            await self.resolve_scope(trip, approval, choice)
            res = self.resume_result(trip_id)
            if ledger_key and payload_hash:
                self._idempotency_ledger[ledger_key] = (payload_hash, res)
            return res

        if approval.node_name == "recovery_booking":
            if decision not in ("approve", "reject"):
                raise TripApiError(422, "invalid_decision",
                                   f"decision '{decision}' is not supported",
                                   recoverable=True,
                                   hint="decision must be 'approve' or "
                                        "'reject'; recovery approval carries "
                                        "value.option_id")
            resolved: Dict[str, Any] = {"approved": decision == "approve",
                                        "kind": "recovery_booking"}

            if approval.expires_at:
                expiry = _parse_iso(approval.expires_at)
                if expiry and datetime.now(timezone.utc) >= expiry:
                    raise TripApiError(
                        410, "approval_expired",
                        "This recovery approval has expired.",
                        recoverable=True,
                        hint="refresh the disruption options before booking")

            if decision == "approve":
                oid = value.get("option_id") if isinstance(value, dict) else None
                rec_opts = (trip.context.get("recovery") or {}).get("options") or []
                selected_opt = next((o for o in rec_opts
                                     if o.get("id") == oid
                                     or (o.get("option") or {}).get("id") == oid),
                                    None)
                if not oid or not selected_opt:
                    raise TripApiError(
                        422, "missing_option",
                        "recovery approval requires value.option_id from the replacement options",
                        recoverable=True)

                resolved["option_id"] = oid
                opt_data = deepcopy(selected_opt.get("option") or selected_opt)
                approval.immutable_option = deepcopy(opt_data)
                approval.price_snapshot = deepcopy(opt_data.get("price"))
                origin = (opt_data.get("dep") or {}).get("airport") or ""
                destination = (opt_data.get("arr") or {}).get("airport") or ""

                # Recovery crosses the exact same safety boundary as the
                # initial booking. A previous clearance is refreshed when
                # stale and never silently reused as an override.
                await self._booking_safety_precheck(trip)
                original_receipt = deepcopy(trip.context.get("flight_book") or {})
                try:
                    booking_res = await self.executor._skills["flight_book"].run({
                        "trip_id": trip_id,
                        "option_id": oid,
                        "origin": origin,
                        "destination": destination,
                        "option": opt_data,
                        "passenger": trip.context.get("profile") or {},
                    }, trip.context)
                except SkillError as exc:
                    raise TripApiError(
                        422, exc.code, exc.message,
                        recoverable=exc.recoverable,
                        hint=_HINTS.get(exc.code) or exc.message)
                except Exception as exc:  # provider may have accepted before timeout
                    resolved["booking_outcome"] = "uncertain"
                    resolved["provider_error"] = type(exc).__name__
                    rec = trip.context.get("recovery") or {}
                    rec["resolved"] = resolved
                    rec["booking_outcome"] = "uncertain"
                    rec["note"] = (
                        "The replacement provider response was uncertain. "
                        "No automatic retry will create another order; "
                        "reconcile the Sandbox booking before trying again.")
                    trip.context["recovery"] = rec
                    async with trip.lock:
                        if approval in trip.pending_approvals:
                            trip.pending_approvals.remove(approval)
                        approval.resolved_value = resolved
                        trip.status = "failed"
                        trip.current = None
                    self._record(
                        trip, "recovery_booking", "flight_book", "FAILED", 0.0,
                        {"error_code": "provider_outcome_uncertain",
                         "message": rec["note"], "recoverable": True})
                    res = self.resume_result(trip_id)
                    res["recovery"] = rec
                    if ledger_key and payload_hash:
                        self._idempotency_ledger[ledger_key] = (
                            payload_hash, res)
                    return res

                if not booking_res.get("booking"):
                    raise TripApiError(
                        502, "incomplete_booking_receipt",
                        "the Sandbox booking response did not include the "
                        "immutable replacement option record",
                        recoverable=True,
                        hint="do not treat this response as a confirmed replacement")

                rights = await self.executor._skills["rights_check"].run({
                    "origin_airport": origin,
                    "destination_airport": destination,
                    "event": (trip.context.get("recovery") or {}).get("event"),
                }, trip.context)
                monitor = await self.executor._skills["disruption_monitor"].run({
                    "pnr": booking_res.get("pnr"),
                    "trip_id": trip_id,
                    "flight_ids": [opt_data.get("flight_no")],
                }, trip.context)

                trip.context["recovery_booking"] = booking_res
                trip.context["rights"] = rights
                trip.context["disruption_monitor"] = monitor
                rec = trip.context.get("recovery") or {}
                receipts = rec.setdefault("receipts", {})
                receipts["original"] = original_receipt
                receipts["replacement"] = deepcopy(booking_res)
                rec["rights"] = rights
                rec["monitor"] = monitor
                trip.context["recovery"] = rec

                itin = trip.context.get("itinerary") or {"items": []}
                items = itin.setdefault("items", [])
                for item in items:
                    if item.get("kind") == "flight" \
                            and item.get("source") == "atlas_real":
                        item["honesty_label"] = (
                            "original booked flight — cancelled/replaced")
                        details = item.setdefault("details", {})
                        details["status"] = "CANCELLED_REPLACED"
                replacement_item = ItinerarySkill._flight_item(
                    booking_res["booking"])
                if replacement_item:
                    replacement_item["honesty_label"] = (
                        "booked replacement flight (Atlas sandbox record)")
                    items.insert(0, replacement_item)
                summary = ItinerarySkill.summarize(
                    items, itin.get("timezone") or
                    ItinerarySkill._timezone_for_booking(booking_res["booking"]))
                itin.update(summary)
                trip.context["itinerary"] = itin

                resolved.update({
                    "booking": booking_res,
                    "booking_outcome": "confirmed",
                    "original_receipt": original_receipt,
                    "replacement_receipt": deepcopy(booking_res),
                    "rights": rights,
                    "monitor": monitor,
                })

            async with trip.lock:
                if approval in trip.pending_approvals:
                    trip.pending_approvals.remove(approval)
                approval.resolved_value = resolved
                rec = trip.context.get("recovery") or {}
                rec["resolved"] = resolved
                trip.context["recovery"] = rec
                trip.status = "completed"
                trip.current = None
            
            self._record(trip, "recovery_choice", "recovery_choice", "COMPLETED", 0.0, resolved)
            res = self.resume_result(trip_id)
            if ledger_key and payload_hash:
                self._idempotency_ledger[ledger_key] = (payload_hash, res)
            return res

        if decision not in ("approve", "reject"):
            raise TripApiError(422, "invalid_decision",
                               f"decision '{decision}' is not supported",
                               recoverable=True,
                               hint="decision must be 'approve' or 'reject'; "
                                    "booking approvals carry value.option_id")
        resolved: Dict[str, Any] = {}
        if isinstance(value, dict):
            resolved.update(value)
        resolved["approved"] = (decision == "approve")
        if decision == "approve" and "option_id" not in resolved:
            raise TripApiError(422, "missing_option",
                               "booking approval requires value.option_id",
                               recoverable=True,
                               hint="pick one of the approval option ids "
                                    "listed in GET /api/trip/{id}/approvals")
        if decision == "approve":
            selected = next((option for option in approval.options
                             if isinstance(option, dict)
                             and option.get("id") == resolved["option_id"]), None)
            if selected is None:
                raise TripApiError(
                    422, "unknown_option",
                    "the selected option is not part of this approval snapshot",
                    recoverable=True,
                    hint="choose an option id listed on this approval")
            approval.immutable_option = selected
            approval.price_snapshot = selected.get("price")
            # Reconcile itinerary preview with the selected option before booking attempt
            if trip.context.get("itinerary"):
                trip.context["itinerary"] = ItinerarySkill.reconcile_flight(
                    trip.context["itinerary"], option=selected)
            # Task #13: deterministic safety precheck BEFORE booking resumes
            # (do_not_travel blocks outright; reconsider_travel needs the
            # separate risk acknowledgement; unable_to_verify retries once).
            await self._booking_safety_precheck(trip)
            trip.context.pop("_confirmed_price_snapshot", None)
            if approval.purpose == "price_reapproval":
                binding = (trip.context.get("_price_reapproval_bindings")
                           or {}).get(approval_id)
                if (not isinstance(binding, dict)
                        or binding.get("offer_id") != resolved["option_id"]
                        or not binding.get("booking_id")):
                    raise TripApiError(
                        409, "price_reapproval_context_missing",
                        "The verified fare context is no longer available.",
                        recoverable=True,
                        hint="verify the fare again and request a fresh approval")
                bound_price = binding.get("price") or {}
                if (bound_price.get("amount") is None
                        or not bound_price.get("currency")):
                    raise TripApiError(
                        409, "price_reapproval_context_missing",
                        "The approved fare snapshot is no longer available.",
                        recoverable=True,
                        hint="verify the fare again and request a fresh approval")
                trip.context["_confirmed_price_snapshot"] = {
                    "booking_id": binding["booking_id"],
                    "offer_id": binding["offer_id"],
                    "amount": bound_price["amount"],
                    "currency": bound_price["currency"],
                }
        try:
            await self.executor.resolve_approval(trip_id, approval_id, resolved)
        except GraphError as exc:
            raise self._graph_error(exc)

        # Check if booking paused due to fare price increase — if so, create immutable reapproval request
        latest_node = trip.trace[-1] if trip.trace else None
        if latest_node and latest_node.status == "FAILED" and (latest_node.details or {}).get("error_code") == "fare_price_increased":
            details = latest_node.details or {}
            prev_price = details.get("previous_price")
            new_price = details.get("current_price")
            curr = details.get("currency", "USD")
            oid = details.get("offer_id") or resolved.get("option_id")
            booking_id = details.get("booking_id")
            verified_at = details.get("verified_at") or _now_iso()

            selected_opt = deepcopy(approval.immutable_option or {})
            if selected_opt:
                selected_opt["price"] = {"amount": new_price, "currency": curr}
                selected_opt["price_usd"] = new_price

            new_app_id = f"{trip_id}:reapp_{len(trip.trace) + 1:03d}"
            consequence = (
                f"Fare increased from {curr} {prev_price} to {curr} {new_price}. "
                "Approving will book the flight at the updated price."
            )
            new_approval = ApprovalRequest(
                approval_id=new_app_id,
                node_name="approve_booking",
                options=[selected_opt] if selected_opt else approval.options,
                created_at=_now_iso(),
                trip_id=trip_id,
                purpose="price_reapproval",
                is_price_increase=True,
                old_price={"amount": prev_price, "currency": curr},
                new_price={"amount": new_price, "currency": curr},
                offer_id=oid,
                verified_at=verified_at,
                consequence=consequence,
                immutable_option=selected_opt,
                price_snapshot={"options": [{"id": oid, "price": {"amount": new_price, "currency": curr}}]},
                expires_at=(datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
            )
            async with trip.lock:
                bindings = trip.context.setdefault(
                    "_price_reapproval_bindings", {})
                bindings[new_app_id] = {
                    "booking_id": booking_id,
                    "offer_id": oid,
                    "verified_at": verified_at,
                    "price": {"amount": new_price, "currency": curr},
                }
                trip.pending_approvals.append(new_approval)
                trip.status = "awaiting_approval"
                trip.current = "approve_booking"
            self._record(trip, "price_reapproval_gate", "approve_booking", "PAUSED", 0.0, {
                "approval_id": new_app_id,
                "purpose": "price_reapproval",
                "old_price": prev_price,
                "new_price": new_price,
                "currency": curr,
            })

        # On booking success, promote itinerary flight to confirmed booking
        fb = trip.context.get("flight_book") or {}
        if fb.get("booking") and trip.context.get("itinerary"):
            trip.context["itinerary"] = ItinerarySkill.reconcile_flight(
                trip.context["itinerary"], booking=fb["booking"])
        res = self.resume_result(trip_id)
        if ledger_key and payload_hash:
            self._idempotency_ledger[ledger_key] = (payload_hash, res)
        return res

    # -- clarify answers (G4-DA-fix F4) -----------------------------------------

    def _sync_clarify_surface(self, trip) -> List[str]:
        clarify = trip.context.get("clarify_loop") or {}
        missing = [q.get("field") for q in (clarify.get("questions") or [])
                   if q.get("field")]
        clarify["complete"] = not missing and not clarify.get(
            "scope_clarification")
        trip.context["clarify_loop"] = clarify
        goal = (trip.context.get("goal_intake") or {}).get("goal")
        if isinstance(goal, dict):
            goal["missing_fields"] = list(missing)
        seed = self._seeds.get(trip.trip_id) or {}
        if isinstance(seed.get("goal"), dict):
            seed["goal"]["missing_fields"] = list(missing)
        return missing

    def confirmation_surface(self, trip_id: str) -> Dict[str, Any]:
        trip = self._trip_or_404(trip_id)
        missing = self._sync_clarify_surface(trip)
        chips = [
            chip.model_dump(mode="json")
            for chip in trip.confirmation_chips.values()
            if chip.state == "pending"
        ]
        return {"missing_fields": missing, "confirmation_chips": chips}

    def seed_airport_confirmation_chips(self, trip_id: str) -> None:
        trip = self._trip_or_404(trip_id)
        goal = (trip.context.get("goal_intake") or {}).get("goal") or {}
        for prefix in ("origin", "destination"):
            field = f"confirmed_{prefix}_airport"
            candidates = goal.get(f"{prefix}_airport_candidates") or []
            if len(candidates) <= 1 or goal.get(field):
                continue
            if any(c.field == field and c.state == "pending"
                   for c in trip.confirmation_chips.values()):
                continue
            chip = ConfirmationChip(
                field=field,
                proposed_value=None,
                options=list(candidates),
                message=f"Choose the {prefix} airport: "
                        f"{', '.join(candidates)}",
                trip_id=trip_id,
            )
            trip.confirmation_chips[chip.chip_id] = chip

    @staticmethod
    def _normalize_profile_clarification(field: str, value: Any) -> str:
        raw = str(value or "").strip()
        if not raw:
            raise TripApiError(
                422, "invalid_clarify_answer",
                f"the answer for '{field}' is empty", recoverable=True)
        if field == "passport_country":
            normalized = raw.upper()
            if not re.fullmatch(r"[A-Z]{2,3}", normalized):
                raise TripApiError(
                    422, "invalid_clarify_answer",
                    "passport country must be a 2- or 3-letter country code",
                    recoverable=True,
                    hint="e.g. MM, TH, SGP")
            return normalized
        if len(raw) > 120:
            raise TripApiError(
                422, "invalid_clarify_answer",
                f"the answer for '{field}' is too long", recoverable=True)
        return raw

    def _normalize_airport_confirmation(self, trip, field: str,
                                        value: Any) -> str:
        raw = str(value or "").strip().upper()
        prefix = "origin" if field == "confirmed_origin_airport" \
            else "destination"
        goal = (trip.context.get("goal_intake") or {}).get("goal") or {}
        candidates = goal.get(f"{prefix}_airport_candidates") or []
        if raw not in candidates:
            raise TripApiError(
                422, "invalid_airport_confirmation",
                f"'{raw}' is not one of the offered {prefix} airports",
                recoverable=True,
                hint=f"choose one of: {', '.join(candidates)}")
        return raw

    async def propose_clarifications(self, trip_id: str,
                                     answers: Dict[str, Any]) -> Dict[str, Any]:
        trip = self._trip_or_404(trip_id)
        if not answers:
            return {"trip_id": trip_id, **self.confirmation_surface(trip_id)}
        allowed = set(_TRIP_GOAL_FIELDS) | set(_PROFILE_CLARIFY_FIELDS) \
            | set(_AIRPORT_CONFIRM_FIELDS)
        async with trip.confirmation_lock:
            for field, raw in answers.items():
                if field not in allowed:
                    raise TripApiError(
                        422, "invalid_clarify_field",
                        f"'{field}' is not a supported clarification field",
                        recoverable=True,
                        hint=f"supported fields: {', '.join(sorted(allowed))}")
                if any(c.field == field and c.state == "pending"
                       for c in trip.confirmation_chips.values()):
                    raise TripApiError(
                        409, "confirmation_pending",
                        f"'{field}' already has a pending confirmation",
                        recoverable=True,
                        hint="confirm, reject, or correct the existing chip")
                if field in _PROFILE_CLARIFY_FIELDS:
                    normalized: Any = self._normalize_profile_clarification(
                        field, raw)
                elif field in _AIRPORT_CONFIRM_FIELDS:
                    normalized = self._normalize_airport_confirmation(
                        trip, field, raw)
                elif field == "date_window":
                    normalized = _extract_dates(str(raw or "").strip())
                    if not normalized:
                        raise TripApiError(
                            422, "invalid_clarify_answer",
                            "the date answer could not be parsed into a window",
                            recoverable=True,
                            hint="e.g. Sep 29-30 or 2026-09-29 to 2026-09-30")
                elif field == "passengers":
                    try:
                        int_val = int(str(raw or "").strip())
                        if not (1 <= int_val <= 9):
                            raise ValueError()
                        normalized = int_val
                    except Exception:
                        raise TripApiError(
                            422, "invalid_clarify_answer",
                            "passenger count must be an integer between 1 and 9",
                            recoverable=True,
                            hint="enter a passenger count from 1 to 9",
                        )
                else:
                    text_value = str(raw or "").strip()
                    upper = text_value.upper()
                    normalized = upper if _IATA_RE.fullmatch(upper) else \
                        _find_city(text_value.lower())
                    if not normalized:
                        raise TripApiError(
                            422, "invalid_clarify_answer",
                            f"could not resolve the answer for '{field}'",
                            recoverable=True,
                            hint="use a city name or a 3-letter IATA code")
                chip = ConfirmationChip(
                    field=field,
                    proposed_value=normalized,
                    message=f"Confirm {field.replace('_', ' ')}: {normalized}",
                    trip_id=trip_id,
                )
                trip.confirmation_chips[chip.chip_id] = chip
        return {"trip_id": trip_id, **self.confirmation_surface(trip_id)}

    def _remove_clarify_question(self, trip, field: str) -> None:
        goal = (trip.context.get("goal_intake") or {}).get("goal") or {}
        origin_known = bool(goal.get("origin_city"))
        clarify = trip.context.get("clarify_loop") or {}
        clarify["questions"] = [
            q for q in (clarify.get("questions") or [])
            if q.get("field") != field and not (origin_known and q.get("field") == "home_city")]
        seed = self._seeds.get(trip.trip_id) or {}
        seed_clarify = seed.get("clarify")
        if isinstance(seed_clarify, dict):
            seed_clarify["questions"] = [
                q for q in (seed_clarify.get("questions") or [])
                if q.get("field") != field and not (origin_known and q.get("field") == "home_city")]
        self._sync_clarify_surface(trip)

    async def _replan_after_confirmation(self, trip, field: str) -> None:
        """Refresh every route/safety-dependent output after a confirmed fact.

        The initial graph may already have produced search and visa previews
        while the traveler was answering clarification cards.  A confirmed
        passport or airport therefore invalidates those previews and any
        approval snapshot derived from them.  Rebuilding the reversible plan
        keeps the eventual booking gate tied to the confirmed facts.
        """
        replan_fields = ("passport_country", "search_now", "passengers", "origin_city", "dest_city", "date_window", *_AIRPORT_CONFIRM_FIELDS)
        if field not in replan_fields:
            return
        if trip.context.get("flight_book"):
            return
        if any(a.node_name == "scope_clarification"
               for a in trip.pending_approvals):
            return
        seed = self._seeds.get(trip.trip_id)
        if not seed:
            return

        if field == "search_now":
            seed["goal"]["search_confirmed"] = True
            if "goal_intake" in trip.context and isinstance(trip.context["goal_intake"].get("goal"), dict):
                trip.context["goal_intake"]["goal"]["search_confirmed"] = True
        else:
            seed["goal"]["search_confirmed"] = False
            if "goal_intake" in trip.context and isinstance(trip.context["goal_intake"].get("goal"), dict):
                trip.context["goal_intake"]["goal"]["search_confirmed"] = False

        clarify = trip.context.get("clarify_loop") or {}
        profile = self.store.get_or_create(str(trip.context.get("user_id") or ""))
        readiness = assess_readiness(
            goal=seed["goal"],
            profile=profile,
            requested_services=seed["requested_services"],
            clarify_data=clarify,
        )

        async with trip.lock:
            trip.pending_approvals = [
                approval for approval in trip.pending_approvals
                if approval.node_name == "scope_clarification"]
            for key in ("flight_search", "visa_check", "approve_booking",
                        "disruption_monitor", "hotel_research",
                        "activities_research", "local_transport_research",
                        "itinerary"):
                trip.context.pop(key, None)

        self._record(trip, "confirmation_replan", "clarify_loop",
                     "COMPLETED", 0.0, {"confirmed_field": field})

        if not readiness.ready_for_search or readiness.requires_search_confirmation:
            trip.status = "clarifying" if (clarify.get("questions") or not clarify.get("complete")) else "in_progress"
            trip.current = None
            return

        rs = RequestedServices(**seed["requested_services"])
        rest = self._build_plan_rest(seed, rs)
        async with trip.lock:
            trip.nodes = rest
            trip.nodes_by_name = {node.name: node for node in rest}
            trip.status = "pending"
            trip.current = None
        if rest:
            await self._run_guarded(trip.trip_id)
        else:
            trip.status = "completed"

    async def resolve_confirmation(self, trip_id: str, chip_id: str,
                                   decision: str,
                                   corrected_value: Any = None) -> Dict[str, Any]:
        trip = self._trip_or_404(trip_id)
        async with trip.confirmation_lock:
            chip = trip.confirmation_chips.get(chip_id)
            if chip is None:
                raise TripApiError(
                    404, "unknown_chip",
                    f"confirmation chip '{chip_id}' not found on trip '{trip_id}'",
                    recoverable=True,
                    hint="use a pending chip returned by this trip")
            if chip.state != "pending":
                raise TripApiError(
                    409, "chip_already_resolved",
                    f"chip '{chip_id}' is already '{chip.state}'",
                    recoverable=True,
                    hint="confirmation chips resolve exactly once")
            if decision not in ("confirm", "reject", "corrected"):
                raise TripApiError(
                    422, "invalid_chip_decision",
                    f"decision '{decision}' not recognized",
                    recoverable=True,
                    hint="decision must be confirm, reject, or corrected")
            if decision == "reject":
                chip.state = "rejected"
                value = None
            else:
                value = corrected_value if decision == "corrected" \
                    else chip.proposed_value
                if value is None:
                    raise TripApiError(
                        422, "confirmation_value_required",
                        "this confirmation requires selecting or correcting a value",
                        recoverable=True,
                        hint=f"choose one of: {', '.join(map(str, chip.options))}")
                field = chip.field
                if field in _PROFILE_CLARIFY_FIELDS:
                    value = self._normalize_profile_clarification(field, value)
                    user_id = str(trip.context.get("user_id") or "")
                    self.store.set_field(user_id, field, value, source="user")
                    trip.context["profile"] = self._profile_ctx(
                        self.store.get_or_create(user_id))
                    self._remove_clarify_question(trip, field)
                elif field in _TRIP_GOAL_FIELDS:
                    result = await self.answer_clarify(
                        trip_id, field, str(value) if field != "date_window"
                        else f"{value['start']} to {value['end']}")
                    value = result["clarify"]["value"]
                elif field in _AIRPORT_CONFIRM_FIELDS:
                    value = self._normalize_airport_confirmation(
                        trip, field, value)
                    goal = (trip.context.get("goal_intake") or {}).get("goal") or {}
                    goal[field] = value
                    route_field = "origin_city" if field == \
                        "confirmed_origin_airport" else "dest_city"
                    goal[route_field] = value
                    seed = self._seeds.get(trip_id) or {}
                    if isinstance(seed.get("goal"), dict):
                        seed["goal"][field] = value
                        seed["goal"][route_field] = value
                chip.corrected_value = value if decision == "corrected" else None
                chip.state = "corrected" if decision == "corrected" \
                    else "confirmed"
                await self._replan_after_confirmation(trip, field)
            surface = self.confirmation_surface(trip_id)
            return {
                "chip_id": chip_id,
                "status": chip.state,
                "decision": decision,
                "field": chip.field,
                "applied_value": value,
                **surface,
                "state": self.state(trip_id),
            }

    async def answer_clarify(self, trip_id: str, field: str,
                             value: str) -> Dict[str, Any]:
        """Persist a NON-profile clarify answer (origin_city, dest_city,
        date_window) into the paused/failed trip's goal, strip the answered
        question and resume a trip that failed on the now-completed route.
        Previously the chip confirm was a silent no-op and the rerun failed
        missing_route again."""
        trip = self._trip_or_404(trip_id)
        if field not in _TRIP_GOAL_FIELDS:
            raise TripApiError(
                422, "invalid_clarify_field",
                f"'{field}' is not a trip-goal clarify field",
                recoverable=True,
                hint=f"trip-goal fields: {', '.join(_TRIP_GOAL_FIELDS)}; "
                     "profile fields use PUT /api/profile/{user_id}/{field}")
        seed = self._seeds.get(trip_id)
        if not seed:
            raise TripApiError(404, "unknown_trip",
                               f"trip '{trip_id}' has no intake seed",
                               recoverable=True,
                               hint="start a trip via POST /api/trip/start")
        raw = value.strip()
        if not raw:
            raise TripApiError(422, "invalid_clarify_answer",
                               f"the answer for '{field}' is empty",
                               recoverable=True,
                               hint="provide a concrete value, e.g. Bangkok "
                                    "or 'Sep 29-30'")

        if field == "date_window":
            window = _extract_dates(raw)
            if not window:
                raise TripApiError(
                    422, "invalid_clarify_answer",
                    "the date answer could not be parsed into a window",
                    recoverable=True,
                    hint="e.g. 'Sep 29-30' or 2026-09-29 to 2026-09-30")
            normalized: Any = window
        elif field == "passengers":
            try:
                int_val = int(raw)
                if not (1 <= int_val <= 9):
                    raise ValueError()
                normalized = int_val
            except Exception:
                raise TripApiError(
                    422, "invalid_clarify_answer",
                    "passenger count must be an integer between 1 and 9",
                    recoverable=True,
                    hint="enter a passenger count from 1 to 9",
                )
        else:
            upper = raw.upper()
            city = upper if _IATA_RE.fullmatch(upper) else _find_city(raw.lower())
            if not city:
                raise TripApiError(
                    422, "invalid_clarify_answer",
                    f"could not resolve '{raw[:60]}' to a known city",
                    recoverable=True,
                    hint="use a city name (e.g. Bangkok) or an IATA code "
                         "(e.g. BKK)")
            normalized = city

        goal = seed["goal"]
        goal[field] = normalized
        goal["search_confirmed"] = False
        if field == "passengers":
            goal["passengers_explicit"] = True
            goal["passengers_confirmed"] = True
        gi = trip.context.get("goal_intake") or {}
        gi["goal"] = goal
        trip.context["goal_intake"] = gi

        # the answered question disappears from the clarify surface
        origin_known = bool(goal.get("origin_city"))
        clarify = trip.context.get("clarify_loop") or {}
        clarify["questions"] = [q for q in (clarify.get("questions") or [])
                                if q.get("field") != field and not (origin_known and q.get("field") == "home_city")]
        trip.context["clarify_loop"] = clarify
        seed_clarify = seed.get("clarify")
        if isinstance(seed_clarify, dict):
            seed_clarify["questions"] = [
                q for q in (seed_clarify.get("questions") or [])
                if q.get("field") != field and not (origin_known and q.get("field") == "home_city")]
        self._sync_clarify_surface(trip)

        # Phase 2: Authoritative readiness check
        profile = self.store.get_or_create(str(trip.context.get("user_id") or ""))
        readiness = assess_readiness(
            goal=goal,
            profile=profile,
            requested_services=seed["requested_services"],
            clarify_data=clarify,
        )

        resumed = False
        trip.status = "clarifying" if (
            clarify.get("questions") or not clarify.get("complete")
        ) else "in_progress"
        trip.current = None

        result = self.resume_result(trip_id)
        result["clarify"] = {"field": field, "value": normalized,
                             "resumed": resumed}
        return result

    # -- introspection -------------------------------------------------------------

    def state(self, trip_id: str) -> Dict[str, Any]:
        trip = self._trip_or_404(trip_id)
        snapshot = self.executor.telemetry(trip_id)
        ctx = trip.context

        # Supply latest failure details from trace if trip failed
        failed = next((n for n in reversed(trip.trace) if n.status == "FAILED"), None)
        if failed and snapshot.get("status") == "failed":
            details = failed.details or {}
            code = details.get("error_code", "node_failed")
            snapshot["error"] = {
                "code": code,
                "message": details.get("message", "node execution failed"),
                "recoverable": bool(details.get("recoverable", False)),
                "hint": _HINTS.get(code) or details.get("message"),
                "failed_node": failed.name,
                "details": details,
            }

        outputs: Dict[str, Any] = {}
        clarify = ctx.get("clarify_loop")
        if clarify:
            outputs["clarify"] = {
                "questions": clarify.get("questions") or [],
                "scope_clarification": clarify.get("scope_clarification"),
                "complete": clarify.get("complete"),
            }
        search = ctx.get("flight_search")
        if search:
            outputs["flight_search"] = search
        visa = ctx.get("visa_check")
        if visa:
            outputs["visa_check"] = visa
        booking = ctx.get("flight_book")
        if booking:
            outputs["booking"] = booking
        itinerary = ctx.get("itinerary")
        if itinerary:
            outputs["itinerary"] = itinerary
        recovery = ctx.get("recovery")
        if recovery:
            outputs["recovery"] = recovery
        recovery_booking = ctx.get("recovery_booking")
        if recovery_booking:
            outputs["recovery_booking"] = recovery_booking
        rights = ctx.get("rights")
        if rights:
            outputs["rights"] = rights
        for domain in ("hotel", "activities", "local_transport"):
            domain_key = f"{domain}_research"
            domain_res = ctx.get(domain_key)
            if domain_res:
                outputs[domain_key] = domain_res
        # Task #13: safety assessment + change events surface in trip state
        outputs["safety_enabled"] = self.safety is not None
        safety = ctx.get("safety")
        if safety:
            outputs["safety"] = {
                "assessment": safety.get("assessment"),
                "source_reports": safety.get("source_reports"),
                "query": safety.get("query"),
                "risk_acknowledged": bool(safety.get("risk_acknowledged")),
                "monitor_enabled": bool(safety.get("monitor_enabled")),
                "checked_at": safety.get("checked_at"),
            }
        safety_events = ctx.get("safety_events")
        if safety_events:
            outputs["safety_events"] = safety_events
        snapshot["outputs"] = outputs
        snapshot.update(self.confirmation_surface(trip_id))
        seed = self._seeds.get(trip_id) or {}
        goal = seed.get("goal") or (ctx.get("goal_intake") or {}).get("goal") or {}
        clarify_data = ctx.get("clarify_loop") or seed.get("clarify") or {}
        profile = self.store.get_or_create(str(ctx.get("user_id") or ""))
        readiness = assess_readiness(
            goal=goal,
            profile=profile,
            requested_services=seed.get("requested_services"),
            clarify_data=clarify_data,
        )
        snapshot["readiness"] = readiness.model_dump(mode="json")
        turn = project_conversation_turn(snapshot, context=ctx)
        snapshot["conversation"] = turn.model_dump(mode="json")
        return snapshot

    def resume_result(self, trip_id: str) -> Dict[str, Any]:
        trip = self._trip_or_404(trip_id)
        result: Dict[str, Any] = {
            "trip_id": trip_id,
            "status": trip.status,
            "current_state": trip.current,
            "graph_state_url": f"/api/trip/{trip_id}/state",
        }
        failed = next((n for n in reversed(trip.trace)
                       if n.status == "FAILED"), None)
        if failed:
            details = failed.details or {}
            code = details.get("error_code", "node_failed")
            result["error"] = {
                "code": code,
                "message": details.get("message", "node execution failed"),
                "recoverable": bool(details.get("recoverable", False)),
                "hint": _HINTS.get(code) or details.get("message"),
                "node": failed.name,
            }
        booking = trip.context.get("flight_book")
        if booking:
            result["booking"] = booking
        return result

    # -- recovery (AJ §8.6): replacement options + suitability reasons --------

    @staticmethod
    def _recovery_reason(option: Dict[str, Any],
                         original: Dict[str, Any]) -> str:
        """Deterministic plain-language suitability reason derived ONLY from
        the returned data (never invented)."""
        reasons = []
        if option.get("carrier") and original.get("carrier") \
                and option["carrier"] == original["carrier"]:
            reasons.append("same airline as your booked flight")
        dep_new = str((option.get("dep") or {}).get("time") or "")
        dep_old = str((original.get("dep") or {}).get("time") or "")
        if dep_new and dep_old:
            if dep_new[11:16] < dep_old[11:16]:
                reasons.append(f"leaves earlier ({dep_new[11:16]})")
            elif dep_new[11:16] > dep_old[11:16]:
                reasons.append(f"leaves later ({dep_new[11:16]})")
        try:
            if float((option.get("price") or {}).get("amount") or 0) < \
                    float((original.get("price") or {}).get("amount") or 0):
                reasons.append("lower price than your booked flight")
        except (TypeError, ValueError):
            pass
        if not reasons:
            reasons.append("same route, available in the Atlas Sandbox")
        return "; ".join(reasons[:2]).capitalize()

    async def _build_recovery(self, trip, event: Dict[str, Any]) -> None:
        """After the recovery subgraph mounts, search replacement options on
        the same route and pause on a SEPARATE recovery approval. Provider
        failures degrade honestly (empty options + note), never fabricate."""
        booking = trip.context.get("flight_book") or {}
        original = (booking.get("booking") or {}).get("option") or {}
        dep = original.get("dep") or {}
        arr = original.get("arr") or {}
        recovery: Dict[str, Any] = {
            "event": event, "original": original, "options": [],
            "degraded": False, "note": "",
            "receipts": {"original": deepcopy(booking),
                         "replacement": None},
            "sandbox_note": "Replacement options come from the Atlas Sandbox "
                            "— a safe practice environment with researched "
                            "mock data.",
        }
        # Task #13: automatic recovery is BLOCKED into a destination under
        # an active do-not-travel advisory — no options, no approval.
        if self.safety is not None:
            safety_error: Optional[Exception] = None
            try:
                safety_ctx = await self._ensure_safety(trip)
            except Exception as exc:  # noqa: BLE001 — degrade, never fabricate
                safety_error = exc
                safety_ctx = trip.context.get("safety") or {}
            status = ((safety_ctx.get("assessment") or {})
                      .get("trip_policy_status"))
            if status == "do_not_travel":
                authority = self._safety_authority(
                    safety_ctx.get("assessment") or {})
                recovery["safety_blocked"] = True
                recovery["note"] = (
                    "Recovery rebooking is blocked: an official do-not-travel "
                    "advisory applies to this destination. Authority: "
                    f"{authority.get('authority') or 'official authority'} "
                    "(updated "
                    f"{authority.get('updated_at') or 'date unknown'}). "
                    "Approval does not remove the risk.")
                trip.context["recovery"] = recovery
                self._record(trip, "recovery_blocked", "safety_research",
                             "COMPLETED", 0.0,
                             {"reason": "do_not_travel",
                              "authority": authority.get("authority")})
                return
            if safety_error is not None and not status:
                # G4.6-DA fix F2: a FAILED safety check is never a silent
                # pass — surface the unverified state and record it
                # honestly (a cached assessment, when one exists, still
                # gates via the status check above).
                recovery["safety_unverified"] = True
                recovery["note"] = (
                    "The destination's safety status could not be verified "
                    f"({type(safety_error).__name__}) and no earlier "
                    "assessment exists. Replacement options are shown "
                    "without a verified safety status — check official "
                    "advice before choosing one.")
                self._record(trip, "recovery_safety_check_failed",
                             "safety_research", "FAILED", 0.0,
                             {"error": type(safety_error).__name__})
        if dep.get("airport") and arr.get("airport"):
            try:
                plan = await self.executor._skills["recovery_plan"].run({
                    "trip_id": trip.trip_id,
                    "booking": (booking.get("booking") or {}),
                    "event": event,
                }, trip.context)
                for row in plan.get("recovery_options") or []:
                    option = deepcopy(row.get("option") or {})
                    option["reason"] = self._recovery_reason(option, original)
                    recovery["options"].append(option)
            except Exception as exc:  # noqa: BLE001 — hostile upstream
                recovery["degraded"] = True
                recovery["note"] = (
                    f"Replacement search degraded ({type(exc).__name__}) — "
                    "no options are shown rather than invented.")
        trip.context["recovery"] = recovery
        if recovery["options"]:
            option_snapshot = deepcopy(recovery["options"])
            approval = ApprovalRequest(
                approval_id=f"{trip.trip_id}:rec1",
                node_name="recovery_booking",
                options=[{"id": o["id"], "reason": o["reason"],
                          "label": f"{o.get('carrier', '')} "
                                   f"{o.get('flight_no', '')}".strip()}
                         for o in recovery["options"]],
                created_at=_now_iso(),
                trip_id=trip.trip_id,
                purpose="recovery_booking",
                immutable_option={"options": option_snapshot},
                price_snapshot={
                    "options": [
                        {"id": o.get("id"),
                         "price": deepcopy(o.get("price"))}
                        for o in option_snapshot
                    ]
                },
                expires_at=(datetime.now(timezone.utc) + timedelta(minutes=30))
                .isoformat())
            trip.pending_approvals.append(approval)
            trip.status = "awaiting_approval"
            trip.current = "recovery_booking"
            self._record(trip, "recovery_options", "recovery_options",
                         "PAUSED", 0.0,
                         {"approval_id": approval.approval_id,
                          "options": len(recovery["options"])})

    async def simulate_disruption(self, trip_id: str,
                                  event: Dict[str, Any]) -> Dict[str, Any]:
        trip = self._trip_or_404(trip_id)
        telemetry = await self.executor.on_disruption(trip_id, event)
        await self._build_recovery(trip, event)
        return {"mounted": True, "trip_id": trip.trip_id,
                "subgraph": telemetry, "event": event}

    # -- safety API (Task #13) -------------------------------------------------

    def _require_safety(self) -> None:
        if self.safety is None:
            raise TripApiError(
                503, "safety_disabled",
                "this orchestrator was started without the safety pipeline",
                recoverable=True, hint=_HINTS["safety_disabled"])

    async def safety_assessment(self, trip_id: str,
                                force: bool = False) -> Dict[str, Any]:
        """GET/POST safety: current (or fresh, with force) assessment."""
        self._require_safety()
        trip = self._trip_or_404(trip_id)
        safety_ctx = await self._ensure_safety(trip, force=force)
        assessment = safety_ctx.get("assessment")
        if not assessment:
            raise TripApiError(
                409, "safety_not_runnable",
                "no destination is known for this trip yet — the safety "
                "check runs once the route is clarified",
                recoverable=True,
                hint="answer the route clarification first")
        return {
            "trip_id": trip_id,
            "assessment": assessment,
            "source_reports": safety_ctx.get("source_reports") or [],
            "query": safety_ctx.get("query"),
            "risk_acknowledged": bool(safety_ctx.get("risk_acknowledged")),
            "monitor_enabled": bool(safety_ctx.get("monitor_enabled")),
            "safety_events": trip.context.get("safety_events") or [],
            "checked_at": safety_ctx.get("checked_at"),
            "fresh_check": bool(force),
        }

    async def safety_acknowledge(self, trip_id: str) -> Dict[str, Any]:
        """Separate risk acknowledgement — ONLY meaningful while official
        advice is reconsider_travel. It NEVER makes the risk go away."""
        self._require_safety()
        trip = self._trip_or_404(trip_id)
        safety_ctx = await self._ensure_safety(trip)
        assessment = safety_ctx.get("assessment") or {}
        status = assessment.get("trip_policy_status")
        if status != "reconsider_travel":
            raise TripApiError(
                409, "no_acknowledgement_required",
                f"risk acknowledgement is only needed while advice is "
                f"reconsider_travel (current status: "
                f"{status or 'unknown'})", recoverable=True,
                hint=_HINTS["no_acknowledgement_required"])
        safety_ctx["risk_acknowledged"] = True
        safety_ctx["acknowledged_at"] = _now_iso()
        trip.context["safety"] = safety_ctx
        trip.context["safety_check"] = self._safety_gate_ctx(trip)
        self._record(trip, "safety_acknowledgement", "safety_research",
                     "COMPLETED", 0.0,
                     {"acknowledged_at": safety_ctx["acknowledged_at"]})
        return {
            "trip_id": trip_id,
            "risk_acknowledged": True,
            "status": status,
            "notice": "Acknowledging this warning does not remove the "
                      "risk. Booking can now proceed to approval.",
            "acknowledged_at": safety_ctx["acknowledged_at"],
        }

    async def safety_monitor(self, trip_id: str,
                             enabled: bool) -> Dict[str, Any]:
        """Consent gate for monitoring. With consent, a bounded baseline
        check runs; later rechecks emit SafetyChangeEvents on material
        changes only. Push alerts go through guardian_push ONLY."""
        self._require_safety()
        trip = self._trip_or_404(trip_id)
        monitor = self.safety.monitor
        monitor.set_consent(trip_id, enabled)
        safety_ctx = trip.context.get("safety") or {}
        safety_ctx["monitor_enabled"] = bool(enabled)
        trip.context["safety"] = safety_ctx
        out: Dict[str, Any] = {"trip_id": trip_id,
                               "monitor_enabled": bool(enabled)}
        if not enabled:
            out["status"] = "monitoring_disabled"
            return out
        query = self._safety_query(trip)
        if query is None:
            out["status"] = "armed_no_route_yet"
            return out
        try:
            result = await monitor.check(trip_id, query, self.safety.research)
        except Exception as exc:  # noqa: BLE001 — G4.6-DA fix F5: honest
            # degrade, never a bare 500 on the consent endpoint
            self._record(trip, "safety_monitor_check_failed",
                         "safety_monitor", "FAILED", 0.0,
                         {"error": type(exc).__name__})
            out["status"] = "check_failed"
            return out
        await self._store_safety_events(trip, result.get("events") or [])
        out.update({"status": result.get("status"),
                    "events": result.get("events") or []})
        return out

    async def safety_recheck_with_monitor(self, trip_id: str
                                          ) -> Dict[str, Any]:
        """A fresh recheck that ALSO runs the consent-gated monitor path
        (used by the UI 'Check again')."""
        self._require_safety()
        trip = self._trip_or_404(trip_id)
        payload = await self.safety_assessment(trip_id, force=True)
        if self.safety.monitor.consent_enabled(trip_id):
            query = self._safety_query(trip)
            if query is not None:
                try:
                    result = await self.safety.monitor.check(
                        trip_id, query, self.safety.research)
                except Exception as exc:  # noqa: BLE001 — G4.6-DA fix F5:
                    # the fresh assessment survives a monitor failure
                    self._record(trip, "safety_monitor_check_failed",
                                 "safety_monitor", "FAILED", 0.0,
                                 {"error": type(exc).__name__})
                    payload["monitor_status"] = "check_failed"
                    payload["safety_events"] = (
                        trip.context.get("safety_events") or [])
                    return payload
                await self._store_safety_events(
                    trip, result.get("events") or [])
                payload["monitor_status"] = result.get("status")
                payload["monitor_events"] = result.get("events") or []
        payload["safety_events"] = trip.context.get("safety_events") or []
        return payload

    async def _store_safety_events(self, trip,
                                   events: List[Dict[str, Any]]) -> None:
        """Surface SafetyChangeEvents in trip state; push (only with
        consent, already checked) via the guardian_push skill path."""
        if not events:
            return
        existing = trip.context.get("safety_events") or []
        existing.extend(events)
        trip.context["safety_events"] = existing[-20:]
        self._record(trip, "safety_change_detected", "safety_monitor",
                     "COMPLETED", 0.0,
                     {"events": len(events),
                      "change_kinds": sorted({k for e in events
                                              for k in e.get("change_kinds",
                                                             [])})})
        for event in events:
            delivery = await self.safety.push.run({
                "event": "safety_change",
                "payload": {
                    "trip_id": trip.trip_id,
                    "change_kinds": event.get("change_kinds"),
                    "differences": event.get("differences"),
                    "proposed_action": event.get("proposed_action"),
                    "approval_required": True,
                },
            })
            self._record(trip, "safety_change_alert", "guardian_push",
                         "COMPLETED", 0.0,
                         {"delivery_status":
                          delivery.get("delivery_status")})


# --- singleton ---------------------------------------------------------------------

_orchestrator: Optional[TripOrchestrator] = None


def get_trip_orchestrator() -> TripOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        # production default: the REAL safety pipeline is enabled (Task
        # #13) — bounded official fetches, honest degrade, deterministic
        # policy engine. Test harnesses install their own orchestrator via
        # set_trip_orchestrator() and stay unaffected.
        _orchestrator = TripOrchestrator(safety_service=SafetyService())
    return _orchestrator


def set_trip_orchestrator(orch: Optional[TripOrchestrator]) -> None:
    """Test hook: install/reset the shared orchestrator."""
    global _orchestrator
    _orchestrator = orch


# --- API ------------------------------------------------------------------------------


class TripStartRequest(BaseModel):
    # G3-DA fix F6: bounded input at the boundary — a 5MB goal is refused
    # before allocation/retention (max_length -> invalid_request envelope)
    goal_text: str = Field(..., max_length=4000)
    user_id: str = Field(..., max_length=128)


class ApprovalDecision(BaseModel):
    decision: str
    value: Optional[Any] = None


class ClarifyAnswerRequest(BaseModel):
    # bounded input at the boundary (§6, same pattern as TripStartRequest)
    field: str = Field(..., max_length=64)
    value: str = Field(..., max_length=200)


class SafetyMonitorRequest(BaseModel):
    enabled: bool


@router.post("/start")
async def trip_start(body: TripStartRequest):
    # explicit user_id validation FIRST (G3-DA fix F3): invalid_user_id is
    # reserved for the identifier check and can never mask goal-parse errors
    if not _USER_ID_RE.fullmatch(body.user_id):
        raise TripApiError(
            400, "invalid_user_id",
            f"user_id '{body.user_id[:50]}' contains unsupported characters",
            recoverable=True,
            hint="use only letters, digits, '_' or '-' in user_id")
    if not body.goal_text.strip():
        raise TripApiError(422, "empty_goal",
                           "goal_text must carry the travel goal",
                           recoverable=True,
                           hint="e.g. 'plan my whole trip BKK to Singapore "
                                "Sep 28-30'")
    orch = get_trip_orchestrator()
    try:
        trip_id = await orch.start(body.goal_text, body.user_id)
    except ValidationError:
        # hostile goal text (e.g. an impossible calendar date) fails goal
        # construction: 422 invalid_goal with a SANITIZED message — no raw
        # pydantic detail, no errors.pydantic.dev URLs (G3-DA fix F3)
        raise TripApiError(
            422, "invalid_goal",
            "the goal text could not be parsed into a valid travel goal",
            recoverable=True,
            hint="check the dates and locations — use a real calendar date, "
                 "e.g. 'Sep 28-30' or 2026-09-28")
    except ValueError as exc:
        raise TripApiError(400, "invalid_user_id", str(exc), recoverable=True,
                           hint="use only letters, digits, '_' or '-' in "
                                "user_id")
    except GraphError as exc:
        raise orch._graph_error(exc)
    return {"trip_id": trip_id,
            "graph_state_url": f"/api/trip/{trip_id}/state",
            "status": orch.executor.get(trip_id).status}


@router.get("/{trip_id}/state")
async def trip_state(trip_id: str):
    return JSONResponse(content=get_trip_orchestrator().state(trip_id))


@router.get("/{trip_id}/approvals")
async def trip_approvals(trip_id: str):
    orch = get_trip_orchestrator()
    trip = orch._trip_or_404(trip_id)
    return {"trip_id": trip_id,
            "approvals": [a.model_dump(mode="json")
                          for a in trip.pending_approvals]}


@router.post("/{trip_id}/approvals/{approval_id}")
async def trip_resolve_approval(trip_id: str, approval_id: str,
                                body: ApprovalDecision,
                                idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
                                x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key")):
    key = idempotency_key or x_idempotency_key
    orch = get_trip_orchestrator()
    return await orch.resolve(trip_id, approval_id, body.decision, body.value, idempotency_key=key)


@router.post("/{trip_id}/clarify-answers")
async def trip_clarify_answer(trip_id: str, body: ClarifyAnswerRequest):
    """G4-DA-fix F4: non-profile clarify answers persist into the trip goal
    (and resume a trip that failed on the now-complete route)."""
    orch = get_trip_orchestrator()
    return await orch.answer_clarify(trip_id, body.field, body.value)


# --- safety intelligence endpoints (Task #13) --------------------------------
# Statuses come ONLY from the deterministic SafetyPolicyEngine; the LLM
# never decides whether a destination is clear to travel.


@router.get("/{trip_id}/safety")
async def trip_safety(trip_id: str):
    return JSONResponse(
        content=await get_trip_orchestrator().safety_assessment(trip_id))


@router.post("/{trip_id}/safety/recheck")
async def trip_safety_recheck(trip_id: str):
    """Fresh verification: re-collects official sources and re-runs the
    monitor path when consent is enabled."""
    orch = get_trip_orchestrator()
    return JSONResponse(
        content=await orch.safety_recheck_with_monitor(trip_id))


@router.post("/{trip_id}/safety/acknowledge")
async def trip_safety_acknowledge(trip_id: str):
    """Separate risk acknowledgement for reconsider_travel — it never makes
    the risk go away and is recorded separately from booking approval."""
    return JSONResponse(
        content=await get_trip_orchestrator().safety_acknowledge(trip_id))


@router.post("/{trip_id}/safety/monitor")
async def trip_safety_monitor(trip_id: str, body: SafetyMonitorRequest):
    """Monitoring consent gate: no consent -> no rechecks, no events, no
    alerts. Revoking consent clears stored monitor state."""
    return JSONResponse(content=await get_trip_orchestrator().safety_monitor(
        trip_id, body.enabled))


@router.get("/{trip_id}/simulate-disruption")
async def trip_simulate_disruption(trip_id: str, allow_sim: str = ""):
    if allow_sim != "1":
        raise TripApiError(
            403, "simulation_disabled",
            "disruption simulation is a demo hook and is disabled by default",
            recoverable=True,
            hint="append ?allow_sim=1 to enable the demo simulation hook")
    orch = get_trip_orchestrator()
    trip = orch._trip_or_404(trip_id)
    booking = trip.context.get("flight_book") or {}
    option = (booking.get("booking") or {}).get("option") or {}
    event = {
        "flight_number": option.get("flight_no") or "SIM-FLIGHT",
        "status": "DISRUPTED_SIMULATED",
        "simulated": True,
        "reason": "G3 demo hook (simulate-disruption?allow_sim=1)",
    }
    try:
        return await orch.simulate_disruption(trip_id, event)
    except GraphError as exc:
        raise orch._graph_error(exc)


@router.get("/{trip_id}/stream")
async def trip_stream(trip_id: str):
    """SSE step events: node records, pending approvals, terminal status.

    Bounded lifetime (G3-DA fix F7): when no new events arrive within the
    idle window — or the absolute lifetime is exceeded — a final status
    event with reason 'stream_timeout' is emitted and the stream closes;
    the trip itself keeps its status untouched."""
    orch = get_trip_orchestrator()
    orch._trip_or_404(trip_id)

    async def event_gen():
        sent_nodes = 0
        sent_approvals = 0
        started = time.monotonic()
        last_progress = started
        while True:
            trip = orch.executor.get(trip_id)
            new_events = False
            for rec in trip.trace[sent_nodes:]:
                yield ("event: node\n"
                       f"data: {json.dumps(rec.model_dump(mode='json'))}\n\n")
                new_events = True
            sent_nodes = len(trip.trace)
            for approval in trip.pending_approvals[sent_approvals:]:
                yield ("event: approval\n"
                       f"data: {json.dumps(approval.model_dump(mode='json'))}\n\n")
                new_events = True
            sent_approvals = len(trip.pending_approvals)
            if new_events:
                last_progress = time.monotonic()
            if trip.status in ("completed", "failed"):
                yield ("event: status\n"
                       f"data: {json.dumps({'status': trip.status})}\n\n")
                return
            now = time.monotonic()
            if (now - last_progress > STREAM_IDLE_TIMEOUT_SECONDS
                    or now - started > STREAM_MAX_LIFETIME_SECONDS):
                yield ("event: status\n"
                       f"data: {json.dumps({'status': trip.status, 'reason': 'stream_timeout'})}\n\n")
                return
            await asyncio.sleep(0.4)

    return StreamingResponse(event_gen(), media_type="text/event-stream")


# ==============================================================================
# §6 CANONICAL PLURAL ROUTER (/api/trips/*)
# ==============================================================================

class ClarificationsRequest(BaseModel):
    answers: Dict[str, Any] = Field(default_factory=dict)


class ConfirmationChipDecision(BaseModel):
    decision: str
    corrected_value: Optional[Any] = None


class SimulateDisruptionRequest(BaseModel):
    scenario: Optional[str] = None
    flight_number: Optional[str] = None
    reason: Optional[str] = None


@trips_router.post("")
@trips_router.post("/")
async def trips_start(body: TripStartRequest):
    res = await trip_start(body)
    trip_id = res["trip_id"]
    orch = get_trip_orchestrator()
    orch.seed_airport_confirmation_chips(trip_id)
    surface = orch.confirmation_surface(trip_id)
    return {
        "trip_id": trip_id,
        "status": res["status"],
        **surface,
        "state_url": f"/api/trips/{trip_id}/state",
        "stream_url": f"/api/trips/{trip_id}/stream",
    }


@trips_router.get("/{trip_id}")
async def trips_summary(trip_id: str):
    orch = get_trip_orchestrator()
    trip = orch._trip_or_404(trip_id)
    goal = (trip.context.get("goal_intake") or {}).get("goal")
    return {
        "trip_id": trip_id,
        "status": trip.status,
        "current_state": trip.current,
        "goal": goal,
        "pending_approvals": len(trip.pending_approvals),
        **orch.confirmation_surface(trip_id),
        "state_url": f"/api/trips/{trip_id}/state",
        "stream_url": f"/api/trips/{trip_id}/stream",
    }


@trips_router.get("/{trip_id}/state")
async def trips_state(trip_id: str):
    return JSONResponse(content=get_trip_orchestrator().state(trip_id))


@trips_router.get("/{trip_id}/approvals")
async def trips_approvals(trip_id: str):
    return await trip_approvals(trip_id)


@trips_router.post("/{trip_id}/approvals/{approval_id}")
async def trips_resolve_approval(trip_id: str, approval_id: str,
                                 body: ApprovalDecision,
                                 idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
                                 x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key")):
    return await trip_resolve_approval(trip_id, approval_id, body,
                                       idempotency_key=idempotency_key,
                                       x_idempotency_key=x_idempotency_key)


@trips_router.post("/{trip_id}/clarifications")
async def trips_clarifications(trip_id: str, body: ClarificationsRequest):
    orch = get_trip_orchestrator()
    return await orch.propose_clarifications(trip_id, body.answers)


@trips_router.post("/{trip_id}/confirmations/{chip_id}")
async def trips_confirmation(trip_id: str, chip_id: str, body: ConfirmationChipDecision):
    orch = get_trip_orchestrator()
    return await orch.resolve_confirmation(
        trip_id, chip_id, body.decision, body.corrected_value)


@trips_router.post("/{trip_id}/plan")
async def trips_plan(trip_id: str):
    orch = get_trip_orchestrator()
    trip = orch._trip_or_404(trip_id)

    # If the trip already has a final status, just return state
    if trip.status in ("completed", "failed"):
        return JSONResponse(content=orch.state(trip_id))

    # If waiting for approval, return state with pending approvals
    if trip.status == "awaiting_approval":
        return JSONResponse(content=orch.state(trip_id))

    seed = orch._seeds.get(trip_id)
    if seed:
        clarify = trip.context.get("clarify_loop") or {}
        profile = orch.store.get_or_create(str(trip.context.get("user_id") or ""))

        # If calling /plan directly when scope clarification was pending, resolve unrequested items to not_requested
        if clarify.get("scope_clarification"):
            rs_dict = dict(seed.get("requested_services") or {})
            for k in ("hotel", "activities", "local_transport", "visa_check"):
                if rs_dict.get(k) == "unknown":
                    rs_dict[k] = "not_requested"
            seed["requested_services"] = rs_dict
            trip.context["requested_services"] = rs_dict
            if "clarify_loop" in trip.context and isinstance(trip.context["clarify_loop"], dict):
                trip.context["clarify_loop"]["scope_clarification"] = None
            clarify = trip.context.get("clarify_loop") or {}

        readiness = assess_readiness(
            goal=seed["goal"],
            profile=profile,
            requested_services=seed.get("requested_services", {}),
            clarify_data=clarify,
        )
        if not readiness.ready_for_search:
            # P0 bypass fix: Zero provider calls if not ready!
            trip.status = "clarifying" if (clarify.get("questions") or not clarify.get("complete")) else "in_progress"
            state = orch.state(trip_id)
            return JSONResponse(content={"trip_id": trip_id, "status": trip.status, "state": state})

        # Explicit search confirmation provided via /plan action
        seed["goal"]["search_confirmed"] = True
        rs = RequestedServices(**seed.get("requested_services", {"flight_search": "requested"}))
        rest = orch._build_plan_rest(seed, rs)
        trip.nodes = rest
        trip.nodes_by_name = {n.name: n for n in rest}
        trip.status = "pending"
        trip.current = None

    if trip.nodes:
        try:
            await orch._run_guarded(trip_id)
        except GraphError as exc:
            raise orch._graph_error(exc)

    state = orch.state(trip_id)

    # Enrich with plan execution outputs
    result = {
        "trip_id": trip_id,
        "status": trip.status,
        "current_node": trip.current,
        "outputs": {},
        "pending_approvals": [a.model_dump(mode="json")
                              for a in trip.pending_approvals],
    }
    for key in ("flight_search", "visa_check", "flight_book", "itinerary",
                "safety_check", "hotel_research", "activities_research",
                "local_transport_research", "recovery"):
        if key in trip.context:
            result["outputs"][key] = trip.context[key]
    if state.get("error"):
        result["error"] = state["error"]
    result["nodes"] = state.get("nodes", [])
    result["state"] = state
    return JSONResponse(content=result)


@trips_router.post("/{trip_id}/itinerary/sections/{section_id}/replace")
async def trips_itinerary_replace_section(
        trip_id: str, section_id: str, body: ItineraryReplacementRequest):
    orch = get_trip_orchestrator()
    trip = orch._trip_or_404(trip_id)
    
    itin = trip.context.get("itinerary") or {}
    items = itin.get("items") or []
    
    result = ItinerarySkill.replace_section(
        items, section_id, body,
        timezone_name=itin.get("timezone") or "Asia/Singapore")
    if "error" in result:
        # e.g. unknown_section, booked_flight_rejected, validation_error
        code = 404 if result["error"] == "unknown_section" else 422
        raise TripApiError(code, result["error"], result.get("message", "Cannot replace section"), recoverable=True)
    
    # Store the complete recomputed contract, not only the changed card.
    for key in ("items", "count", "timezone", "budget", "validation"):
        itin[key] = result[key]
    trip.context["itinerary"] = itin
    
    return {
        "trip_id": trip_id,
        "section_id": section_id,
        "replaced": result["replaced"],
        "overlaps": result["validation"]["overlaps"],
        "itinerary": itin,
        "state": orch.state(trip_id)
    }

@trips_router.post("/{trip_id}/simulate-disruption")
async def trips_simulate_disruption_post(trip_id: str,
                                         body: Optional[SimulateDisruptionRequest] = None,
                                         allow_sim: str = "1"):
    orch = get_trip_orchestrator()
    trip = orch._trip_or_404(trip_id)
    booking = trip.context.get("flight_book") or {}
    option = (booking.get("booking") or {}).get("option") or {}
    event = {
        "flight_number": (body.flight_number if body else None) or option.get("flight_no") or "SIM-FLIGHT",
        "status": "DISRUPTED_SIMULATED",
        "simulated": True,
        "scenario": (body.scenario if body else None) or "cancellation",
        "reason": (body.reason if body else None) or "G3 demo hook (simulate-disruption)",
    }
    try:
        return await orch.simulate_disruption(trip_id, event)
    except GraphError as exc:
        raise orch._graph_error(exc)


@trips_router.get("/{trip_id}/simulate-disruption")
async def trips_simulate_disruption_get(trip_id: str, allow_sim: str = "1"):
    return await trip_simulate_disruption(trip_id, allow_sim=allow_sim)


@trips_router.get("/{trip_id}/stream")
async def trips_stream(trip_id: str):
    return await trip_stream(trip_id)
