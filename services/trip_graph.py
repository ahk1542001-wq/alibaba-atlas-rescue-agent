"""TripGraph — generic NodeSpec executor (MASTER_BUILD_PACKAGE §3.1, §14.2).

Generic contract: NodeSpec{name, skill_ref, input_schema, output_schema,
edges:[{when,to}], gate}. Lifecycle hooks implemented inside the executor
(no separate hook engine, §14.2):

- PRE_NODE_VALIDATE — pydantic input check before skill.run(); failure
  records the node FAILED with a recoverable error and stops the trip.
- POST_NODE_RECORD — every execution appends a GraphNodeStateV2
  (skill_ref, latency_ms, citations); unconditional.
- GATE_PAUSE — gate nodes suspend the trip, expose pending ApprovalRequests,
  and resume on resolve_approval(); concurrent resolutions are serialized
  per trip (single winner).
- ON_DISRUPTION_EVENT — on_disruption() mounts the frozen
  DisruptionRecoveryDAG (services/state_graph.py, imported — never modified)
  as a subgraph and appends its trace to the trip.

CONDITIONAL MOUNTING (owner correction B): the planner mounts ONLY services
whose scope is requested in TripIntent.requested_services, plus the
mandatory safety dependency — visa check is always mounted when
flight_booking is requested for an international (cross-border) route.
Deterministic replay: same inputs + approvals -> identical trace modulo
volatile fields (latency/timestamps) via mask_volatile().
"""

import asyncio
import time
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Type

from pydantic import BaseModel, ConfigDict

from models.schemas import (
    ApprovalRequest,
    ConfirmationChip,
    GraphNodeStateV2,
    RequestedServices,
    ScopeClarificationRequest,
    TripIntent,
)
from services.rights_engine import airports_to_countries
from services.skills.base import SkillError
from services.state_graph import DisruptionRecoveryDAG

# --- errors ---------------------------------------------------------------------


