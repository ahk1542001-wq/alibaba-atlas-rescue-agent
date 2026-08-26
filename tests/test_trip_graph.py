"""G2 behavior tests for services/trip_graph.py — the generic NodeSpec executor.

Covers §3.1/§14.2: sequencing + pure conditional edges, CONDITIONAL MOUNTING
driven by TripIntent.requested_services (incl. the mandatory visa safety dep
for international bookings), PRE_NODE_VALIDATE failure path, GATE_PAUSE
pause/resume (incl. concurrent resolutions), POST_NODE_RECORD with
GraphNodeStateV2 + latency, ON_DISRUPTION_EVENT mounting the frozen
DisruptionRecoveryDAG, capability-flag enforcement, deterministic replay,
and cross-trip isolation. All skills here are fakes — real skill behavior
lives in tests/test_skills_behavior.py.
"""

import asyncio

import pytest
from pydantic import BaseModel

from models.schemas import RequestedServices, TripGoal, TripIntent
from services.skills.base import SkillBase
from services.trip_graph import (
    GraphApprovalError,
    GraphCapabilityViolation,
    GraphError,
    NodeSpec,
    TripGraphExecutor,
    mask_volatile,
    plan_trip,
    resolve_scope_choice,
)


def _run(coro):
    return asyncio.run(coro)


# --- fakes --------------------------------------------------------------------

class EchoSkill(SkillBase):
    name = "echo"
    when_to_use = "test fake"
    capabilities = frozenset()

    def __init__(self, out=None):
        self.out = out or {}

    async def run(self, payload, context=None):
        return {"echoed": {**self.out, **payload}}


class StrictInput(BaseModel):
    count: int


class StrictSkill(SkillBase):
    name = "strict"
    when_to_use = "test fake with strict input schema"
    input_model = StrictInput
    capabilities = frozenset()

    async def run(self, payload, context=None):
        return {"count": payload["count"]}


class LLMDeclaredSkill(SkillBase):
    """Declares llm_call; paired with a registry entry lacking it -> violation."""
    name = "overprivileged"
    when_to_use = "test fake for capability enforcement"
    capabilities = frozenset({"llm_call"})

    async def run(self, payload, context=None):
        return {"ran": True}


def _executor(registry=None):
    # allow_unmanifested_skills=True: test fakes ship without SKILL.md
    # manifests; the production default stays FAIL-CLOSED (G2-DA fix 4)
    ex = TripGraphExecutor(registry=registry or [],
                           allow_unmanifested_skills=True)
    ex.register_skill("echo", EchoSkill({"ok": True}))
    ex.register_skill("strict", StrictSkill())
    ex.register_skill("overprivileged", LLMDeclaredSkill())
    return ex


_ALWAYS = lambda out, ctx: True  # noqa: E731 — linear continuation edge


def _nodes_linear():
    return [
        NodeSpec(name="a", skill_ref="echo", edges=[{"when": _ALWAYS, "to": "b"}]),
        NodeSpec(name="b", skill_ref="echo", edges=[{"when": _ALWAYS, "to": "c"}]),
        NodeSpec(name="c", skill_ref="echo", edges=[]),
    ]


# --- sequencing + recording -----------------------------------------------------

def test_linear_sequencing_records_every_node_as_v2():
    ex = _executor()
    ex.start_trip("t1", _nodes_linear(), context={})
    _run(ex.run("t1"))
    trace = ex.get("t1").trace
    assert [n.name for n in trace] == ["a", "b", "c"]
    assert all(n.status == "COMPLETED" for n in trace)
    assert all(n.skill_ref == "echo" for n in trace)
    assert all(n.latency_ms >= 0 for n in trace)
    assert ex.get("t1").status == "completed"


def test_conditional_edges_are_pure_functions_of_output():
    nodes = [
        NodeSpec(
            name="router",
            skill_ref="echo",
            edges=[
                {"when": lambda out, ctx: out["echoed"].get("branch") == "left", "to": "left_node"},
                {"when": lambda out, ctx: True, "to": "right_node"},
            ],
        ),
        NodeSpec(name="left_node", skill_ref="echo", edges=[]),
        NodeSpec(name="right_node", skill_ref="echo", edges=[]),
    ]
    ex = _executor()
    ex.start_trip("tL", nodes, context={"router_in": {"branch": "left"}})
    ex.get("tL").context["router_in"] = {"branch": "left"}
    # node "router" has no input_map -> payload {}; force branch via output stub
    ex.register_skill("echo", EchoSkill({"branch": "left"}))
    _run(ex.run("tL"))
    assert [n.name for n in ex.get("tL").trace] == ["router", "left_node"]

    ex2 = _executor()
    ex2.register_skill("echo", EchoSkill({"branch": "right"}))
    ex2.start_trip("tR", nodes, context={})
    _run(ex2.run("tR"))
    assert [n.name for n in ex2.get("tR").trace] == ["router", "right_node"]


