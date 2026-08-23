from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

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
