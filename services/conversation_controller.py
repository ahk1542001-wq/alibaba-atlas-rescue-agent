"""Pure deterministic TravelCare Conversation Controller (Gate G2).

Projects the current trip snapshot and context into exactly one beginner-friendly,
customer-facing conversation turn.

Rules:
- No external network calls, no LLM calls, no DB/profile writes.
- Deterministic and pure: same state produces the same ConversationTurn.
- Emits at most ONE active question.
- Safety and approval blockers always take priority.
- Never asks for sensitive PII (passport number, card details, legal identity).
- Preserves provider provenance (Atlas Sandbox, official safety sources, simulated demo).
"""

from typing import Any, Dict, List, Optional
from models.schemas import ConversationQuestion, ConversationAction, ConversationTurn

FORBIDDEN_PII_FIELDS = frozenset({
    "passport_number",
    "passport_num",
    "passport_expiry",
    "credit_card",
    "card_number",
    "cvv",
    "ssn",
    "national_id",
    "bank_account",
    "payment_method",
})

QUESTION_REASONS = {
    "passport_country": "Needed to check entry and transit requirements.",
    "destination": "Needed to find flights, safety advisories, and entry rules.",
    "origin": "Needed to search departing flights from your area.",
    "dates": "Needed to find available flights for your travel window.",
    "passengers": "Needed to confirm seat availability and calculate total fares.",
    "budget": "Optional, helps select accommodations and activities within your comfort range.",
}