def test_no_matching_edge_terminates_cleanly():
    nodes = [
        NodeSpec(name="solo", skill_ref="echo",
                 edges=[{"when": lambda out, ctx: False, "to": "nowhere"}]),
    ]
    ex = _executor()
    ex.start_trip("t", nodes, context={})
    _run(ex.run("t"))
    assert ex.get("t").status == "completed"
    assert [n.name for n in ex.get("t").trace] == ["solo"]


# --- PRE_NODE_VALIDATE ------------------------------------------------------------

def test_validation_failure_records_failed_node_and_recovers_state():
    nodes = [
        NodeSpec(name="bad", skill_ref="strict",
                 input_map={"count": "raw_count"}, edges=[]),
    ]
    ex = _executor()
    ex.start_trip("tv", nodes, context={"raw_count": "not-an-int"})
    _run(ex.run("tv"))
    trip = ex.get("tv")
    assert trip.status == "failed"
    rec = trip.trace[-1]
    assert rec.name == "bad"
    assert rec.status == "FAILED"
    assert rec.details["error_code"] == "validation_error"
    assert rec.details["recoverable"] is True


# --- GATE_PAUSE --------------------------------------------------------------------

def _gate_nodes():
    return [
        NodeSpec(name="prepare", skill_ref="echo",
                 edges=[{"when": _ALWAYS, "to": "approve"}]),
        NodeSpec(name="approve", skill_ref="approval_gate", gate=True,
                 edges=[
                     {"when": lambda out, ctx: bool(out.get("approval", {}).get("approved")),
                      "to": "commit"},
                 ]),
        NodeSpec(name="commit", skill_ref="echo", edges=[]),
    ]


def test_gate_pauses_exposes_pending_approval_then_resumes():
    ex = _executor()
    ex.start_trip("tg", _gate_nodes(), context={})
    _run(ex.run("tg"))
    trip = ex.get("tg")
    assert trip.status == "awaiting_approval"
    assert len(trip.pending_approvals) == 1
    req = trip.pending_approvals[0]
    assert req.node_name == "approve"
    assert req.approval_id and req.created_at

    _run(ex.resolve_approval("tg", req.approval_id, {"approved": True}))
    trip = ex.get("tg")
    assert trip.status == "completed"
    names = [n.name for n in trip.trace]
    assert "commit" in names
    assert trip.context["approve"]["approval"] == {"approved": True}


def test_gate_rejection_skips_downstream_action_node():
    ex = _executor()
    ex.start_trip("tg2", _gate_nodes(), context={})
    _run(ex.run("tg2"))
    req = ex.get("tg2").pending_approvals[0]
    _run(ex.resolve_approval("tg2", req.approval_id, {"approved": False}))
    trip = ex.get("tg2")
    names = [n.name for n in trip.trace]
    assert "commit" not in names
    assert trip.status == "completed"


def test_concurrent_approval_resolutions_single_winner():
    ex = _executor()
    ex.start_trip("tc", _gate_nodes(), context={})
    _run(ex.run("tc"))
    approval_id = ex.get("tc").pending_approvals[0].approval_id

    async def race():
        results = await asyncio.gather(
            ex.resolve_approval("tc", approval_id, {"approved": True}),
            ex.resolve_approval("tc", approval_id, {"approved": True}),
            ex.resolve_approval("tc", approval_id, {"approved": True}),
            return_exceptions=True,
        )
        return results

    results = _run(race())
    wins = [r for r in results if not isinstance(r, Exception)]
    losses = [r for r in results if isinstance(r, GraphApprovalError)]
    assert len(wins) == 1
    assert len(losses) == 2


def test_unknown_approval_id_rejected():
    ex = _executor()
    ex.start_trip("tx", _gate_nodes(), context={})
    _run(ex.run("tx"))
    with pytest.raises(GraphApprovalError):
        _run(ex.resolve_approval("tx", "nope", {"approved": True}))


