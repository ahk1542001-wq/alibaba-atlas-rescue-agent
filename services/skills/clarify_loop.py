"""clarify_loop skill — §4 S2 / loop L1 (G2 behavior).

Owner correction (A)+(B): profiles start EMPTY, so every missing required
value becomes a question; zero redundant questions when the profile already
answers them. When any core service scope is unknown the loop emits a scope
clarification offering EXACTLY three choices: flight-only | flight + Sandbox
booking | complete trip.
"""

from typing import Any, Dict, List, Optional

from models.schemas import RequestedServices
from services.profile_store import ProfileStore
from services.skills.base import SkillBase
from services.trip_graph import (
    SCOPE_CHOICES,
    _SCOPE_CLARIFY_SERVICES,
    resolve_scope_choice,
)

_SCOPE_PROMPTS = {
    "flight_only": "Search flights only (no booking, no hotels/activities)",
    "flight_plus_booking": "Search flights and book through the Atlas Sandbox",
    "complete_trip": "Complete trip: flights, booking, hotels, activities, "
                     "local transport",
}


class ClarifyLoopSkill(SkillBase):
    name = "clarify_loop"
    when_to_use = (
        "after goal intake, when TripGoal fields are incomplete; asks only "
        "missing questions and surfaces confirmation chips for inferred facts"
    )
    capabilities = frozenset({"llm_call"})

    def __init__(self, profile_store: Optional[ProfileStore] = None) -> None:
        self._store = profile_store or ProfileStore()

    async def run(self, payload: Dict[str, Any],
                  context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        goal = payload.get("goal") or {}
        user_id = str(payload.get("user_id") or "")
        rs = RequestedServices(**(payload.get("requested_services") or {}))

        # a supplied scope choice resolves the three-way clarification
        scope_choice = payload.get("scope_choice")
        if scope_choice:
            rs = resolve_scope_choice(rs, scope_choice)

        questions: List[Dict[str, str]] = []
        # 1. Route and date facts first — never re-ask what the goal already answers
        if not goal.get("origin_city"):
            questions.append({"field": "origin_city",
                              "question": "Where does the trip start "
                                          "(city or airport code)?"})
        if not goal.get("dest_city"):
            questions.append({"field": "dest_city",
                              "question": "Where do you want to go?"})
        if not goal.get("date_window"):
            questions.append({"field": "date_window",
                              "question": "Which dates (start and end) work "
                                          "for you?"})

        # 2. Scope and identity facts
        is_flight_only = (
            rs.flight_search == "requested" and
            rs.flight_booking == "not_requested" and
            rs.visa_check == "not_requested" and
            rs.hotel == "not_requested" and
            rs.activities == "not_requested" and
            rs.local_transport == "not_requested"
        )

        # Passenger count: ask when not explicitly supplied or confirmed
        if not goal.get("passengers_explicit") and not goal.get("passengers_confirmed"):
            questions.append({"field": "passengers",
                              "question": "How many passengers are traveling?"})

        profile = self._store.get_or_create(user_id) if user_id else None
        if profile is not None:
            # Passport country: do NOT ask for flight-only; ask ONLY when booking/visa/complete-trip
            if not is_flight_only and not profile.identity.passport_country:
                questions.append({"field": "passport_country",
                                  "question": "Which country issued your "
                                              "passport? (Needed to check entry "
                                              "and transit requirements.)"})
            # Home city: do NOT ask when origin is already known
            if not goal.get("origin_city") and not profile.identity.home_city:
                questions.append({"field": "home_city",
                                  "question": "Which city do you live in?"})

        scope_clarification = None
        if any(getattr(rs, f) == "unknown" for f in _SCOPE_CLARIFY_SERVICES):
            scope_clarification = {
                "prompt": "How far should the agent go for this trip?",
                "choices": list(SCOPE_CHOICES),
                "choice_labels": _SCOPE_PROMPTS,
            }

        return {
            "questions": questions,
            "scope_clarification": scope_clarification,
            "requested_services": rs.model_dump(),
            "scope_clarified": scope_clarification is None,
            "complete": not questions and scope_clarification is None,
        }
