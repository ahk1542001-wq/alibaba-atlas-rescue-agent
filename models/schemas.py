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
    date: Optional[str] = Field("2026-08-20", description="Departure date YYYY-MM-DD")
    passengers: Optional[int] = Field(1, ge=1, le=9)
    cabin_class: Optional[str] = Field("ECONOMY")
    currency: Optional[str] = Field("USD")

class DisruptionEvent(BaseModel):
    flight_number: str
    passenger_name: Optional[str] = "Aung Hein Kyaw"
    date: Optional[str] = None
    currency: Optional[str] = "USD"
    party_size: Optional[int] = 1

class RescuePackage(BaseModel):
    package_type: str  # FASTEST_RECOVERY | BEST_VALUE | DIRECT_COMFORT
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

class BookingRequest(BaseModel):
    offer_id: str
    passenger_name: str
    passport_number: Optional[str] = "MB987654"
    baggage_addon: Optional[str] = "30kg Priority Included"
    seat_selected: Optional[str] = "12A"
    price_usd: float
    party_size: Optional[int] = 1

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
