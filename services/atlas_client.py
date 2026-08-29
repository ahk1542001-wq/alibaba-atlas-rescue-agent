import asyncio
import datetime
import json as _json
import logging
import math
import shutil
from typing import Dict, Any, List, Optional

logger = logging.getLogger("atlas")


class AtlasProviderError(RuntimeError):
    """Safe, typed failure at the Atlas Sandbox boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class AtlasSandboxUnavailableError(AtlasProviderError):
    pass


class AtlasMalformedResponseError(AtlasProviderError):
    pass


class AtlasTicketingUnavailableError(AtlasProviderError):
    pass


class AtlasTravelerDataRequiredError(AtlasProviderError):
    pass


def tomorrow_iso() -> str:
    return (datetime.date.today() + datetime.timedelta(days=1)).isoformat()


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

    def __init__(self, environment: str = "sandbox"):
        if environment != "sandbox":
            raise ValueError(f"AtlasClient only supports 'sandbox' environment (attempted: {environment!r})")
        self.environment = "sandbox"
        self.last_cli_envelope: Optional[Dict[str, Any]] = None
        self._capability_status: Optional[Dict[str, Any]] = None

    def get_capability_boundary(self) -> Dict[str, Any]:
        """Return the 8-field provider capability boundary.
        Defaults are conservative: activation_url=None, order/payment/ticketing unavailable
        unless returned by normalized atlas-flight auth status envelope.
        """
        auth_data = self._capability_status or {}
        return {
            "search_available": bool(auth_data.get("search_available", False)),
            "verification_available": bool(auth_data.get("verification_available", False)),
            "order_creation_available": bool(auth_data.get("order_creation_available", False)),
            "payment_available": bool(auth_data.get("payment_available", False)),
            "ticketing_available": bool(auth_data.get("ticketing_available", False)),
            "blocker_code": auth_data.get("blocker_code") or None,
            "activation_url": auth_data.get("activation_url") or None,
            "environment": "sandbox",
            "provenance": "atlas_sandbox",
        }

    # ------------------------------------------------------------------
    # Official atlas-flight CLI bridge (real Atlas Sandbox)
    # Authentication is completed once via `atlas-flight auth login`.
    # Any failure is typed and fail-closed; runtime callers never fall back to
    # fabricated provider data.
    # ------------------------------------------------------------------
    async def _run_cli(self, args: List[str]) -> Dict[str, Any]:
        binary = shutil.which("atlas-flight")
        if not binary:
            raise AtlasSandboxUnavailableError(
                "ATLAS_CLI_UNAVAILABLE",
                "Atlas Sandbox CLI is unavailable.",
            )
        cmd = [binary] + args + ["--json"]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout=90)
            line = stdout.decode().strip()
            if not line:
                logger.warning("atlas-flight returned no JSON output")
                raise AtlasSandboxUnavailableError(
                    "ATLAS_EMPTY_RESPONSE",
                    "Atlas Sandbox returned no usable response.",
                )
            envelope = _json.loads(line.splitlines()[-1])
            self.last_cli_envelope = {
                "status": envelope.get("status"),
                "code": envelope.get("code"),
            }
            data = envelope.get("data")
            if args == ["auth", "status"]:
                provider = data if isinstance(data, dict) else {}
                details = envelope.get("details")
                details = details if isinstance(details, dict) else {}
                # Cache only the allowlisted capability surface. Provider
                # auth payloads may contain account metadata that must never
                # enter public state or logs.
                self._capability_status = {
                    "search_available": bool(
                        provider.get("search_available", False)),
                    "verification_available": bool(
                        provider.get("verification_available", False)),
                    "order_creation_available": bool(
                        provider.get("order_creation_available", False)),
                    "payment_available": bool(
                        provider.get("payment_available", False)),
                    "ticketing_available": bool(
                        provider.get("ticketing_available", False)),
                    "blocker_code": (
                        provider.get("blocker_code")
                        or provider.get("ticketing_blocker")
                        or details.get("ticketing_blocker")
                        or (envelope.get("code")
                            if envelope.get("status") != "success" else None)
                    ),
                    "activation_url": (
                        provider.get("ticketing_activation_url")
                        or provider.get("activation_url")
                        or details.get("ticketing_activation_url")
                        or details.get("activation_url")
                    ),
                }
            if envelope.get("status") == "action_required":
                if (envelope.get("code") == "PRICE_CONFIRMATION_REQUIRED"
                        and isinstance(data, dict)):
                    return data
                details = envelope.get("details") or {}
                blocker = str(details.get("ticketing_blocker") or "").strip()
                if blocker or envelope.get("code") == "SUBSCRIPTION_REQUIRED":
                    raise AtlasTicketingUnavailableError(
                        blocker or "TICKETING_ACTIVATION_REQUIRED",
                        "Atlas Sandbox ticketing is not activated for this account.",
                    )
                raise AtlasSandboxUnavailableError(
                    str(envelope.get("code") or "ATLAS_ACTION_REQUIRED"),
                    "Atlas Sandbox requires an account action before this request can continue.",
                )
            if envelope.get("status") == "success" and isinstance(data, dict):
                return data
            logger.warning(
                "atlas-flight request failed code=%s",
                envelope.get("code"),
            )
            raise AtlasSandboxUnavailableError(
                str(envelope.get("code") or "ATLAS_REQUEST_FAILED"),
                "Atlas Sandbox request could not be completed.",
            )
        except FileNotFoundError:
            logger.warning("atlas-flight binary not found")
            raise AtlasSandboxUnavailableError(
                "ATLAS_CLI_UNAVAILABLE",
                "Atlas Sandbox CLI is unavailable.",
            )
        except AtlasProviderError:
            raise
        except (_json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning("atlas-flight returned malformed JSON")
            raise AtlasMalformedResponseError(
                "ATLAS_MALFORMED_RESPONSE",
                "Atlas Sandbox returned a malformed response.",
            ) from exc
        except Exception as exc:  # noqa: BLE001 — CLI bridge must never break the API
            logger.warning("atlas-flight CLI failed (%s)", type(exc).__name__)
            raise AtlasSandboxUnavailableError(
                "ATLAS_REQUEST_FAILED",
                "Atlas Sandbox request could not be completed.",
            ) from exc

    async def cli_search_flights(
        self, origin: str, destination: str, date: str, adults: int, currency: str
    ) -> List[Dict[str, Any]]:
        """Flight search through the authenticated Atlas Sandbox CLI.

        Provider failures raise a typed error; no runtime mock fallback exists.
        """
        data = await self._run_cli(
            [
                "search",
                "--origin", origin,
                "--destination", destination,
                "--depart", date,
                "--adults", str(adults),
                "--currency", currency,
            ]
        )
        # The success envelope may carry the offer list directly or nested;
        # normalize the official CLI payload defensively.
        offers = data if isinstance(data, list) else None
        if offers is None and isinstance(data, dict):
            for key in ("offers", "results", "items", "flights"):
                if isinstance(data.get(key), list):
                    offers = data[key]
                    break
        if offers is None:
            raise AtlasMalformedResponseError(
                "ATLAS_OFFERS_MISSING",
                "Atlas Sandbox response did not contain an offer list.",
            )
        search_id = data.get("search_id") if isinstance(data, dict) else None
        if search_id is None:
            return offers
        return [
            {"search_id": search_id, **offer}
            if isinstance(offer, dict) else offer
            for offer in offers
        ]

    async def get_flight_status(self, flight_number: str, date: str) -> Dict[str, Any]:
        """Report the honest boundary: the Atlas CLI has no status command."""
        clean_code = flight_number.upper().replace(" ", "").replace("-", "")
        return {
            "flight_number": clean_code,
            "airline_code": clean_code[:2],
            "status": "UNKNOWN",
            "reason": "Flight status is not available from the Atlas Sandbox CLI",
        }

    async def get_demo_flight_status(
        self, flight_number: str, date: str
    ) -> Dict[str, Any]:
        """Explicit fictional disruption fixtures for the labeled demo flow."""
        clean_code = flight_number.upper().replace(" ", "").replace("-", "")
        
        disruptions = {
            "TG303": {
                "flight_number": "TG303",
                "airline_code": "TG",
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
                "airline_code": "FD",
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
                "airline_code": "SQ",
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
            },
            "AF198": {
                "flight_number": "AF198",
                "airline_code": "AF",
                "carrier": "Air France",
                "origin": "CDG",
                "origin_airport": "Charles de Gaulle Airport (CDG)",
                "destination": "BKK",
                "destination_airport": "Suvarnabhumi Airport (BKK)",
                "scheduled_departure": f"{date} 13:45",
                "scheduled_arrival": f"{date} 06:10",
                "status": "CANCELLED",
                "reason": "Crew Duty Time Limits Exceeded",
                "affected_passengers": 290,
                "gate": "K32",
                "terminal": "Terminal 2E",
                "aircraft": "Boeing 777-300ER",
                "compensation_amount_usd": 650.0
            }
        }
        
        return disruptions.get(clean_code, {
            "flight_number": clean_code,
            "airline_code": clean_code[:2],
            "status": "UNKNOWN",
            "reason": "Flight status unavailable in Atlas Sandbox",
        })

    # Carrier code -> marketing name for offers returned by the live CLI
    CARRIER_NAMES = {
        "TR": "Scoot", "TG": "Thai Airways", "8M": "Myanmar Airways International",
        "SQ": "Singapore Airlines", "FD": "Thai AirAsia", "AK": "AirAsia",
        "SL": "Thai Lion Air", "VZ": "Thai Vietjet", "QH": "Lao Airlines",
        "PG": "Bangkok Airways", "WE": "Thai Smile", "EK": "Emirates",
        "QR": "Qatar Airways", "LH": "Lufthansa", "BA": "British Airways",
        "AF": "Air France", "KL": "KLM", "CX": "Cathay Pacific", "MH": "Malaysia Airlines",
        "VN": "Vietnam Airlines", "PR": "Philippine Airlines", "GA": "Garuda Indonesia",
        "KE": "Korean Air", "OZ": "Asiana", "NH": "ANA", "JL": "Japan Airlines",
        "TK": "Turkish Airlines", "AI": "Air India", "UL": "SriLankan", "BG": "Biman",
        "CA": "Air China", "MU": "China Eastern", "CZ": "China Southern", "UO": "HK Express",
        "5J": "Cebu Pacific", "JT": "Lion Air", "ID": "Batik Air", "KT": "Citilink",
    }

    @staticmethod
    def _fmt_cli_time(raw: Any) -> str:
        """'202608250905' -> '2026-08-25 09:05'; passes through other formats."""
        s = str(raw or "")
        if len(s) == 12 and s.isdigit():
            return f"{s[0:4]}-{s[4:6]}-{s[6:8]} {s[8:10]}:{s[10:12]}"
        return s

    def _normalize_cli_offer(
        self, o: Dict[str, Any], rate: float, symbol: str,
        display_currency: str = "USD", passengers: int = 1,
    ) -> Dict[str, Any]:
        """Map a live atlas-flight CLI offer onto the app's FlightOffer shape."""
        offer_id = str(o.get("offer_id") or "").strip()
        if not offer_id:
            raise AtlasMalformedResponseError(
                "ATLAS_OFFER_ID_MISSING",
                "Atlas Sandbox returned an offer without an identifier.",
            )
        segments = o.get("segments") or []
        first = segments[0] if segments else {}
        last = segments[-1] if segments else {}
        carrier = (first.get("carrier") or "").upper()
        total = o.get("total_price")
        cabin = first.get("cabin_class")
        cabin_name = {1: "ECONOMY", 2: "PREMIUM_ECONOMY", 3: "BUSINESS", 4: "FIRST"}.get(
            cabin if isinstance(cabin, int) else None, str(cabin or "ECONOMY").upper()
        )
        duration = sum(int(s.get("duration_minutes") or 0) for s in segments) or None
        return {
            "offer_id": offer_id,
            "search_id": o.get("search_id"),
            "airline": self.CARRIER_NAMES.get(carrier, carrier or "Unknown Carrier"),
            "airline_code": carrier,
            "flight_number": first.get("flight_number") or "",
            "origin": first.get("departure_airport", ""),
            "destination": last.get("arrival_airport", ""),
            "departure_time": self._fmt_cli_time(first.get("departure_time")),
            "arrival_time": self._fmt_cli_time(last.get("arrival_time")),
            "duration_minutes": duration,
            "price_usd": float(total) if isinstance(total, (int, float)) else 0.0,
            "price_converted": round(float(total) * rate, 2) if isinstance(total, (int, float)) else 0.0,
            "price_amount": round(float(total) * rate, 2) if isinstance(total, (int, float)) else 0.0,
            "currency": display_currency,
            "currency_symbol": symbol,
            "cabin_class": cabin_name,
            "seats_available": 9,
            "alliance": "",
            "stops": max(0, len(segments) - 1),
            "via": [s.get("departure_airport") for s in segments[1:] if s.get("departure_airport")],
            "bookable": bool(o.get("bookable")),
            "price_status": o.get("price_status", ""),
            # Atlas CLI `total_price` is already the total for every traveler
            # in the search. Downstream normalization must not multiply it.
            "price_scope": "trip_total",
            "passenger_count": passengers,
        }

    async def search_flights(
        self, origin: str, destination: str, date: str, passengers: int = 1, cabin_class: str = "ECONOMY", currency: str = "USD"
    ) -> List[Dict[str, Any]]:
        """Search available flights across 140+ airlines on Atlas GDS with multi-currency conversion."""
        # Live inventory only exists for future dates; clamp stale/same-day inputs
        try:
            today = datetime.date.today().isoformat()
            if date and date <= today:
                date = tomorrow_iso()
        except (TypeError, ValueError):
            pass
        origin = origin.upper().strip()
        destination = destination.upper().strip()
        upper = currency.upper().strip()
        if upper not in self.RATES:
            raise ValueError(
                f"Unsupported display currency: {upper}. Supported values: "
                f"{', '.join(sorted(self.RATES))}"
            )
        # Atlas Sandbox only (official atlas-flight CLI). No runtime mock
        # fallback exists.
        # Always query the CLI in USD: Atlas returns total_price in the requested
        # currency, so requesting the display currency here would double-convert.
        # Display-currency conversion happens locally via RATES below.
        cli_offers = await self.cli_search_flights(
            origin=origin, destination=destination, date=date, adults=passengers, currency="USD"
        )
        if not cli_offers:
            raise AtlasSandboxUnavailableError(
                "ATLAS_NO_OFFERS",
                "Atlas Sandbox returned no flight offers for this route.",
            )
        rate = self.RATES[upper]
        symbol = self.SYMBOLS[upper]
        normalized = [
            self._normalize_cli_offer(
                o, rate, symbol, display_currency=upper,
                passengers=passengers,
            )
            for o in cli_offers
        ]
        exact = [
            offer for offer in normalized
            if offer["origin"].upper() == origin
            and offer["destination"].upper() == destination
        ]
        if not exact:
            raise AtlasSandboxUnavailableError(
                "ATLAS_EXACT_ROUTE_UNAVAILABLE",
                "Atlas Sandbox returned no offers for the exact airports requested.",
            )
        return exact

    async def demo_search_flights(
        self, origin: str, destination: str, date: str,
        currency: str = "USD",
    ) -> List[Dict[str, Any]]:
        """Explicit fictional offers for labeled simulation flows only."""
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
        """Create a real Atlas Sandbox booking context for an offer."""
        data = await self._run_cli(
            ["offer", "verify", "--offer-id", offer_id]
        )
        booking_id = str(data.get("booking_id") or "").strip()
        if not booking_id:
            raise AtlasMalformedResponseError(
                "ATLAS_BOOKING_ID_MISSING",
                "Atlas Sandbox fare verification returned no booking context.",
            )
        price_change = str(data.get("price_change") or "unknown")
        return {
            "verified": price_change != "increased",
            "offer_id": offer_id,
            "booking_id": booking_id,
            "previous_price": data.get("previous_price"),
            "current_price": data.get("current_price"),
            "currency": data.get("currency"),
            "price_change": price_change,
            "price_confirmation_required": price_change == "increased",
            "requirements": data.get("requirements") or {},
            "travelers": data.get("travelers") or [],
            "segments": data.get("segments") or [],
            "baggage_supported": bool(data.get("baggage_supported")),
            "seat_supported": bool(data.get("seat_supported")),
            "verified_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

    async def confirm_price(self, booking_id: str) -> Dict[str, Any]:
        """Confirm a previously verified increased fare by opaque booking ID."""
        data = await self._run_cli(
            ["booking", "confirm-price", "--booking-id", booking_id]
        )
        returned_id = str(data.get("booking_id") or "").strip()
        if not returned_id or returned_id != booking_id:
            raise AtlasMalformedResponseError(
                "ATLAS_BOOKING_ID_MISMATCH",
                "Atlas Sandbox price confirmation returned an invalid booking context.",
            )
        current_price = data.get("current_price")
        currency = str(data.get("currency") or "").upper().strip()
        if (not isinstance(current_price, (int, float))
                or isinstance(current_price, bool)
                or not math.isfinite(float(current_price))
                or currency not in self.RATES):
            raise AtlasMalformedResponseError(
                "ATLAS_CONFIRMED_PRICE_INVALID",
                "Atlas Sandbox price confirmation returned no valid explicit "
                "amount and currency.",
            )
        return {
            "verified": True,
            "offer_id": data.get("offer_id"),
            "booking_id": returned_id,
            "previous_price": data.get("previous_price"),
            "current_price": float(current_price),
            "currency": currency,
            "price_change": str(data.get("price_change") or "increased"),
            "price_confirmation_required": False,
            "price_confirmed": True,
            "requirements": data.get("requirements") or {},
            "travelers": data.get("travelers") or [],
            "segments": data.get("segments") or [],
            "baggage_supported": bool(data.get("baggage_supported")),
            "seat_supported": bool(data.get("seat_supported")),
            "verified_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

    async def get_seat_map(self, flight_number: str) -> Dict[str, Any]:
        """Return the explicit demo seat-map fixture."""
        return {
            "provenance": "explicit_demo_simulation",
            "simulated": True,
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
        """Return the explicit demo baggage-transfer fixture."""
        return {
            "provenance": "explicit_demo_simulation",
            "simulated": True,
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
        self, booking_id: str, passenger: Dict[str, Any],
        baggage_addon: Optional[str] = None, seat_selected: str = "12A"
    ) -> Dict[str, Any]:
        """Fail closed until Atlas ticketing and an approved PII flow exist."""
        status = await self._run_cli(["auth", "status"])
        if not status.get("ticketing_available"):
            raise AtlasTicketingUnavailableError(
                str(status.get("ticketing_blocker")
                    or "ATLAS_TICKETING_UNAVAILABLE"),
                "Atlas Sandbox ticketing is not activated for this account.",
            )
        raise AtlasTravelerDataRequiredError(
            "ATLAS_TRAVELER_DATA_REQUIRED",
            "Atlas Sandbox order creation requires an approved ephemeral "
            "traveler-data flow; no order was created.",
        )

    async def search_transit_hotels(self, airport_code: str = "BKK") -> List[Dict[str, Any]]:
        """Search Booking.com / Agoda partner emergency transit hotels near airport."""
        return [
            {
                "voucher_id": "HTL-NOVOTEL-8921",
                "hotel_name": "Novotel Bangkok Suvarnabhumi Airport Hotel",
                "stars": 4,
                "location": "Directly connected to Main Terminal via Air-conditioned Underground Walkway",
                "airside_no_visa": False,
                "check_in": "Today 11:30 AM",
                "check_out": "Tomorrow 07:00 AM (Overnight 19.5 Hours)",
                "room_type": "Deluxe King Room (Soundproofed Airfield View)",
                "amenities": [
                    "Free International Breakfast Buffet & Dinner",
                    "24-Hour Free Terminal Shuttle (Every 15 mins)",
                    "High-Speed Fiber WiFi (100 Mbps)",
                    "Swimming Pool & 24h Fitness Center",
                    "Late Checkout Guaranteed"
                ],
                "free_breakfast": True,
                "nightly_rate_usd": 120.00,
                "covered_by": "100% Airline Disruption Guarantee",
                "status": "PRE_APPROVED_BY_AIRLINE",
                "qr_code_token": "QR-HTL-NVTL-BKKSVN-DELUXE-8921"
            },
            {
                "voucher_id": "HTL-MIRACLE-4102",
                "hotel_name": "Miracle Transit Hotel (Airside Concourse G)",
                "stars": 4,
                "location": "Inside International Departure Concourse G (4th Floor) — No Thai Visa Needed",
                "airside_no_visa": True,
                "check_in": "Immediate Check-in",
                "check_out": "Until Rescue Flight Boarding",
                "room_type": "Airside Superior Suite (Private Shower & Daybed)",
                "amenities": [
                    "No Immigration / Visa Clearance Required",
                    "Direct Flight Gate Access (3 mins walk to Gate D4)",
                    "Complimentary Mini-bar & Hot Meals",
                    "Private Hot Rain Shower & Toiletries",
                    "Spa & Foot Massage Credit Included"
                ],
                "free_breakfast": True,
                "nightly_rate_usd": 95.00,
                "covered_by": "100% Airline Disruption Guarantee",
                "status": "PRE_APPROVED_BY_AIRLINE",
                "qr_code_token": "QR-HTL-MRCL-AIRSIDE-SUITE-4102"
            }
        ]

    async def issue_care_gift_vouchers(self, pnr: str = "ATLAS-45BAE5") -> Dict[str, Any]:
        """Issue 24/7 Disruption Care Package & Gift Vouchers (Booking.com Genius / VIP Style)."""
        return {
            "lounge_voucher": "Miracle Lounge Pass #LV-8921 (Concourse D - Gate D5)",
            "dining_credit": "$45.00 Airport Dining Voucher #DV-9012 (Valid at 32 Restaurants)",
            "grab_transfer_pass": "$20.00 Grab / Uber Airport Ride Pass #GRAB-AIRPORT-8921",
            "global_esim_data": "10GB Global 5G Roaming e-SIM #ESIM-ASIA-8921",
            "airline_compensation": "$250.00 Direct Payout Claim #CLM-2026-8941",
            "total_care_package_value_usd": 380.00,
            "status": "ACTIVE_IN_DIGITAL_WALLET"
        }
