from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal
from datetime import date

class FlightOffer(BaseModel):
    offer_id: str
    airline: str
    airline_code: str
    flight_number: str
    origin: str
    destination: str
    departure_time: str
    arrival_time: str
    duration_minutes: int
    price_usd: float
    price_converted: Optional[float] = None
    currency: str = "USD"
    currency_symbol: str = "$"
    cabin_class: str = "ECONOMY"
    seats_available: int = 9
    alliance: str = "Star Alliance"
    stops: int = 0
    aircraft: str = "Airbus A320"
    gate: str = "D4"

class FlightSearchRequest(BaseModel):
    origin: str = Field(..., description="IATA 3-letter origin airport code")
    destination: str = Field(..., description="IATA 3-letter destination airport code")
    date: Optional[str] = Field(None, description="Departure date YYYY-MM-DD (defaults to next search day)")
    passengers: Optional[int] = Field(1, ge=1, le=9)
    cabin_class: Optional[str] = Field("ECONOMY")
    currency: Optional[str] = Field("USD")

class PredictiveDisruptionRadar(BaseModel):
    flight_number: str
    inbound_aircraft_tail: str
    inbound_route: str
    inbound_delay_minutes: int
    airspace_congestion_index: str
    weather_radar_status: str
    predicted_cancellation_risk_percent: int
    lead_time_advantage_minutes: int
    recommendation: str

class FlightRescueDiff(BaseModel):
    original_flight: str
    original_carrier: str
    original_departure: str
    original_status: str
    rescue_flight: str
    rescue_carrier: str
    rescue_departure: str
    time_delta_display: str
    loyalty_tier_status: str
    baggage_transfer_status: str
    queue_time_saved_minutes: int

class HotelVoucher(BaseModel):
    voucher_id: str
    hotel_name: str
    stars: int = 4
    location: str
    airside_no_visa: bool = False
    check_in: str
    check_out: str
    room_type: str
    amenities: List[str]
    free_breakfast: bool = True
    shuttle_service: str
    status: str = "CONFIRMED_AND_PAID_BY_AIRLINE"
    qr_code_token: str

class CareGiftVouchers(BaseModel):
    lounge_voucher: str
    dining_credit: str
    grab_transfer_pass: str
    global_esim_data: str
    total_gift_value_usd: float = 95.00

class DisruptionEvent(BaseModel):
    flight_number: str
    passenger_name: str
    date: Optional[str] = None
    currency: Optional[str] = "USD"
    party_size: Optional[int] = 1
    nationality: Optional[str] = "MM"

class RescuePackage(BaseModel):
    package_type: str  # FASTEST_RECOVERY | BEST_VALUE | DIRECT_COMFORT | OVERNIGHT_HOTEL_BUNDLE
    badge: str
    airline: str
    flight_number: str
    departure_time: str
    arrival_time: str
    duration_minutes: int
    price_usd: float
    price_converted: Optional[float] = None
    currency_symbol: str = "$"
    cabin_class: str
    origin: str
    destination: str
    agent_recommendation_reason: str
    offer_id: str
    hotel_included: Optional[HotelVoucher] = None

class BookingRequest(BaseModel):
    offer_id: str
    passenger_name: str
    baggage_addon: Optional[str] = "30kg Priority Included"
    seat_selected: Optional[str] = "12A"
    price_usd: float
    party_size: Optional[int] = 1
    hotel_needed: Optional[bool] = False

class BookingConfirmation(BaseModel):
    booking_id: str
    pnr: str
    ticket_number: str
    status: str
    passenger_name: str
    flight_number: str
    seat_assigned: str
    gate: str
    boarding_time: str
    lounge_pass: str
    baggage_tag: str
    hotel_voucher: Optional[HotelVoucher] = None
    care_gifts: Optional[CareGiftVouchers] = None

class CompensationClaim(BaseModel):
    claim_id: str
    passenger_name: str
    flight_number: str
    carrier: str
    incident_type: str
    cause: str
    eligible_payout_usd: float
    status: str
    settlement_method: str
    created_at: str
    filing_officer: str

class ConciergeQuery(BaseModel):
    query: str
    session_id: Optional[str] = None

class ConciergeResponse(BaseModel):
    reply: str
    action_taken: str
    metadata: Optional[Dict[str, Any]] = None

class AgentTelemetry(BaseModel):
    model: str
    system_prompt: str
    pareto_weights: Dict[str, float]
    average_reasoning_tokens: int
    inference_latency_ms: float
    framework: str


# ---------------------------------------------------------------------------
# TravelCare v2 contracts (MASTER_BUILD_PACKAGE.md §5) — append-only block.
# Existing models above stay untouched.
#
# CANONICAL PRIVACY CONTRACT (R1 reconciliation): NO passport number field
# exists in any v2 contract — no requesting, accepting, transmitting,
# masking, storing, displaying, or testing of passport numbers. Passport
# COUNTRY is sufficient for the demo, visa logic, and route risk.
# ---------------------------------------------------------------------------

