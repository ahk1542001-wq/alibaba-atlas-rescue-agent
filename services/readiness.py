"""Authoritative Trip Readiness Policy (Gate G2 / Phase 2).

Determines whether a trip request has collected and confirmed all required
facts before invoking Atlas Sandbox search, visa intelligence, or leisure research.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from models.schemas import RequestedServices, Profile


class ReadinessAssessment(BaseModel):
    ready_for_search: bool
    ready_for_booking: bool
    missing_facts: List[str]
    is_flight_only: bool
    requires_scope_choice: bool
    requires_search_confirmation: bool


def assess_readiness(
    goal: Dict[str, Any],
    profile: Optional[Profile] = None,
    requested_services: Optional[Dict[str, Any]] = None,
    clarify_data: Optional[Dict[str, Any]] = None,
) -> ReadinessAssessment:
    """Evaluate whether all required trip facts are confirmed before running graph nodes."""
    clarify = clarify_data or {}
    rs_dict = requested_services or {}
    rs = RequestedServices(**rs_dict) if rs_dict else RequestedServices()

    missing_facts: List[str] = []

    # 1. Route facts
    if not goal.get("origin_city") and not goal.get("origin_airport"):
        missing_facts.append("origin_city")
    if not goal.get("dest_city") and not goal.get("dest_airport"):
        missing_facts.append("dest_city")
    if not goal.get("date_window") and not goal.get("travel_date"):
        missing_facts.append("date_window")

    # 2. Scope determination
    requires_scope = bool(clarify.get("scope_clarification"))
    if requires_scope:
        missing_facts.append("scope_choice")

    is_flight_only = (
        rs.flight_search == "requested"
        and rs.flight_booking == "not_requested"
        and rs.visa_check == "not_requested"
        and rs.hotel == "not_requested"
        and rs.activities == "not_requested"
        and rs.local_transport == "not_requested"
    )

    # 3. Passenger count (must be explicitly provided or confirmed for booking/complete-trip)
    if not goal.get("passengers"):
        missing_facts.append("passengers")
    elif not is_flight_only and not goal.get("passengers_explicit"):
        missing_facts.append("passengers")

    # 4. Airport ambiguity (only blocking if city could not be resolved to a default IATA)
    origin_candidates = goal.get("origin_airport_candidates") or []
    if len(origin_candidates) > 1 and not goal.get("origin_city") and not goal.get("confirmed_origin_airport"):
        missing_facts.append("confirmed_origin_airport")

    dest_candidates = goal.get("destination_airport_candidates") or []
    if len(dest_candidates) > 1 and not goal.get("dest_city") and not goal.get("confirmed_destination_airport"):
        missing_facts.append("confirmed_destination_airport")

    # 5. Passport requirements (omitted for flight-only, required for booking/complete-trip)
    passport_country = None
    if profile and profile.identity and profile.identity.passport_country:
        passport_country = profile.identity.passport_country
    if goal.get("passport_country"):
        passport_country = goal.get("passport_country")

    if not is_flight_only and not passport_country and not requires_scope:
        missing_facts.append("passport_country")

    ready_for_search = len(missing_facts) == 0
    ready_for_booking = ready_for_search and (is_flight_only or bool(passport_country))

    return ReadinessAssessment(
        ready_for_search=ready_for_search,
        ready_for_booking=ready_for_booking,
        missing_facts=missing_facts,
        is_flight_only=is_flight_only,
        requires_scope_choice=requires_scope,
        requires_search_confirmation=ready_for_search and not goal.get("search_confirmed", False),
    )