class GraphError(Exception):
    """Structured executor failure."""

    def __init__(self, code: str, message: str, recoverable: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.recoverable = recoverable


class GraphValidationError(GraphError):
    def __init__(self, message: str) -> None:
        super().__init__("validation_error", message, recoverable=True)


class GraphCapabilityViolation(GraphError):
    def __init__(self, message: str) -> None:
        super().__init__("capability_violation", message, recoverable=False)


class GraphApprovalError(GraphError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, recoverable=True)


# --- node spec --------------------------------------------------------------------


class NodeEdge(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    when: Callable[[Dict[str, Any], Dict[str, Any]], bool]  # pure function
    to: str


class NodeSpec(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    name: str
    skill_ref: str
    input_schema: Optional[Type[BaseModel]] = None   # reserved (§3.1 contract)
    output_schema: Optional[Type[BaseModel]] = None  # reserved (§3.1 contract)
    edges: List[NodeEdge] = []
    gate: bool = False
    # param -> context path string ("a.b.c") OR pure callable(context)
    input_map: Dict[str, Any] = {}


# --- trip state ---------------------------------------------------------------------


class Trip:
    def __init__(self, trip_id: str, nodes: List[NodeSpec],
                 context: Dict[str, Any]) -> None:
        self.trip_id = trip_id
        self.nodes = list(nodes)
        self.nodes_by_name = {n.name: n for n in nodes}
        self.context: Dict[str, Any] = dict(context)
        self.trace: List[GraphNodeStateV2] = []
        self.pending_approvals: List[ApprovalRequest] = []
        self.confirmation_chips: Dict[str, ConfirmationChip] = {}
        self.status = "pending"  # pending|running|awaiting_approval|completed|failed
        self.current: Optional[str] = None
        self.lock = asyncio.Lock()
        self.confirmation_lock = asyncio.Lock()


# --- helpers ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lookup(context: Dict[str, Any], path: str) -> Any:
    cur: Any = context
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def resolve_input(input_map: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for key, spec in (input_map or {}).items():
        payload[key] = spec(context) if callable(spec) else _lookup(context, spec)
    return payload


def mask_volatile(trace: List[GraphNodeStateV2]) -> List[Dict[str, Any]]:
    """Deterministic-replay comparison form: drop latency/timestamp fields."""
    out = []
    for rec in trace:
        dumped = rec.model_dump(mode="json")
        dumped.pop("latency_ms", None)
        dumped.pop("timestamp", None)
        out.append(dumped)
    return out


# --- executor -----------------------------------------------------------------------------


class TripGraphExecutor:
    """In-memory trip registry keyed by trip_id with cross-trip isolation.

    Security default (G2-DA fix): capability enforcement FAILS CLOSED when a
    skill_ref has no manifest entry — test harnesses and embedded helpers
    must opt in explicitly via allow_unmanifested_skills=True.
    """

    def __init__(self, registry: Optional[List[Dict[str, Any]]] = None,
                 allow_unmanifested_skills: bool = False) -> None:
        if registry is None:
            from services.skills import load_skill_registry
            registry = load_skill_registry()
        self._registry_by_name = {entry["name"]: entry for entry in registry}
        self._allow_unmanifested_skills = allow_unmanifested_skills
        self._skills: Dict[str, Any] = {}
        self._trips: Dict[str, Trip] = {}

    # -- registry / skills -----------------------------------------------------

    def register_skill(self, name: str, skill: Any) -> None:
        self._skills[name] = skill

    # -- trip lifecycle ----------------------------------------------------------

    def start_trip(self, trip_id: str, nodes: List[NodeSpec],
                   context: Dict[str, Any]) -> Trip:
        if trip_id in self._trips:
            raise ValueError(f"trip '{trip_id}' already exists (replay must use a "
                             "fresh trip_id; cross-trip state is isolated)")
        ctx = dict(context)
        ctx.setdefault("trip_id", trip_id)
        trip = Trip(trip_id, nodes, ctx)
        self._trips[trip_id] = trip
        return trip

    def get(self, trip_id: str) -> Trip:
        return self._trips[trip_id]  # KeyError surfaces unknown trips honestly

    def telemetry(self, trip_id: str) -> Dict[str, Any]:
        trip = self.get(trip_id)
        return {
            "trip_id": trip_id,
            "status": trip.status,
            "current_state": trip.current,
            "total_latency_ms": round(sum(n.latency_ms for n in trip.trace), 2),
            "nodes": [n.model_dump(mode="json") for n in trip.trace],
            "pending_approvals": [a.model_dump(mode="json")
                                  for a in trip.pending_approvals],
        }

    # -- execution -----------------------------------------------------------------

    async def run(self, trip_id: str) -> str:
        trip = self.get(trip_id)
        async with trip.lock:
            # --- status guards (G2-DA fix): never re-enter a live trip -------
            if trip.status == "awaiting_approval":
                raise GraphApprovalError(
                    "pending_approval",
                    f"trip '{trip_id}' is awaiting approval; resolve the "
                    "pending approval via resolve_approval() / "
                    "POST /api/trip/{id}/approvals — re-running would "
                    "duplicate approvals and re-execute the graph")
            if trip.status in ("completed", "failed"):
                raise GraphError(
                    "trip_terminal",
                    f"trip '{trip_id}' already reached terminal status "
                    f"'{trip.status}'; re-running would re-fire side effects "
                    "— start a fresh trip_id instead", recoverable=False)
            entry = trip.nodes[0].name if trip.nodes else None
            try:
                await self._advance(trip, entry)
            except Exception as exc:  # noqa: BLE001 — record, then re-raise
                self._record_unexpected_failure(trip, exc)
                raise
            return trip.status

    def _record_unexpected_failure(self, trip: Trip, exc: Exception) -> None:
        """Any non-SkillError escape leaves a FAILED record + failed status
        (G2-DA fix) instead of a trip stuck at 'running'. Paths that already
        recorded a FAILED node (capability violation, non-recoverable
        SkillError) are left untouched."""
        if trip.status == "failed":
            return
        spec = trip.nodes_by_name.get(trip.current) if trip.current else None
        if spec is not None:
            self._record(trip, spec, "FAILED", 0.0, {
                "error_code": "internal_error",
                "message": f"{type(exc).__name__}: {exc}"[:400],
                "recoverable": False,
            })
        trip.status = "failed"

    async def _advance(self, trip: Trip, name: Optional[str]) -> None:
        while name:
            spec = trip.nodes_by_name.get(name)
            if spec is None:
                raise GraphError("unknown_node",
                                 f"edge points to unknown node '{name}'",
                                 recoverable=False)
            trip.current = name
            trip.status = "running"
            outcome = await self._execute_node(trip, spec)
            if outcome in ("paused", "failed"):
                return
            output = trip.context.get(name)
            name = self._next_name(spec, output, trip.context)
        trip.status = "completed"
        trip.current = None

    @staticmethod
    def _next_name(spec: NodeSpec, output: Any,
                   context: Dict[str, Any]) -> Optional[str]:
        """Pure conditional edges decide the successor; no edge (or no match)
        terminates the walk. Linear chains are expressed as always-true edges
        (the planner generates them for intent-driven flows)."""
        for edge in spec.edges:
            if edge.when(output or {}, context):
                return edge.to
        return None

    def _record(self, trip: Trip, spec: NodeSpec, status: str, latency_ms: float,
                details: Dict[str, Any]) -> GraphNodeStateV2:
        rec = GraphNodeStateV2(
            node_id=f"node_{len(trip.trace) + 1:03d}",  # sequence -> replay-stable
            name=spec.name,
            status=status,
            latency_ms=round(latency_ms, 2),
            timestamp=_now_iso(),
            details=details,
            skill_ref=spec.skill_ref,
            citations=[],
        )
        trip.trace.append(rec)
        return rec

    def _enforce_capabilities(self, trip: Trip, spec: NodeSpec, skill: Any) -> None:
        """Manifest (SKILL.md) is the source of truth for granted flags; a
        class declaring more than its manifest allows is refused (§14.4).

        FAIL CLOSED (G2-DA fix): a skill_ref with NO manifest entry is
        refused with capability_violation unless the executor was built with
        the explicit allow_unmanifested_skills opt-in (default False).
        """
        declared = set(getattr(skill, "capabilities", frozenset()))
        entry = self._registry_by_name.get(spec.skill_ref)
        if entry is None:
            if self._allow_unmanifested_skills:
                return  # explicit opt-in (test harnesses / embedded helpers)
            self._record(trip, spec, "FAILED", 0.0, {
                "error_code": "capability_violation",
                "message": f"skill '{spec.skill_ref}' has no manifest entry; "
                           "executor fails closed (allow_unmanifested_skills "
                           "opt-in required)",
                "recoverable": False,
            })
            trip.status = "failed"
            raise GraphCapabilityViolation(
                f"skill '{spec.skill_ref}' has no manifest entry — "
                "execution refused (fail-closed)")
        allowed = set(entry.get("allowed_tools", []))
        exceeding = declared - allowed
        if exceeding:
            self._record(trip, spec, "FAILED", 0.0, {
                "error_code": "capability_violation",
                "message": f"skill '{spec.skill_ref}' declares capabilities "
                           f"{sorted(exceeding)} not granted by its manifest "
                           f"{sorted(allowed)}",
                "recoverable": False,
            })
            trip.status = "failed"
            raise GraphCapabilityViolation(
                f"skill '{spec.skill_ref}' exceeds declared capabilities: "
                f"{sorted(exceeding)}")

    async def _execute_node(self, trip: Trip, spec: NodeSpec) -> str:
        # ---- GATE_PAUSE: suspend before any irreversible/expensive action ----
        if spec.gate:
            options = _lookup(
                trip.context, spec.input_map.get("options", "")) or []
            initial_booking = spec.name == "approve_booking"
            approval = ApprovalRequest(
                approval_id=f"{trip.trip_id}:{len(trip.trace) + 1:03d}",
                node_name=spec.name,
                options=deepcopy(options),
                created_at=_now_iso(),
                trip_id=trip.trip_id,
                purpose="initial_booking" if initial_booking else None,
                immutable_option={"options": deepcopy(options)}
                if initial_booking else None,
                price_snapshot={
                    "options": [
                        {"id": option.get("id"),
                         "price": deepcopy(option.get("price"))}
                        for option in options if isinstance(option, dict)
                    ]
                } if initial_booking else None,
                expires_at=(datetime.now(timezone.utc) + timedelta(minutes=30))
                .isoformat() if initial_booking else None,
            )
            trip.pending_approvals.append(approval)
            trip.status = "awaiting_approval"
            trip.current = spec.name
            self._record(trip, spec, "PAUSED", 0.0,
                         {"approval_id": approval.approval_id})
            return "paused"

        skill = self._skills.get(spec.skill_ref)
        if skill is None:
            self._record(trip, spec, "FAILED", 0.0, {
                "error_code": "skill_not_registered",
                "message": f"no skill registered for '{spec.skill_ref}'",
                "recoverable": False,
            })
            trip.status = "failed"
            raise GraphError("skill_not_registered",
                             f"no skill registered for '{spec.skill_ref}'",
                             recoverable=False)

        self._enforce_capabilities(trip, spec, skill)

        # ---- PRE_NODE_VALIDATE ------------------------------------------------
        payload = resolve_input(spec.input_map, trip.context)
        model = spec.input_schema or getattr(skill, "input_model", None)
        if model is not None:
            try:
                payload = model(**payload).model_dump(mode="json")
            except Exception as exc:  # noqa: BLE001 — boundary validation
                self._record(trip, spec, "FAILED", 0.0, {
                    "error_code": "validation_error",
                    "message": str(exc)[:400],
                    "recoverable": True,
                })
                trip.status = "failed"
                return "failed"

        # ---- skill run + POST_NODE_RECORD --------------------------------------
        started = time.perf_counter()
        try:
            output = await skill.run(payload, trip.context)
        except SkillError as exc:
            latency = (time.perf_counter() - started) * 1000
            err_details = {
                "error_code": exc.code,
                "message": exc.message,
                "recoverable": exc.recoverable,
            }
            if hasattr(exc, "details") and isinstance(exc.details, dict):
                err_details.update(exc.details)
            self._record(trip, spec, "FAILED", latency, err_details)
            trip.status = "failed"
            if exc.recoverable:
                return "failed"
            raise
        latency = (time.perf_counter() - started) * 1000
        trip.context[spec.name] = output
        details = {"citations": len((output or {}).get("citations", []) or [])} \
            if isinstance(output, dict) else {}
        self._record(trip, spec, "COMPLETED", latency, details)
        return "ok"

    # ---- approval resolution ------------------------------------------------------

    async def resolve_approval(self, trip_id: str, approval_id: str,
                               value: Any) -> str:
        trip = self.get(trip_id)
        async with trip.lock:
            if trip.status != "awaiting_approval":
                raise GraphApprovalError(
                    "already_resolved",
                    f"trip '{trip_id}' is not awaiting approval "
                    f"(status={trip.status})")
            request = next((a for a in trip.pending_approvals
                            if a.approval_id == approval_id), None)
            if request is None:
                raise GraphApprovalError(
                    "unknown_approval",
                    f"approval '{approval_id}' not found for trip '{trip_id}'")
            # --- expiry gate (G2-DA fix): expired approvals never resume -----
            if request.expires_at:
                try:
                    expiry = datetime.fromisoformat(request.expires_at)
                except ValueError:
                    expiry = None
                if expiry is not None:
                    if expiry.tzinfo is None:
                        expiry = expiry.replace(tzinfo=timezone.utc)
                    if datetime.now(timezone.utc) >= expiry:
                        raise GraphApprovalError(
                            "approval_expired",
                            f"approval '{approval_id}' expired at "
                            f"{request.expires_at}; request a fresh approval")
            request.resolved_value = value
            trip.pending_approvals.remove(request)
            spec = trip.nodes_by_name[request.node_name]
            output = {"approval": value}
            trip.context[spec.name] = output
            self._record(trip, spec, "COMPLETED", 0.0,
                         {"approval_id": approval_id, "resolved_value": value})
            trip.status = "running"
            try:
                await self._advance(trip, self._next_name(spec, output,
                                                          trip.context))
            except Exception as exc:  # noqa: BLE001 — record, then re-raise
                self._record_unexpected_failure(trip, exc)
                raise
            return trip.status

    # ---- ON_DISRUPTION_EVENT --------------------------------------------------------

    async def on_disruption(self, trip_id: str,
                            event: Dict[str, Any]) -> Dict[str, Any]:
        """Mount the frozen DisruptionRecoveryDAG as a subgraph (import-only)."""
        trip = self.get(trip_id)
        async with trip.lock:
            dag = DisruptionRecoveryDAG(session_id=f"recovery_{trip_id}")
            dag.record_step("IngestionRadar", 0.5, {"event": event})
            for node_name in DisruptionRecoveryDAG.NODES[1:]:
                dag.record_step(node_name, 0.5, {"mounted_by": "trip_graph"})
            telemetry = dag.get_graph_telemetry()
            self._record(trip, NodeSpec(name="RecoverySubgraph",
                                        skill_ref="recovery_subgraph"),
                         "COMPLETED", telemetry["total_dag_latency_ms"],
                         {"subgraph": telemetry, "event": event})
            return telemetry


# --- planner: intent-first conditional mounting (owner correction B) -------------------

SCOPE_CHOICES = ("flight_only", "flight_plus_booking", "complete_trip")

# visa_check is excluded: it is a safety dependency, not a user-facing scope choice
_SCOPE_CLARIFY_SERVICES = ("flight_search", "flight_booking", "hotel",
                           "activities", "local_transport")


def resolve_scope_choice(requested: RequestedServices,
                         choice: str) -> RequestedServices:
    """Map one of the exactly-three clarification choices onto service scopes."""
    if choice == "flight_only":
        updates = dict(flight_search="requested", flight_booking="not_requested",
                       visa_check="not_requested", hotel="not_requested",
                       activities="not_requested", local_transport="not_requested")
    elif choice == "flight_plus_booking":
        updates = dict(flight_search="requested", flight_booking="requested",
                       visa_check="not_requested", hotel="not_requested",
                       activities="not_requested", local_transport="not_requested")
    elif choice == "complete_trip":
        updates = dict(flight_search="requested", flight_booking="requested",
                       visa_check="requested", hotel="requested",
                       activities="requested", local_transport="requested")
    else:
        raise ValueError(f"unknown scope choice '{choice}'; expected one of "
                         f"{SCOPE_CHOICES}")
    return RequestedServices(**{**requested.model_dump(), **updates})


def is_international(origin: Optional[str], destination: Optional[str]) -> bool:
    if not origin or not destination:
        return False
    o, d, _ = airports_to_countries(origin, destination)
    return bool(o and d and o != d)


@dataclass
class Plan:
    nodes: List[NodeSpec] = field(default_factory=list)
    scope_clarification: Optional[ScopeClarificationRequest] = None


def _selected_option(ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    approval = (ctx.get("approve_booking") or {}).get("approval") or {}
    option_id = approval.get("option_id")
    for option in (ctx.get("flight_search") or {}).get("options", []):
        if option.get("id") == option_id:
            return option
    return None


def _route_from_goal(ctx: Dict[str, Any]) -> List[str]:
    goal = (ctx.get("goal_intake") or {}).get("goal") or {}
    return [c for c in (goal.get("origin_city"), goal.get("dest_city")) if c]


def _requested_leisure_domains(ctx: Dict[str, Any]) -> List[str]:
    requested = ctx.get("requested_services") or {}
    return [domain for domain in ("hotel", "activities", "local_transport")
            if requested.get(domain) == "requested"
            or f"{domain}_research" in ctx]


def plan_trip(intent: TripIntent) -> Plan:
    """Build the node list for one trip strictly from requested_services."""
    rs = intent.requested_services
    if not intent.scope_clarified and any(
            getattr(rs, f) == "unknown" for f in _SCOPE_CLARIFY_SERVICES):
        return Plan(nodes=[], scope_clarification=ScopeClarificationRequest(
            prompt="How far should the agent go for this trip?",
            choices=list(SCOPE_CHOICES)))

    goal = intent.goal
    international = is_international(goal.origin_city, goal.dest_city)
    booking = rs.flight_booking == "requested"
    nodes: List[NodeSpec] = [
        NodeSpec(name="goal_intake", skill_ref="goal_intake",
                 input_map={"free_text": "raw_text"}),
        NodeSpec(name="clarify_loop", skill_ref="clarify_loop", input_map={
            "goal": "goal_intake.goal",
            "user_id": "user_id",
            "requested_services": "goal_intake.requested_services",
        }),
    ]

    if rs.flight_search != "requested":
        return Plan(nodes=_with_linear_continuation(nodes))  # nothing beyond

    nodes.append(NodeSpec(name="flight_search", skill_ref="flight_search",
                          input_map={
                              "origin": "goal_intake.goal.origin_city",
                              "destination": "goal_intake.goal.dest_city",
                              "date": "goal_intake.goal.date_window.start",
                              "passengers": "goal_intake.goal.passengers",
                          }))
    if not booking:
        # flight-only intent: stop after options (no hotel/activities/transport)
        return Plan(nodes=_with_linear_continuation(nodes))

    # mandatory safety dep: cross-border booking ALWAYS gets a visa check,
    # even when the user did not request one (owner correction B/C)
    if rs.visa_check == "requested" or international:
        nodes.append(NodeSpec(name="visa_check", skill_ref="visa_check",
                              input_map={
                                  "passport_country": "profile.passport_country",
                                  "route": _route_from_goal,
                              },
                              edges=[
                                  # §3.1 replan edge: a baseline BLOCKED_RISK
                                  # (visa_blocked) reroutes back to
                                  # flight_search — a blocked route can never
                                  # reach the approval gate or booking
                                  NodeEdge(when=lambda out, ctx: bool(
                                      (out or {}).get("visa_blocked")),
                                      to="flight_search"),
                              ]))

    for domain in ("hotel", "activities", "local_transport"):
        if getattr(rs, domain) == "requested":
            nodes.append(NodeSpec(name=f"{domain}_research",
                                  skill_ref=f"{domain}_research",
                                  input_map={
                                      "domain": lambda ctx, d=domain: d,
                                      "destination": "goal_intake.goal.dest_city",
                                      "date_window": "goal_intake.goal.date_window",
                                  }))

    # itinerary only when leisure research exists: a flight-only booking
    # already owns its flight record; mounting an unrequested assembler
    # would violate intent-first routing (owner correction B)
    if any(getattr(rs, d) == "requested" for d in
           ("hotel", "activities", "local_transport")):
        nodes.append(NodeSpec(name="itinerary", skill_ref="itinerary",
                              input_map={
                                  "booking": lambda ctx: (ctx.get("flight_book") or {}).get("booking"),
                                  "options": "flight_search.options",
                                  "requested_domains": _requested_leisure_domains,
                              }))

    nodes.append(NodeSpec(
        name="approve_booking", skill_ref="approval_gate", gate=True,
        input_map={"options": "flight_search.options"},
        edges=[NodeEdge(
            when=lambda out, ctx: bool((out.get("approval") or {}).get("approved")),
            to="flight_book")],
    ))
    nodes.append(NodeSpec(name="flight_book", skill_ref="flight_book", input_map={
        "option_id": "approve_booking.approval.option_id",
        "origin": "goal_intake.goal.origin_city",
        "destination": "goal_intake.goal.dest_city",
        "passport_country": "profile.passport_country",
        "passenger": "profile",
        "option": _selected_option,
        "confirmed_price_snapshot": "_confirmed_price_snapshot",
    }))
    nodes.append(NodeSpec(name="disruption_monitor", skill_ref="disruption_monitor",
                          input_map={
                              "pnr": "flight_book.pnr",
                              "trip_id": "trip_id",
                              "flight_ids": lambda ctx: [
                                  ((ctx.get("flight_book") or {}).get("booking") or {})
                                  .get("option", {}).get("flight_no")]
                          }))
    return Plan(nodes=_with_linear_continuation(nodes))


def _with_linear_continuation(nodes: List[NodeSpec]) -> List[NodeSpec]:
    """Give edge-less interior nodes an always-true edge to their successor.

    Nodes that already carry conditional edges without an unconditional fallback
    (such as visa_check with a replan edge) receive a fallback edge to their
    successor. Gate nodes (e.g. approve_booking) only branch on approval.
    """
    for i, node in enumerate(nodes[:-1]):
        if not node.edges:
            node.edges = [NodeEdge(when=lambda out, ctx: True,
                                   to=nodes[i + 1].name)]
        elif node.name == "visa_check":
            node.edges.append(NodeEdge(when=lambda out, ctx: True,
                                       to=nodes[i + 1].name))
    return nodes
