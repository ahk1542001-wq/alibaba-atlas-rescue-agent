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
import re
import time
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from models.schemas import (
    ApprovalRequest,
    GraphNodeStateV2,
    RequestedServices,
    TripGoal,
    TripIntent,
)
from routers.v1.profile import TripApiError, get_profile_store
from services.atlas_client import AtlasClient
from services.research_coordinator import ResearchCoordinator
from services.skills.base import SkillBase
from services.skills.clarify_loop import ClarifyLoopSkill
from services.skills.disruption_monitor import DisruptionMonitorSkill
from services.skills.flight_book import FlightBookSkill
from services.skills.flight_search import FlightSearchSkill
from services.skills.goal_intake import GoalIntakeSkill
from services.skills.itinerary import ItinerarySkill
from services.skills.visa_check import VisaCheckSkill
from services.trip_graph import (
    SCOPE_CHOICES,
    GraphError,
    TripGraphExecutor,
    plan_trip,
    resolve_scope_choice,
)
from services.web_intel_client import WebIntelClient
from services import llm as llm_service

router = APIRouter(prefix="/api/trip", tags=["Trip"])

_SCOPE_LABELS = {
    "flight_only": "Search flights only (no booking, no hotels/activities)",
    "flight_plus_booking": "Search flights and book through the Atlas Sandbox",
    "complete_trip": "Complete trip: flights, booking, hotels, activities, "
                     "local transport",
}

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
    mounted only for explicitly requested leisure domains."""

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


class TripOrchestrator:
    """Wires the frozen/G2 services onto the §6 trip API. All state lives in
    the TripGraphExecutor registry (cross-trip isolation is proven there)."""

    def __init__(self, profile_store=None, atlas=None, web_intel=None,
                 llm_chat=None) -> None:
        self.store = profile_store or get_profile_store()
        # explicit opt-in for the three runtime-registered research adapters
        # (DomainResearchSkill instances have no *.SKILL.md by design; every
        # manifested skill is still capability-checked against its manifest)
        self.executor = TripGraphExecutor(allow_unmanifested_skills=True)
        atlas_client = atlas or AtlasClient()
        self.web_intel = web_intel or WebIntelClient(
            ddg_fetcher=ddg_lite_fetch,
            tavily_api_key="", serper_api_key="")
        self.coordinator = ResearchCoordinator(atlas=atlas_client,
                                               web_intel=self.web_intel)
        ex = self.executor
        gi = GoalIntakeSkill(llm_chat=llm_chat or llm_service.chat)
        cl = ClarifyLoopSkill(self.store)
        ex.register_skill("goal_intake", gi)
        ex.register_skill("clarify_loop", cl)
        ex.register_skill("flight_search", FlightSearchSkill(atlas=atlas_client))
        ex.register_skill("visa_check", VisaCheckSkill(web_intel=self.web_intel))
        ex.register_skill("flight_book", FlightBookSkill(atlas=atlas_client))
        ex.register_skill("disruption_monitor",
                          DisruptionMonitorSkill(trip_registry=ex))
        ex.register_skill("itinerary", ItinerarySkill())
        for domain in ("hotel", "activities", "local_transport"):
            ex.register_skill(f"{domain}_research",
                              DomainResearchSkill(domain, self.coordinator))
        self.skills = {"goal_intake": gi, "clarify_loop": cl}
        # trip_id -> intent seed for scope-clarification resume
        self._seeds: Dict[str, Dict[str, Any]] = {}

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
        """Trip context view of the profile — EMPTY for new users by design;
        the demo fixture is opt-in and never auto-loaded (correction A)."""
        name_field = profile.fields.get("name")
        return {
            "passport_country": profile.identity.passport_country,
            "passport_no_masked": profile.identity.passport_no_masked,
            "home_city": profile.identity.home_city,
            "name": name_field.value if name_field else "",
        }

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

    async def start(self, goal_text: str, user_id: str) -> str:
        profile = self.store.get_or_create(user_id)  # ValueError -> router
        trip_id = f"trip_{uuid.uuid4().hex[:12]}"
        ctx = {"raw_text": goal_text, "user_id": user_id,
               "profile": self._profile_ctx(profile)}

        # stage 1 runs skill-direct so the graph mounts exactly one plan
        t0 = time.perf_counter()
        goal_out = await self.skills["goal_intake"].run(
            {"free_text": goal_text}, ctx)
        t1 = time.perf_counter()
        clarify_out = await self.skills["clarify_loop"].run(
            {"goal": goal_out["goal"], "user_id": user_id,
             "requested_services": goal_out["requested_services"]}, ctx)
        t2 = time.perf_counter()

        seed = {"raw_text": goal_text, "goal": goal_out["goal"],
                "requested_services": clarify_out["requested_services"],
                "clarify": clarify_out}
        self._seeds[trip_id] = seed

        scope = clarify_out.get("scope_clarification")
        trip = self.executor.start_trip(trip_id, [], ctx)
        trip.context["goal_intake"] = goal_out
        trip.context["clarify_loop"] = clarify_out
        self._record(trip, "goal_intake", "goal_intake", "COMPLETED",
                     (t1 - t0) * 1000, {"degraded": goal_out.get("degraded")})
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

        rs = RequestedServices(**clarify_out["requested_services"])
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
            rest = self._build_plan_rest(seed, rs)
            trip.nodes = rest
            trip.nodes_by_name = {n.name: n for n in rest}
            trip.context["requested_services"] = rs.model_dump()
            trip.status = "pending"
            trip.current = None
        if rest:
            await self._run_guarded(trip.trip_id)
        else:
            trip.status = "completed"

    async def resolve(self, trip_id: str, approval_id: str,
                      decision: str, value: Any) -> Dict[str, Any]:
        trip = self._trip_or_404(trip_id)
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
            return self.resume_result(trip_id)

        if decision not in ("approve", "reject"):
            raise TripApiError(422, "invalid_decision",
                               f"decision '{decision}' is not supported",
                               recoverable=True,
                               hint="decision must be 'approve' or 'reject'; "
                                    "booking approvals carry value.option_id")
        resolved: Dict[str, Any] = {"approved": decision == "approve"}
        if isinstance(value, dict):
            resolved.update(value)
        if decision == "approve" and "option_id" not in resolved:
            raise TripApiError(422, "missing_option",
                               "booking approval requires value.option_id",
                               recoverable=True,
                               hint="pick one of the approval option ids "
                                    "listed in GET /api/trip/{id}/approvals")
        try:
            await self.executor.resolve_approval(trip_id, approval_id, resolved)
        except GraphError as exc:
            raise self._graph_error(exc)
        return self.resume_result(trip_id)

    # -- introspection -------------------------------------------------------------

    def state(self, trip_id: str) -> Dict[str, Any]:
        trip = self._trip_or_404(trip_id)
        snapshot = self.executor.telemetry(trip_id)
        ctx = trip.context
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
        snapshot["outputs"] = outputs
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

    async def simulate_disruption(self, trip_id: str,
                                  event: Dict[str, Any]) -> Dict[str, Any]:
        trip = self._trip_or_404(trip_id)
        telemetry = await self.executor.on_disruption(trip_id, event)
        return {"mounted": True, "trip_id": trip.trip_id,
                "subgraph": telemetry, "event": event}


# --- singleton ---------------------------------------------------------------------

_orchestrator: Optional[TripOrchestrator] = None


def get_trip_orchestrator() -> TripOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = TripOrchestrator()
    return _orchestrator


def set_trip_orchestrator(orch: Optional[TripOrchestrator]) -> None:
    """Test hook: install/reset the shared orchestrator."""
    global _orchestrator
    _orchestrator = orch


# --- API ------------------------------------------------------------------------------


class TripStartRequest(BaseModel):
    goal_text: str
    user_id: str


class ApprovalDecision(BaseModel):
    decision: str
    value: Optional[Any] = None


@router.post("/start")
async def trip_start(body: TripStartRequest):
    if not body.goal_text.strip():
        raise TripApiError(422, "empty_goal",
                           "goal_text must carry the travel goal",
                           recoverable=True,
                           hint="e.g. 'plan my whole trip BKK to Singapore "
                                "Sep 28-30'")
    orch = get_trip_orchestrator()
    try:
        trip_id = await orch.start(body.goal_text, body.user_id)
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
                                body: ApprovalDecision):
    orch = get_trip_orchestrator()
    return await orch.resolve(trip_id, approval_id, body.decision, body.value)


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
    """SSE step events: node records, pending approvals, terminal status."""
    orch = get_trip_orchestrator()
    orch._trip_or_404(trip_id)

    async def event_gen():
        sent_nodes = 0
        sent_approvals = 0
        while True:
            trip = orch.executor.get(trip_id)
            for rec in trip.trace[sent_nodes:]:
                yield ("event: node\n"
                       f"data: {json.dumps(rec.model_dump(mode='json'))}\n\n")
            sent_nodes = len(trip.trace)
            for approval in trip.pending_approvals[sent_approvals:]:
                yield ("event: approval\n"
                       f"data: {json.dumps(approval.model_dump(mode='json'))}\n\n")
            sent_approvals = len(trip.pending_approvals)
            if trip.status in ("completed", "failed"):
                yield ("event: status\n"
                       f"data: {json.dumps({'status': trip.status})}\n\n")
                return
            await asyncio.sleep(0.4)

    return StreamingResponse(event_gen(), media_type="text/event-stream")