# --- capability enforcement ---------------------------------------------------------

def test_capability_violation_refused_and_recorded():
    # registry (manifest source of truth) grants nothing; skill declares llm_call
    registry = [{"name": "overprivileged", "allowed_tools": [], "description": "x",
                 "module_path": "services.skills.overprivileged", "path": "fake"}]
    ex = TripGraphExecutor(registry=registry)
    ex.register_skill("overprivileged", LLMDeclaredSkill())
    ex.start_trip("cap", [NodeSpec(name="x", skill_ref="overprivileged", edges=[])],
                  context={})
    with pytest.raises(GraphCapabilityViolation):
        _run(ex.run("cap"))
    rec = ex.get("cap").trace[-1]
    assert rec.status == "FAILED"
    assert rec.details["error_code"] == "capability_violation"


# --- deterministic replay ------------------------------------------------------------

def test_replay_is_deterministic_modulo_volatile_fields():
    def build():
        ex = _executor()
        ex.start_trip("r", _nodes_linear(), context={"seed": 7})
        _run(ex.run("r"))
        return ex.get("r").trace

    assert mask_volatile(build()) == mask_volatile(build())


# --- cross-trip isolation ---------------------------------------------------------------

def test_cross_trip_context_isolation():
    ex = _executor()
    ex.start_trip("A", _nodes_linear(), context={"secret": "alpha"})
    ex.start_trip("B", _nodes_linear(), context={})
    _run(ex.run("A"))
    _run(ex.run("B"))
    assert ex.get("A").context["secret"] == "alpha"
    assert "secret" not in ex.get("B").context
    assert [n.name for n in ex.get("B").trace] == ["a", "b", "c"]


def test_unknown_trip_id_raises_keyerror():
    ex = _executor()
    with pytest.raises(KeyError):
        ex.get("ghost")
    with pytest.raises(KeyError):
        _run(ex.run("ghost"))


# --- ON_DISRUPTION_EVENT ------------------------------------------------------------------

def test_disruption_event_mounts_recovery_subgraph_and_appends_trace():
    ex = _executor()
    ex.start_trip("d1", _nodes_linear(), context={})
    _run(ex.run("d1"))
    before = len(ex.get("d1").trace)
    _run(ex.on_disruption("d1", {"flight_number": "TG303", "status": "CANCELLED"}))
    trip = ex.get("d1")
    assert len(trip.trace) == before + 1
    rec = trip.trace[-1]
    assert rec.name == "RecoverySubgraph"
    assert rec.skill_ref == "recovery_subgraph"
    sub_nodes = [s["name"] for s in rec.details["subgraph"]["nodes"]]
    assert sub_nodes[0] == "IngestionRadar"
    assert sub_nodes[-1] == "ClosedLoopVerified"
    assert rec.details["event"]["flight_number"] == "TG303"


# --- planner: intent-first mounting --------------------------------------------------------

def _goal(origin="BKK", dest="SIN"):
    return TripGoal(
        goal_id="g1", raw_text="BKK to SIN", origin_city=origin, dest_city=dest,
        date_window={"start": "2026-09-28", "end": "2026-09-30"}, passengers=1,
    )


def _intent(**scopes):
    rs = RequestedServices(**scopes)
    return TripIntent(intent_id="i1", raw_text="plan my trip",
                      goal=_goal(), requested_services=rs, scope_clarified=True)


def test_unknown_scope_emits_three_choice_clarification_and_no_nodes():
    intent = TripIntent(intent_id="i", raw_text="I need Singapore",
                        goal=_goal(), requested_services=RequestedServices())
    plan = plan_trip(intent)
    assert plan.nodes == []
    assert plan.scope_clarification is not None
    assert plan.scope_clarification.choices == ["flight_only", "flight_plus_booking",
                                                "complete_trip"]


def test_flight_only_mounts_no_hotel_activities_or_transport_research():
    plan = plan_trip(_intent(flight_search="requested", flight_booking="not_requested",
                             visa_check="not_requested", hotel="not_requested",
                             activities="not_requested", local_transport="not_requested"))
    names = [n.name for n in plan.nodes]
    assert "flight_search" in names
    assert not {"hotel_research", "activities_research",
                "local_transport_research", "flight_book"} & set(names)