def project_conversation_turn(
    state: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
) -> ConversationTurn:
    """Derive exactly one customer-facing ConversationTurn from the trip state."""
    ctx = context or {}
    status = state.get("status", "in_progress")
    outputs = state.get("outputs") or {}
    pending_approvals = state.get("pending_approvals") or []
    error = state.get("error") or {}

    # 1. PRIORITY: Safety blocker (do_not_travel / reconsider_travel requiring acknowledgement)
    safety_data = outputs.get("safety") or ctx.get("safety") or {}
    assessment = safety_data.get("assessment") or {}
    policy_status = assessment.get("trip_policy_status") or assessment.get("overall_status")
    if policy_status == "do_not_travel":
        why = assessment.get("why_selected") or "Official government travel advisories advise against all travel to this destination."
        return ConversationTurn(
            phase="safety_blocked",
            assistant_message=f"Safety Alert: Official government advice warns against travel to your destination. {why}",
            question=None,
            actions=[
                ConversationAction(
                    action_id="check_again",
                    label="Check safety again",
                    kind="secondary",
                ),
                ConversationAction(
                    action_id="review_alternatives",
                    label="Review safer alternatives",
                    kind="primary",
                ),
            ],
            requires_user_input=False,
            consequence="Booking is blocked while an official 'Do not travel' advisory is active.",
            provenance_label="Official Government Advisories",
            recoverable=True,
            error_code="safety_do_not_travel",
        )

    # 2. PRIORITY: Disruption Recovery Approval
    rec_approval = next((a for a in pending_approvals if a.get("node_name") in ("recovery_booking", "recovery_plan") or a.get("purpose") in ("recovery_booking", "recovery_plan")), None)
    if rec_approval:
        prompt = rec_approval.get("prompt") or "A disruption has been detected on your flight. A safety-checked rescue package is available."
        return ConversationTurn(
            phase="recovery_approval",
            assistant_message=f"Disruption Notice: {prompt}",
            question=None,
            actions=[
                ConversationAction(
                    action_id="approve",
                    label="Approve rescue package",
                    kind="primary",
                    requires_confirmation=True,
                    consequence="Approving rebooks the alternative flight and hotel package through Atlas Sandbox.",
                ),
                ConversationAction(
                    action_id="reject",
                    label="Decline and explore other options",
                    kind="secondary",
                ),
            ],
            requires_user_input=False,
            consequence="Approving rebooks the rescue package through the Atlas Sandbox.",
            provenance_label="EXPLICIT DEMO SIMULATION" if outputs.get("recovery", {}).get("simulated", True) else "Atlas Sandbox",
            recoverable=True,
        )

    # 3. PRIORITY: Price Increase Reapproval
    price_inc_approval = next((a for a in pending_approvals if a.get("is_price_increase") or a.get("purpose") == "price_reapproval" or "price_reapproval" in str(a.get("node_name", ""))), None)
    if price_inc_approval:
        old_price = price_inc_approval.get("old_price") or {}
        new_price = price_inc_approval.get("new_price") or {}
        old_val = float(old_price.get("amount") or 0.0) if old_price.get("amount") is not None else 0.0
        new_val = float(new_price.get("amount") or 0.0) if new_price.get("amount") is not None else 0.0
        old_curr = old_price.get("currency", "USD")
        new_curr = new_price.get("currency", "USD")
        old_amt = f"{old_curr} {old_val:.2f}"
        new_amt = f"{new_curr} {new_val:.2f}"
        consequence_msg = price_inc_approval.get("consequence") or f"The verified fare has updated from {old_amt} to {new_amt}."
        return ConversationTurn(
            phase="price_reapproval",
            assistant_message=f"Price Update: During pre-booking fare verification, the flight price changed from {old_amt} to {new_amt}. Would you like to proceed with the updated total?",
            question=None,
            actions=[
                ConversationAction(
                    action_id="approve",
                    label=f"Accept updated fare ({new_amt})",
                    kind="primary",
                    requires_confirmation=True,
                    consequence=f"Approving accepts the updated total of {new_amt} and attempts the Atlas Sandbox booking.",
                ),
                ConversationAction(
                    action_id="reject",
                    label="Choose a different flight",
                    kind="secondary",
                ),
            ],
            requires_user_input=False,
            consequence=consequence_msg,
            provenance_label="Atlas Sandbox Verified Fare",
            recoverable=True,
            error_code="fare_price_increase",
        )

    # 4. PRIORITY: Booking Approval (Step 4)
    booking_approval = next((a for a in pending_approvals if a.get("node_name") in ("approve_booking", "flight_book")), None)
    if booking_approval:
        prompt = booking_approval.get("prompt") or "Your complete plan is ready. Review and approve to request your Sandbox booking."
        return ConversationTurn(
            phase="booking_approval",
            assistant_message=f"{prompt}",
            question=None,
            actions=[
                ConversationAction(
                    action_id="approve",
                    label="Approve Sandbox booking",
                    kind="primary",
                    requires_confirmation=True,
                    consequence="Approving requests an Atlas Sandbox booking. A PNR exists only if Atlas confirms it.",
                ),
                ConversationAction(
                    action_id="back_to_review",
                    label="Back to plan review",
                    kind="secondary",
                ),
            ],
            requires_user_input=False,
            consequence="Approving requests an Atlas Sandbox booking. A PNR exists only if Atlas confirms it.",
            provenance_label="Atlas Sandbox",
            recoverable=True,
        )

    # 5. PRIORITY: Ticketing Unavailable / Error State
    err_code = error.get("code") or ""
    if not err_code and status == "failed":
        nodes = state.get("nodes") or []
        failed_node = next((n for n in reversed(nodes) if n.get("status") == "FAILED"), None)
        if failed_node:
            err_code = (failed_node.get("details") or {}).get("error_code") or ""

    if status == "failed" and (err_code in ("ticketing_activation_required", "atlas_ticketing_unavailable", "atlas_booking_unavailable", "TICKETING_ACTIVATION_REQUIRED") or "ticketing" in err_code.lower() or (error.get("details") or {}).get("ticketing_blocker") == "TICKETING_ACTIVATION_REQUIRED"):
        return ConversationTurn(
            phase="ticketing_unavailable",
            assistant_message="Your plan is safe. Atlas Sandbox ticketing is not enabled for this account, so no booking or ticket was created.",
            question=None,
            actions=[
                ConversationAction(
                    action_id="back_to_review",
                    label="Back to review",
                    kind="primary",
                )
            ],
            requires_user_input=False,
            consequence="Your complete plan is preserved. You can review all details or search other routes.",
            provenance_label="Atlas Sandbox",
            recoverable=True,
            error_code=err_code or "atlas_ticketing_unavailable",
        )

    if status == "failed":
        msg = error.get("message") or "We hit a snag while planning your trip."
        hint = error.get("hint")
        if hint:
            msg = f"{msg} {hint}"
        return ConversationTurn(
            phase="error",
            assistant_message=msg,
            question=None,
            actions=[
                ConversationAction(
                    action_id="retry",
                    label="Try again",
                    kind="primary",
                )
            ],
            requires_user_input=False,
            recoverable=bool(error.get("recoverable", True)),
            error_code=err_code or "trip_error",
        )

    # 6. PRIORITY: Clarification Questions (First required trip fact BEFORE scope clarification)
    clarify = outputs.get("clarify") or ctx.get("clarify_loop") or {}
    questions = clarify.get("questions") or []
    scope_clarification = clarify.get("scope_clarification")

    # Ask the first unanswered required question before asking scope
    for q in questions:
        field = q.get("field", "")
        if not field or field in FORBIDDEN_PII_FIELDS:
            continue
        prompt = q.get("prompt") or q.get("question") or f"Please provide your {field}."
        input_kind = "choice" if q.get("choices") else ("number" if field == "passengers" else "text")
        choices = q.get("choices") or []
        reason = q.get("reason") or QUESTION_REASONS.get(field)
        q_obj = ConversationQuestion(
            field=field,
            prompt=prompt,
            input_kind=input_kind,
            choices=choices,
            optional=bool(q.get("optional", False)),
            reason=reason,
        )
        return ConversationTurn(
            phase="clarification",
            assistant_message=prompt,
            question=q_obj,
            actions=[],
            requires_user_input=True,
            consequence=None,
            provenance_label="TravelCare AI",
            recoverable=True,
        )

    # Scope choice if ambiguous and all required route/date/passenger facts are known
    if scope_clarification and isinstance(scope_clarification, dict):
        raw_choices = scope_clarification.get("choices") or [
            "flight_only", "flight_plus_booking", "complete_trip"
        ]
        labels = scope_clarification.get("choice_labels") or {}
        choices = [
            {"id": c, "label": labels.get(c, c.replace('_', ' ').capitalize())} if isinstance(c, str) else c
            for c in raw_choices
        ]
        q_obj = ConversationQuestion(
            field="scope_choice",
            prompt=scope_clarification.get("prompt", "How would you like TravelCare to assist you?"),
            input_kind="choice",
            choices=choices,
            optional=False,
            reason="Helps customize your plan with the exact services you need.",
        )
        return ConversationTurn(
            phase="scope_choice",
            assistant_message="To tailor your experience, please choose how you would like to proceed:",
            question=q_obj,
            actions=[],
            requires_user_input=True,
            consequence=None,
            provenance_label="TravelCare AI",
            recoverable=True,
        )

    # 7. PRIORITY: Full Plan Review (Step 3)
    itinerary = outputs.get("itinerary") or ctx.get("itinerary")
    if itinerary and (outputs.get("hotel_research") or outputs.get("flight_search")):
        return ConversationTurn(
            phase="full_plan_review",
            assistant_message="Here is your complete travel plan, including entry requirements, safety status, flights, lodging, and activities. Review everything before deciding to book.",
            question=None,
            actions=[
                ConversationAction(
                    action_id="continue_to_booking",
                    label="Continue to booking →",
                    kind="primary",
                ),
                ConversationAction(
                    action_id="edit_plan",
                    label="Edit plan",
                    kind="secondary",
                ),
            ],
            requires_user_input=False,
            consequence=None,
            provenance_label="Atlas Sandbox & Researched Intelligence",
            recoverable=True,
        )

    # 8. PRIORITY: Flight Options (Step 2)
    flight_search = outputs.get("flight_search") or ctx.get("flight_search")
    if flight_search and flight_search.get("options"):
        opts = flight_search["options"]
        return ConversationTurn(
            phase="options_selection",
            assistant_message=f"Found {len(opts)} flight options in the Atlas Sandbox. Please choose your preferred flight to review your complete plan.",
            question=None,
            actions=[
                ConversationAction(
                    action_id="select_option",
                    label="Select flight option",
                    kind="primary",
                )
            ],
            requires_user_input=False,
            provenance_label="Atlas Sandbox",
            recoverable=True,
        )

    # 9. PRIORITY: Completed Trip (Step 5 / My Trip)
    booking = outputs.get("booking") or ctx.get("flight_book", {}).get("booking")
    if status == "completed" and booking and booking.get("pnr"):
        pnr = booking.get("pnr")
        return ConversationTurn(
            phase="completed",
            assistant_message=f"Your trip is confirmed! PNR: {pnr}. We are monitoring your journey for any disruptions.",
            question=None,
            actions=[
                ConversationAction(
                    action_id="view_trip",
                    label="View My Trip",
                    kind="primary",
                )
            ],
            requires_user_input=False,
            provenance_label="Atlas Sandbox Confirmed Booking",
            recoverable=True,
        )

    # Default in-progress / intake turn
    return ConversationTurn(
        phase="in_progress",
        assistant_message="TravelCare AI is preparing your travel plan...",
        question=None,
        actions=[],
        requires_user_input=False,
        provenance_label="TravelCare AI",
        recoverable=True,
    )
