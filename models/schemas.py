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
    passport_number: Optional[str] = None
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
# ---------------------------------------------------------------------------

def mask_passport(passport_no: str) -> str:
    """Mask a passport number; never echoes raw characters for short inputs.

    mask_passport("MD1234567") -> "MD*****67" (first2+last2 only when the
    input is >=8 chars, where that reveals less than half). Inputs shorter
    than 8 chars are fully redacted to a fixed-shape star string — a 5-char
    secret must not survive as 4 visible characters (DA-review fix).
    """
    if len(passport_no) < 8:
        return "*" * len(passport_no)
    return f"{passport_no[:2]}{'*' * (len(passport_no) - 4)}{passport_no[-2:]}"


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
    """Identity block — every field optional so new profiles start empty."""
    passport_country: Optional[str] = None
    passport_no_masked: Optional[str] = None
    expiry: Optional[date] = None
    home_city: Optional[str] = None


class ProfilePrefs(BaseModel):
    cabin: Optional[str] = None
    airlines_like: List[str] = []
    diet: Optional[str] = None
    budget_range: Optional[str] = None


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