# Canonical safe-field allowlist (§5 Profile). Every other profile field —
# especially passport-number/expiry/government-ID/payment shapes — is
# rejected at the boundary.
SAFE_PROFILE_FIELDS = frozenset({
    "passport_country", "home_city", "preferred_origin_airport", "cabin",
    "airlines_like", "diet", "budget_range", "display_currency",
    "accessibility_notes"})
FORBIDDEN_PROFILE_FIELDS = frozenset({
    "passport_no", "passport_number", "passport", "expiry", "national_id",
    "document_number", "full_name", "legal_name", "name", "date_of_birth",
    "payment_card", "card_number"})


class DateWindow(BaseModel):
    start: date
    end: date


class TripGoal(BaseModel):
    goal_id: str
    raw_text: str
    origin_city: Optional[str] = None
    dest_city: Optional[str] = None
    date_window: Optional[DateWindow] = None
    passengers: int = Field(1, ge=1)
    budget_hint: Optional[str] = None
    purpose: Optional[str] = None


class FlightEndpoint(BaseModel):
    airport: str
    time: str


class Money(BaseModel):
    amount: float
    currency: str


class FlightOption(BaseModel):
    id: str
    carrier: str
    flight_no: str
    dep: FlightEndpoint
    arr: FlightEndpoint
    duration_min: int
    price: Money
    sandbox_provenance: Literal[True] = True


class BookingRecord(BaseModel):
    pnr: str
    option: FlightOption
    status: str
    booked_at: str
    monitor_armed: bool


class VisaSource(BaseModel):
    url: str
    retrieved_date: date


class VisaRequirement(BaseModel):
    country: str
    kind: Literal["entry", "transit"]
    name: str
    risk_level: Literal["info", "warn", "block"]
    source: VisaSource
    as_of: date


class WebIntelCitation(BaseModel):
    url: str
    title: str
    retrieved_date: date
    snippet_max280: str = Field(..., max_length=280)


class ProfileIdentity(BaseModel):
    """Identity block — SAFE fields only (canonical §5): passport country
    and home city. No passport number, expiry, or legal identity exists."""
    passport_country: Optional[str] = None
    home_city: Optional[str] = None


class ProfilePrefs(BaseModel):
    cabin: Optional[str] = None
    airlines_like: List[str] = []
    diet: Optional[str] = None
    budget_range: Optional[str] = None
    preferred_origin_airport: Optional[str] = None
    display_currency: Optional[str] = None
    accessibility_notes: Optional[str] = None


class ProfileFieldValue(BaseModel):
    value: Any
    source: Literal["user", "ai_inferred"]
    updated_at: str


class ProfileConsent(BaseModel):
    store_local: bool = False


class Profile(BaseModel):
    user_id: str
    identity: ProfileIdentity = ProfileIdentity()
    prefs: ProfilePrefs = ProfilePrefs()
    fields: Dict[str, ProfileFieldValue] = {}
    consent: ProfileConsent = ProfileConsent()


class ConfirmationChip(BaseModel):
    field: str
    proposed_value: Any
    message: str
    state: Literal["pending", "confirmed", "rejected"] = "pending"


class ApprovalRequest(BaseModel):
    approval_id: str
    node_name: str
    options: List[Any] = []
    created_at: str
    resolved_value: Optional[Any] = None
    # G2-DA fix: optional expiry (ISO timestamp). None = never expires
    # (backward compatible); resolve_approval rejects expired approvals with
    # a recoverable approval_expired error.
    expires_at: Optional[str] = None


from services.state_graph import GraphNodeState  # noqa: E402  (extends legacy model)


class GraphNodeStateV2(GraphNodeState):
    skill_ref: str
    citations: List[WebIntelCitation] = []


# --- Intent-first service scoping (owner correction, pre-G2) ---------------

ServiceScope = Literal["requested", "not_requested", "unknown"]


class RequestedServices(BaseModel):
    """Per-service scope; every service defaults to unknown (never pre-requested)."""
    flight_search: ServiceScope = "unknown"
    flight_booking: ServiceScope = "unknown"
    visa_check: ServiceScope = "unknown"
    hotel: ServiceScope = "unknown"
    activities: ServiceScope = "unknown"
    local_transport: ServiceScope = "unknown"


class TripIntent(BaseModel):
    intent_id: str
    raw_text: str
    goal: TripGoal
    requested_services: RequestedServices = RequestedServices()
    scope_clarified: bool = False


# --- G2 runtime output contracts ------------------------------------------------

class WebIntelResult(BaseModel):
    provider: str
    degraded: bool = False
    offline: bool = False
    answers: List[str] = []
    citations: List[WebIntelCitation] = []


class RightsOpinion(BaseModel):
    regime: str  # EU261 | UK261 | TURKEY_SHY | US_DOT | NONE
    amount: Optional[float] = None
    currency: Optional[str] = None
    legal_citation: str = ""
    distance_km: int = 0
    note: str = ""


class ItemProvenance(BaseModel):
    source_url: Optional[str] = None
    retrieved_date: Optional[date] = None
    researched_as_of: Optional[date] = None
    degraded: bool = False


