from pydantic import BaseModel, Field, model_validator
from typing import Optional, List, Dict, Any, Literal
from datetime import date, datetime, timezone
import math
import uuid

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
    origin_airport_candidates: List[str] = Field(default_factory=list)
    confirmed_origin_airport: Optional[str] = None
    dest_city: Optional[str] = None
    destination_airport_candidates: List[str] = Field(default_factory=list)
    confirmed_destination_airport: Optional[str] = None
    venue: Optional[str] = None
    date_window: Optional[DateWindow] = None
    passengers: int = Field(1, ge=1)
    budget_hint: Optional[str] = None
    purpose: Optional[str] = None
    missing_fields: List[str] = Field(default_factory=list)


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


class ProfileValue(BaseModel):
    value: Any
    source: Literal["user", "ai_inferred"] = "user"
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    confirmation: str = "confirmed"


ProfileFieldValue = ProfileValue


class ProfileConsent(BaseModel):
    store_local: bool = False


class Profile(BaseModel):
    user_id: str
    passport_country: Optional[ProfileValue] = None
    home_city: Optional[ProfileValue] = None
    preferred_origin_airport: Optional[ProfileValue] = None
    cabin: Optional[ProfileValue] = None
    airlines_like: Optional[ProfileValue] = None
    diet: Optional[ProfileValue] = None
    budget_range: Optional[ProfileValue] = None
    display_currency: Optional[ProfileValue] = None
    accessibility_notes: Optional[ProfileValue] = None
    consent: ProfileConsent = Field(default_factory=ProfileConsent)
    schema_version: int = 1

    # Compatibility shim fields for legacy callers
    identity: ProfileIdentity = Field(default_factory=ProfileIdentity)
    prefs: ProfilePrefs = Field(default_factory=ProfilePrefs)
    fields: Dict[str, ProfileValue] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _normalize_profile_input(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        d = dict(data)
        fields_dict = d.get("fields")
        if isinstance(fields_dict, dict):
            d["fields"] = {k: v for k, v in fields_dict.items()
                           if k in SAFE_PROFILE_FIELDS and k not in FORBIDDEN_PROFILE_FIELDS}

        # Migrate from fields dict, identity, or prefs if top-level missing
        fields_clean = d.get("fields")
        for fld in SAFE_PROFILE_FIELDS:
            val = d.get(fld)
            if val is None and isinstance(fields_clean, dict) and fld in fields_clean:
                val = fields_clean[fld]
            if val is None and fld == "passport_country" and isinstance(d.get("identity"), dict):
                val = d["identity"].get("passport_country")
            if val is None and fld == "home_city" and isinstance(d.get("identity"), dict):
                val = d["identity"].get("home_city")
            if val is None and isinstance(d.get("prefs"), dict) and fld in d["prefs"]:
                val = d["prefs"].get(fld)

            if val is not None:
                if isinstance(val, dict) and "value" in val:
                    d[fld] = val
                elif isinstance(val, ProfileValue):
                    d[fld] = val
                else:
                    d[fld] = {
                        "value": val,
                        "source": "user",
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                        "confirmation": "confirmed"
                    }

        return d

    @model_validator(mode="after")
    def _sync_compat_shims(self) -> "Profile":
        # Keep only safe fields in self.fields
        clean_fields = {}
        for fld in SAFE_PROFILE_FIELDS:
            pv = getattr(self, fld, None)
            if pv is not None:
                clean_fields[fld] = pv
                if fld == "passport_country" and pv.value is not None:
                    self.identity.passport_country = str(pv.value)
                elif fld == "home_city" and pv.value is not None:
                    self.identity.home_city = str(pv.value)
                elif fld == "cabin" and pv.value is not None:
                    self.prefs.cabin = str(pv.value)
                elif fld == "preferred_origin_airport" and pv.value is not None:
                    self.prefs.preferred_origin_airport = str(pv.value)
                elif fld == "display_currency" and pv.value is not None:
                    self.prefs.display_currency = str(pv.value)
                elif fld == "budget_range" and pv.value is not None:
                    self.prefs.budget_range = str(pv.value)
                elif fld == "diet" and pv.value is not None:
                    self.prefs.diet = str(pv.value)
                elif fld == "accessibility_notes" and pv.value is not None:
                    self.prefs.accessibility_notes = str(pv.value)
                elif fld == "airlines_like" and pv.value is not None:
                    self.prefs.airlines_like = pv.value if isinstance(pv.value, list) else [str(pv.value)]
        self.fields = clean_fields
        return self


class ConfirmationChip(BaseModel):
    chip_id: str = Field(default_factory=lambda: f"chip-{uuid.uuid4().hex[:8]}")
    field: str
    proposed_value: Any
    message: str
    state: Literal["pending", "confirmed", "rejected", "corrected"] = "pending"
    corrected_value: Optional[Any] = None
    trip_id: Optional[str] = None
    options: List[Any] = Field(default_factory=list)


class ApprovalRequest(BaseModel):
    approval_id: str
    node_name: str
    options: List[Any] = []
    created_at: str
    resolved_value: Optional[Any] = None
    trip_id: Optional[str] = None
    purpose: Optional[str] = None
    immutable_option: Optional[Dict[str, Any]] = None
    price_snapshot: Optional[Dict[str, Any]] = None
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
    item_id: str = Field(default_factory=lambda: f"itin-{uuid.uuid4().hex[:8]}")
    name: str
    kind: str  # flight | hotel | activity | local_transport
    source: str  # atlas_real | organizer | amadeus | osm | researched_mock | llm_suggestion
    honesty_label: str  # §15.2 chip text
    price_range_sgd: Optional[List[float]] = None
    details: Dict[str, Any] = Field(default_factory=dict)
    provenance: ItemProvenance = Field(default_factory=ItemProvenance)
    booked: bool = False  # True for flight items linked to a BookingRecord


class ItineraryReplacementRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)
    kind: Literal["hotel", "activity", "local_transport"]
    price_range_sgd: Optional[List[float]] = Field(
        default=None, min_length=2, max_length=2)
    details: Dict[str, Any] = Field(default_factory=dict)
    source_url: Optional[str] = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_price_range(self):
        if self.price_range_sgd is not None:
            low, high = self.price_range_sgd
            if (not math.isfinite(low) or not math.isfinite(high)
                    or low < 0 or high < low):
                raise ValueError(
                    "price_range_sgd must be non-negative and ordered low to high")
        return self


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