def test_complete_trip_mounts_researchers_and_booking_chain():
    plan = plan_trip(_intent(flight_search="requested", flight_booking="requested",
                             visa_check="requested", hotel="requested",
                             activities="requested", local_transport="requested"))
    names = [n.name for n in plan.nodes]
    for expected in ("flight_search", "visa_check", "approve_booking", "flight_book",
                     "hotel_research", "activities_research", "local_transport_research",
                     "itinerary", "disruption_monitor"):
        assert expected in names, expected
    gate = next(n for n in plan.nodes if n.name == "approve_booking")
    assert gate.gate is True


def test_international_booking_mounts_visa_even_when_not_requested():
    plan = plan_trip(_intent(flight_search="requested", flight_booking="requested",
                             visa_check="not_requested", hotel="not_requested",
                             activities="not_requested", local_transport="not_requested"))
    names = [n.name for n in plan.nodes]
    assert "visa_check" in names  # mandatory safety dep: BKK->SIN is cross-border


def test_domestic_booking_does_not_force_visa():
    intent = _intent(flight_search="requested", flight_booking="requested",
                     visa_check="not_requested", hotel="not_requested",
                     activities="not_requested", local_transport="not_requested")
    intent.goal.origin_city = "DMK"
    intent.goal.dest_city = "BKK"  # both TH
    plan = plan_trip(intent)
    assert "visa_check" not in [n.name for n in plan.nodes]


def test_resolve_scope_choice_maps_all_three_options():
    base = RequestedServices()
    only = resolve_scope_choice(base, "flight_only")
    assert (only.flight_search, only.flight_booking, only.hotel) == \
        ("requested", "not_requested", "not_requested")
    plus = resolve_scope_choice(base, "flight_plus_booking")
    assert (plus.flight_search, plus.flight_booking) == ("requested", "requested")
    full = resolve_scope_choice(base, "complete_trip")
    assert all(getattr(full, f) == "requested" for f in
               ("flight_search", "flight_booking", "visa_check",
                "hotel", "activities", "local_transport"))
    with pytest.raises(ValueError):
        resolve_scope_choice(base, "luxury_yacht_package")


# --- G2-DA remediation: run() status guards (finding 3) -------------------------

def test_rerun_of_awaiting_approval_trip_is_refused():
    """Re-running a paused trip must not duplicate approvals or re-execute."""
    ex = _executor()
    ex.start_trip("tg-rerun", _gate_nodes(), context={})
    _run(ex.run("tg-rerun"))
    trip = ex.get("tg-rerun")
    assert trip.status == "awaiting_approval"
    before_approvals = len(trip.pending_approvals)
    before_trace = len(trip.trace)
    with pytest.raises(GraphApprovalError) as ei:
        _run(ex.run("tg-rerun"))
    assert ei.value.recoverable is True
    trip = ex.get("tg-rerun")
    assert trip.status == "awaiting_approval"       # still paused, untouched
    assert len(trip.pending_approvals) == before_approvals  # no duplicate approval
    assert len(trip.trace) == before_trace          # graph not re-executed


def test_rerun_of_completed_trip_is_refused_non_recoverable():
    ex = _executor()
    ex.start_trip("tdone", _nodes_linear(), context={})
    _run(ex.run("tdone"))
    trace_len = len(ex.get("tdone").trace)
    with pytest.raises(GraphError) as ei:
        _run(ex.run("tdone"))
    assert ei.value.recoverable is False
    assert ex.get("tdone").status == "completed"
    assert len(ex.get("tdone").trace) == trace_len  # side effects not re-fired


def test_rerun_of_failed_trip_is_refused_non_recoverable():
    nodes = [NodeSpec(name="bad", skill_ref="strict",
                      input_map={"count": "raw_count"}, edges=[])]
    ex = _executor()
    ex.start_trip("tfail", nodes, context={"raw_count": "not-an-int"})
    _run(ex.run("tfail"))
    assert ex.get("tfail").status == "failed"
    trace_len = len(ex.get("tfail").trace)
    with pytest.raises(GraphError) as ei:
        _run(ex.run("tfail"))
    assert ei.value.recoverable is False
    assert len(ex.get("tfail").trace) == trace_len


# --- G2-DA remediation: capability check fails CLOSED (finding 4) ----------------

