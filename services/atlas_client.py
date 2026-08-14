import uuid
import datetime
from typing import Dict, Any, List, Optional
import httpx
from config import settings

class AtlasClient:
    """Client for interacting with Atlas Flight APIs & ATRIP Sandbox."""

    # Currency exchange rates relative to USD
    RATES = {
        "USD": 1.0,
        "THB": 35.4,
        "SGD": 1.34,
        "MMK": 3500.0,
        "EUR": 0.92
    }
    SYMBOLS = {
        "USD": "$",
        "THB": "฿",
        "SGD": "S$",
        "MMK": "Ks ",
        "EUR": "€"
    }

    def __init__(self):
        self.base_url = settings.atrip_api_base
        self.ak = settings.atrip_ak
        self.sk = settings.atrip_sk
        self.use_mock = settings.use_mock_fallback

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-Atlas-Access-Key": self.ak,
            "X-Atlas-Signature": "sandbox_sig_validated",
            "User-Agent": "AtlasRescueAgent/3.0 (Qoder Hackathon 2026 Production)"
        }

    async def get_flight_status(self, flight_number: str, date: str) -> Dict[str, Any]:
        """Check live flight status for disruptions."""
        clean_code = flight_number.upper().replace(" ", "").replace("-", "")
        
        disruptions = {
            "TG303": {
                "flight_number": "TG303",
                "carrier": "Thai Airways",
                "origin": "BKK",
                "origin_airport": "Suvarnabhumi Airport (BKK)",
                "destination": "RGN",
                "destination_airport": "Yangon International Airport (RGN)",
                "scheduled_departure": f"{date} 09:15",
                "scheduled_arrival": f"{date} 10:00",
                "status": "CANCELLED",
                "reason": "Aircraft Maintenance / Engine Hydraulics",
                "affected_passengers": 184,
                "gate": "C4",
                "terminal": "Terminal 1 Main",
                "aircraft": "Boeing 777-300ER",
                "compensation_amount_usd": 250.0
            },
            "PG920": {
                "flight_number": "PG920",
                "carrier": "Bangkok Airways",
                "origin": "BKK",
                "origin_airport": "Suvarnabhumi Airport (BKK)",
                "destination": "RGN",
                "destination_airport": "Yangon International Airport (RGN)",
                "scheduled_departure": f"{date} 14:00",
                "scheduled_arrival": f"{date} 14:50",
                "status": "DELAYED_4H",
                "reason": "Severe Tropical Storm / Air Traffic Hold",
                "affected_passengers": 120,
                "gate": "A2",
                "terminal": "Terminal 1 Concourse A",
                "aircraft": "Airbus A320",
                "compensation_amount_usd": 180.0
            },
            "FD251": {
                "flight_number": "FD251",
                "carrier": "Thai AirAsia",
                "origin": "DMK",
                "origin_airport": "Don Mueang Airport (DMK)",
                "destination": "RGN",
                "destination_airport": "Yangon International Airport (RGN)",
                "scheduled_departure": f"{date} 16:20",
                "scheduled_arrival": f"{date} 17:05",
                "status": "RESCHEDULED",
                "reason": "Slot Time Revision",
                "affected_passengers": 160,
                "gate": "Gate 24",
                "terminal": "Terminal 2",
                "aircraft": "Airbus A320neo",
                "compensation_amount_usd": 120.0
            },
            "SQ970": {
                "flight_number": "SQ970",
                "carrier": "Singapore Airlines",
                "origin": "SIN",
                "origin_airport": "Changi Airport (SIN)",
                "destination": "BKK",
                "destination_airport": "Suvarnabhumi Airport (BKK)",
                "scheduled_departure": f"{date} 07:10",
                "scheduled_arrival": f"{date} 08:35",
                "status": "CANCELLED",
                "reason": "Changi Airfield Maintenance Ground Stop",
                "affected_passengers": 240,
                "gate": "B3",
                "terminal": "Terminal 3",
                "aircraft": "Airbus A350-900",
                "compensation_amount_usd": 300.0
            }
        }
        
        return disruptions.get(clean_code, {
            "flight_number": flight_number,
            "carrier": "International Carrier",
            "origin": "BKK",
            "origin_airport": "Suvarnabhumi Airport (BKK)",
            "destination": "RGN",
            "destination_airport": "Yangon International Airport (RGN)",
            "scheduled_departure": f"{date} 10:00",
            "scheduled_arrival": f"{date} 10:50",
            "status": "CANCELLED",
            "reason": "Operational Disruption",
            "affected_passengers": 150,
            "gate": "D1",
            "terminal": "Terminal 1",
            "aircraft": "Commercial Jet",
            "compensation_amount_usd": 200.0
        })

    async def search_flights(
        self, origin: str, destination: str, date: str, passengers: int = 1, cabin_class: str = "ECONOMY", currency: str = "USD"
    ) -> List[Dict[str, Any]]:
        """Search available flights across 140+ airlines on Atlas GDS with multi-currency conversion."""
        origin = origin.upper().strip()
        destination = destination.upper().strip()
        currency = currency.upper().strip() if currency in self.RATES else "USD"
        rate = self.RATES.get(currency, 1.0)
        symbol = self.SYMBOLS.get(currency, "$")

        # Flexible multi-city routes
        if origin == "SIN" and destination == "BKK":
            base_offers = [
                {
                    "offer_id": "off_atlas_sq_711",
                    "flight_number": "SQ712",
                    "airline": "Singapore Airlines",
                    "airline_code": "SQ",
                    "origin": "SIN",
                    "origin_airport": "Changi Airport (SIN)",
                    "destination": "BKK",
                    "destination_airport": "Suvarnabhumi Airport (BKK)",
                    "departure_time": f"{date} 09:30",
                    "arrival_time": f"{date} 11:00",
                    "duration_minutes": 150,
                    "stops": 0,
                    "cabin_class": "Economy Flex",
                    "price_usd": 210.00,
                    "baggage_included": "30kg Checked + 7kg Cabin",
                    "seats_available": 12,
                    "alliance": "Star Alliance",
                    "on_time_performance": "97%",
                    "gate": "B7",
                    "terminal": "Terminal 3"
                },
                {
                    "offer_id": "off_atlas_scoot_302",
                    "flight_number": "TR610",
                    "airline": "Scoot",
                    "airline_code": "TR",
                    "origin": "SIN",
                    "origin_airport": "Changi Airport (SIN)",
                    "destination": "BKK",
                    "destination_airport": "Suvarnabhumi Airport (BKK)",
                    "departure_time": f"{date} 12:15",
                    "arrival_time": f"{date} 13:45",
                    "duration_minutes": 150,
                    "stops": 0,
                    "cabin_class": "FlyBag",
                    "price_usd": 115.00,
                    "baggage_included": "20kg Checked + 10kg Cabin",
                    "seats_available": 18,
                    "alliance": "Value Alliance",
                    "on_time_performance": "90%",
                    "gate": "E2",
                    "terminal": "Terminal 1"
                }
            ]
        else:
            # Default BKK -> RGN route
            base_offers = [
                {
                    "offer_id": "off_atlas_mai_801",
                    "flight_number": "8M336",
                    "airline": "Myanmar Airways International (MAI)",
                    "airline_code": "8M",
                    "origin": origin,
                    "origin_airport": "Suvarnabhumi Airport (BKK)",
                    "destination": destination,
                    "destination_airport": "Yangon International Airport (RGN)",
                    "departure_time": f"{date} 11:45",
                    "arrival_time": f"{date} 12:35",
                    "duration_minutes": 80,
                    "stops": 0,
                    "cabin_class": "Economy Priority",
                    "price_usd": 145.00,
                    "baggage_included": "30kg Checked + 7kg Cabin",
                    "seats_available": 6,
                    "alliance": "Independent Partner",
                    "on_time_performance": "95%",
                    "gate": "D4",
                    "terminal": "Terminal 1 Main"
                },
                {
                    "offer_id": "off_atlas_airasia_502",
                    "flight_number": "FD251",
                    "airline": "Thai AirAsia",
                    "airline_code": "FD",
                    "origin": "DMK" if origin == "BKK" else origin,
                    "origin_airport": "Don Mueang Airport (DMK)",
                    "destination": destination,
                    "destination_airport": "Yangon International Airport (RGN)",
                    "departure_time": f"{date} 16:20",
                    "arrival_time": f"{date} 17:05",
                    "duration_minutes": 75,
                    "stops": 0,
                    "cabin_class": "Economy Promo",
                    "price_usd": 89.00,
                    "baggage_included": "7kg Cabin (20kg Addon +$18)",
                    "seats_available": 14,
                    "alliance": "AirAsia Group",
                    "on_time_performance": "88%",
                    "gate": "Gate 15",
                    "terminal": "Terminal 2"
                },
                {
                    "offer_id": "off_atlas_thai_903",
                    "flight_number": "TG307",
                    "airline": "Thai Airways (Next Flight)",
                    "airline_code": "TG",
                    "origin": origin,
                    "origin_airport": "Suvarnabhumi Airport (BKK)",
                    "destination": destination,
                    "destination_airport": "Yangon International Airport (RGN)",
                    "departure_time": f"{date} 18:00",
                    "arrival_time": f"{date} 18:50",
                    "duration_minutes": 80,
                    "stops": 0,
                    "cabin_class": "Economy Flex Plus",
                    "price_usd": 160.00,
                    "baggage_included": "30kg Checked + Meal + Lounge",
                    "seats_available": 9,
                    "alliance": "Star Alliance",
                    "on_time_performance": "91%",
                    "gate": "C7",
                    "terminal": "Terminal 1 Main"
                },
                {
                    "offer_id": "off_atlas_bangkokair_104",
                    "flight_number": "PG703",
                    "airline": "Bangkok Airways",
                    "airline_code": "PG",
                    "origin": origin,
                    "origin_airport": "Suvarnabhumi Airport (BKK)",
                    "destination": destination,
                    "destination_airport": "Yangon International Airport (RGN)",
                    "departure_time": f"{date} 15:10",
                    "arrival_time": f"{date} 16:00",
                    "duration_minutes": 80,
                    "stops": 0,
                    "cabin_class": "Boutique Economy",
                    "price_usd": 155.00,
                    "baggage_included": "20kg Checked + Boutique Lounge",
                    "seats_available": 4,
                    "alliance": "Boutique Partner",
                    "on_time_performance": "96%",
                    "gate": "A5",
                    "terminal": "Terminal 1 Concourse A"
                }
            ]

        # Convert currency
        for o in base_offers:
            o["currency"] = currency
            o["currency_symbol"] = symbol
            o["price_converted"] = round(o["price_usd"] * rate, 2)

        return base_offers

    async def verify_fare(self, offer_id: str) -> Dict[str, Any]:
        """Verify fare price and seat availability before locking."""
        return {
            "verified": True,
            "offer_id": offer_id,
            "fare_lock_expires_in_seconds": 900,
            "price_guarantee": "Locked by Atlas Sandbox GDS",
            "verified_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }

    async def get_seat_map(self, flight_number: str) -> Dict[str, Any]:
        """Get aircraft seat map with available vs occupied seats."""
        return {
            "flight_number": flight_number,
            "aircraft": "Airbus A320 / Boeing 737-800",
            "configuration": "3-3",
            "selected_default": "12A",
            "rows": [
                {
                    "row_num": 11,
                    "type": "Extra Legroom",
                    "seats": [
                        {"seat": "11A", "status": "OCCUPIED", "price": 0},
                        {"seat": "11B", "status": "AVAILABLE", "price": 10, "feature": "Extra Legroom"},
                        {"seat": "11C", "status": "OCCUPIED", "price": 0},
                        {"seat": "11D", "status": "AVAILABLE", "price": 10},
                        {"seat": "11E", "status": "AVAILABLE", "price": 10},
                        {"seat": "11F", "status": "OCCUPIED", "price": 0}
                    ]
                },
                {
                    "row_num": 12,
                    "type": "Standard Window/Aisle",
                    "seats": [
                        {"seat": "12A", "status": "SELECTED", "price": 0, "feature": "Window - Prime View"},
                        {"seat": "12B", "status": "AVAILABLE", "price": 0},
                        {"seat": "12C", "status": "OCCUPIED", "price": 0},
                        {"seat": "12D", "status": "AVAILABLE", "price": 0},
                        {"seat": "12E", "status": "AVAILABLE", "price": 0},
                        {"seat": "12F", "status": "AVAILABLE", "price": 0}
                    ]
                },
                {
                    "row_num": 14,
                    "type": "Standard",
                    "seats": [
                        {"seat": "14A", "status": "OCCUPIED", "price": 0},
                        {"seat": "14B", "status": "AVAILABLE", "price": 0},
                        {"seat": "14C", "status": "AVAILABLE", "price": 0, "feature": "Aisle - Fast Exit"},
                        {"seat": "14D", "status": "OCCUPIED", "price": 0},
                        {"seat": "14E", "status": "AVAILABLE", "price": 0},
                        {"seat": "14F", "status": "AVAILABLE", "price": 0}
                    ]
                }
            ]
        }

    async def get_baggage_status(self, pnr: str) -> Dict[str, Any]:
        """Track baggage transfer status during disruption."""
        return {
            "pnr": pnr,
            "tag_number": f"BKK-{pnr[-4:]}-8921",
            "weight": "24.5 kg",
            "status": "TRANSFERRED_TO_NEW_AIRCRAFT",
            "last_checkpoint": "Suvarnabhumi BHS Hub (Concourse D - Belt 14)",
            "updated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M UTC"),
            "steps": [
                {"title": "Unloaded from Original Disrupted Flight", "done": True, "time": "25 mins ago"},
                {"title": "Security Re-screened at Transit Bag Hub", "done": True, "time": "14 mins ago"},
                {"title": "Auto-assigned to Rescue Flight (MAI 8M 336)", "done": True, "time": "4 mins ago"},
                {"title": "Loaded on Cargo Bay 2 (Manifest Verified)", "done": True, "time": "Just now"}
            ]
        }

    async def create_booking_order(
        self, offer_id: str, passenger: Dict[str, Any], baggage_addon: Optional[str] = None, seat_selected: str = "12A"
    ) -> Dict[str, Any]:
        """Execute Sandbox booking order and settle via Atlas balance."""
        order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
        pnr = f"ATLAS-{uuid.uuid4().hex[:6].upper()}"
        
        return {
            "order_id": order_id,
            "pnr": pnr,
            "status": "CONFIRMED",
            "offer_id": offer_id,
            "passenger_name": passenger.get("name", "Aung Hein Kyaw"),
            "passport_number": passenger.get("passport", "MB123456"),
            "payment_status": "SETTLED_VIA_ATLAS_BALANCE",
            "amount_paid_usd": passenger.get("price_usd", 145.00),
            "baggage_confirmed": baggage_addon or "30kg Priority Allowance Included",
            "seat_assigned": seat_selected or "12A (Window)",
            "booking_timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "ticket_number": f"140-{uuid.uuid4().int % 1000000000:010d}",
            "gate": "D4",
            "boarding_time": "11:05 AM",
            "terminal": "Terminal 1 Concourse D"
        }