class ItineraryItem(BaseModel):
    name: str
    kind: str  # flight | hotel | activity | local_transport
    source: str  # atlas_real | organizer | amadeus | osm | researched_mock | llm_suggestion
    honesty_label: str  # §15.2 chip text
    price_range_sgd: Optional[List[float]] = None
    details: Dict[str, Any] = {}
    provenance: ItemProvenance = ItemProvenance()


class ScopeClarificationRequest(BaseModel):
    prompt: str
    choices: List[str]  # exactly: flight_only | flight_plus_booking | complete_trip


class ResearchRecord(BaseModel):
    """Every research result carries provenance + freshness (owner correction C)."""
    domain: str  # flight | visa | hotel | activities | local_transport
    provenance: str
    source_url: Optional[str] = None
    retrieved_date: date
    freshness_state: Literal["fresh", "stale", "unknown"] = "unknown"
    degraded: bool = False
    data: Dict[str, Any] = {}


# --- Safety intelligence pipeline contracts (Task #13) -------------------------
# LLM NEVER decides safety status: it may only extract bounded facts from
# trusted sources; the deterministic SafetyPolicyEngine computes every
# displayed status from this closed normalized vocabulary.

SafetyLevel = Literal[
    "normal_precautions",
    "increased_caution",
    "reconsider_travel",
    "do_not_travel",
    "unable_to_verify",
]

SafetySourceType = Literal[
    "official_government",        # home/destination government advisory
    "official_multilateral",      # WHO, GDACS-class official bodies
    "transport_operator",         # airline/airport/transport operational
    "third_party",                # never sets or clears official status
    "social",                     # never sets or clears status
]


class SafetyQuery(BaseModel):
    """Input contract for one safety assessment. PRIVACY HARD RULE: this
    model must NEVER carry a passport number, legal identity, precise live
    location, or payment data — only the coarse facts needed to match
    advisories to a route."""
    trip_id: Optional[str] = None
    destination_country: str
    destination_regions: List[str] = []
    cities: List[str] = []
    venue: Optional[str] = None
    route_legs: List[str] = []
    transit_countries: List[str] = []
    transit_airports: List[str] = []
    travel_window: Optional[DateWindow] = None
    passport_country: Optional[str] = None
    residence_country: Optional[str] = None
    requested_categories: List[str] = []


class SafetyEvidence(BaseModel):
    """One official-source finding. Native wording/level is preserved
    alongside the normalized level — normalization never overwrites the
    source's own phrasing."""
    source_id: str                    # gov_uk | us_state | au_smartraveller | ...
    authority: str                    # publisher name in its own wording
    authority_country: Optional[str] = None
    applies_to_nationalities: List[str] = []   # empty = all travelers
    source_type: SafetySourceType = "official_government"
    canonical_url: str
    title: str
    published_at: Optional[str] = None
    updated_at: Optional[str] = None
    retrieved_at: str
    expires_at: Optional[str] = None
    country: str
    affected_regions: List[str] = []
    excluded_regions: List[str] = []
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    native_level: Optional[str] = None        # source's own level wording
    normalized_level: SafetyLevel = "unable_to_verify"
    risk_categories: List[str] = []           # advisory|health|severe_weather|
                                              # disaster|transport_disruption|
                                              # security|local_laws
    concise_facts: List[str] = []             # bounded extracted facts only
    recommended_actions: List[str] = []
    freshness: Literal["fresh", "stale", "unknown"] = "unknown"
    verification_status: Literal["verified", "unverified", "unavailable"] = "unverified"
    extraction_method: Literal["structured_parse", "llm_bounded", "snippet_only"] = \
        "structured_parse"


class SafetySourceReport(BaseModel):
    """Honest per-source outcome — source availability differs by country;
    no single source is universal truth."""
    source_id: str
    status: Literal["ok", "no_coverage", "unavailable", "rejected"]
    note: str = ""
    evidence_count: int = 0


class SafetyAssessment(BaseModel):
    overall_status: SafetyLevel
    trip_policy_status: SafetyLevel
    assessments_per_source: List[Dict[str, Any]] = []
    disagreements: List[Dict[str, Any]] = []
    why_selected: str
    recommended_actions: List[str] = []
    safer_alternatives: List[str] = []
    checked_at: str
    confidence_or_unable_to_verify: str
    unverified_sources: List[str] = []
    stale_warnings: List[Dict[str, Any]] = []   # prior warnings past their
                                                # freshness window — visible,
                                                # labeled, never silently cleared
    risk_acknowledged: bool = False
    monitor_enabled: bool = False


class SafetyChangeEvent(BaseModel):
    """Emitted ONLY on a material change (severity / affected region /
    validity period / recommended action). Old + new evidence are retained
    and the differences identified. A change may PROPOSE a partial replan
    through an approval — it never modifies or rebooks anything."""
    event_id: str
    trip_id: str
    detected_at: str
    change_kinds: List[str]          # severity|affected_region|validity|actions
    differences: List[str]
    old_evidence: Dict[str, Any] = {}
    new_evidence: Dict[str, Any] = {}
    proposed_action: str = "review"  # review | partial_replan_proposal
    approval_required: bool = True