def test_missing_manifest_entry_fails_closed_by_default():
    """No manifest entry for skill_ref -> capability_violation, not a silent pass."""
    ex = TripGraphExecutor(registry=[])  # empty registry: nothing is manifested
    ex.register_skill("overprivileged", LLMDeclaredSkill())
    ex.start_trip("cap-closed",
                  [NodeSpec(name="x", skill_ref="overprivileged", edges=[])],
                  context={})
    with pytest.raises(GraphCapabilityViolation):
        _run(ex.run("cap-closed"))
    rec = ex.get("cap-closed").trace[-1]
    assert rec.status == "FAILED"
    assert rec.details["error_code"] == "capability_violation"
    assert ex.get("cap-closed").status == "failed"


def test_unmanifested_skill_runs_only_with_explicit_opt_in():
    ex = TripGraphExecutor(registry=[], allow_unmanifested_skills=True)
    ex.register_skill("overprivileged", LLMDeclaredSkill())
    ex.start_trip("cap-open",
                  [NodeSpec(name="x", skill_ref="overprivileged", edges=[])],
                  context={})
    _run(ex.run("cap-open"))
    assert ex.get("cap-open").status == "completed"


# --- G2-DA remediation: unexpected exceptions record FAILED (finding 8) ----------

class BoomSkill(SkillBase):
    name = "boom"
    when_to_use = "test fake that explodes with a non-SkillError"
    capabilities = frozenset()

    async def run(self, payload, context=None):
        raise RuntimeError("unexpected internal error")


def test_non_skill_error_records_failed_and_sets_failed_status():
    ex = _executor()
    ex.register_skill("boom", BoomSkill())
    ex.start_trip("tboom", [NodeSpec(name="x", skill_ref="boom", edges=[])],
                  context={})
    with pytest.raises(RuntimeError):  # original error still surfaces
        _run(ex.run("tboom"))
    trip = ex.get("tboom")
    assert trip.status == "failed"          # not stuck at "running"
    rec = trip.trace[-1]
    assert rec.name == "x"
    assert rec.status == "FAILED"
    assert rec.details["error_code"] == "internal_error"
    assert rec.details["recoverable"] is False


def test_non_skill_error_inside_resume_is_also_recorded():
    ex = _executor()
    ex.register_skill("boom", BoomSkill())
    nodes = [
        NodeSpec(name="approve", skill_ref="approval_gate", gate=True,
                 edges=[{"when": _ALWAYS, "to": "boom_node"}]),
        NodeSpec(name="boom_node", skill_ref="boom", edges=[]),
    ]
    ex.start_trip("tboom2", nodes, context={})
    _run(ex.run("tboom2"))
    req = ex.get("tboom2").pending_approvals[0]
    with pytest.raises(RuntimeError):
        _run(ex.resolve_approval("tboom2", req.approval_id, {"approved": True}))
    trip = ex.get("tboom2")
    assert trip.status == "failed"
    assert trip.trace[-1].details["error_code"] == "internal_error"


# --- G2-DA remediation: ApprovalRequest expiry (finding 10) -----------------------

def test_approval_request_expires_at_defaults_none():
    from models.schemas import ApprovalRequest
    assert "expires_at" in ApprovalRequest.model_fields
    req = ApprovalRequest(approval_id="a", node_name="n", created_at="t")
    assert req.expires_at is None  # backward compatible


def test_expired_approval_is_rejected_recoverably():
    ex = _executor()
    ex.start_trip("texp", _gate_nodes(), context={})
    _run(ex.run("texp"))
    req = ex.get("texp").pending_approvals[0]
    req.expires_at = "2026-08-25T00:00:00+00:00"  # in the past
    with pytest.raises(GraphApprovalError) as ei:
        _run(ex.resolve_approval("texp", req.approval_id, {"approved": True}))
    assert ei.value.code == "approval_expired"
    assert ei.value.recoverable is True
    trip = ex.get("texp")
    assert trip.status == "awaiting_approval"  # no downstream execution
    assert [n.name for n in trip.trace][-1] != "commit"


def test_future_expiry_and_no_expiry_both_resolve():
    ex = _executor()
    ex.start_trip("tok", _gate_nodes(), context={})
    _run(ex.run("tok"))
    req = ex.get("tok").pending_approvals[0]
    req.expires_at = "2099-01-01T00:00:00+00:00"  # far future
    _run(ex.resolve_approval("tok", req.approval_id, {"approved": True}))
    assert ex.get("tok").status == "completed"
