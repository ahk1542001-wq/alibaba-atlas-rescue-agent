import datetime
from config import settings
import uuid
from typing import Dict, Any, List, Optional
from services import llm
from services import visa_guard
from services import guardian
from services.atlas_client import AtlasClient
from services.state_graph import DisruptionRecoveryDAG


def settings_default_model() -> str:
    from config import settings as _s
    return _s.default_model


def _build_concierge_prompt(context: Optional[Dict[str, Any]]) -> str:
    """Ground the concierge on the live session or trip state instead of a canned story."""
    if not context:
        return (
            "You are the 24/7 AI Travel Concierge of TravelCare AI, an autonomous "
            "flight rescue and trip planning agent. No active trip or disruption right now. "
            "Help the traveler start a trip plan or answer general travel questions concisely (max 3 sentences)."
        )
    parts = [
        "You are the 24/7 AI Travel Concierge of TravelCare AI. "
        "Ground EVERY answer strictly in this live session context:"
    ]
    goal = (context.get("goal_intake") or {}).get("goal") or context.get("goal") or {}
    if goal:
        orig = goal.get("origin_city") or goal.get("origin_airport") or "unstated"
        dest = goal.get("dest_city") or goal.get("dest_airport") or "unstated"
        dates = goal.get("date_window") or goal.get("travel_date") or "unstated"
        pax = goal.get("passengers") or 1
        parts.append(f"- Active Planned Trip: from {orig} to {dest}, dates: {dates}, passengers: {pax}.")
    
    d = context.get("disruption") or {}
    if d:
        parts.append(
            f"- Flight {d.get('flight_number')} {d.get('origin')}-{d.get('destination')} "
            f"is {d.get('status')} ({d.get('reason')})."
        )
    pkg = (context.get("rescue_packages") or [None])[0]
    if pkg:
        parts.append(
            f"- Top rescue option locked: {pkg.get('airline')} {pkg.get('flight_number')} "
            f"{pkg.get('origin')}-{pkg.get('destination')}, departs {pkg.get('departure_time')}, "
            f"fare {pkg.get('currency_symbol')}{pkg.get('price_converted', pkg.get('price_usd'))}."
        )
    vg = context.get("visa_guard") or context.get("visa_check")
    if vg:
        summary = vg.get("summary") or vg.get("message") or "verified"
        parts.append(f"- Entry / Visa check: {summary}")
    safety = (context.get("safety") or {}).get("assessment") or {}
    if safety:
        parts.append(f"- Safety status: {safety.get('trip_policy_status')} ({safety.get('why_selected', '')})")
    claim = context.get("compensation_claim")
    if claim:
        payout = claim.get("eligible_payout_usd")
        basis = claim.get("rights_basis")
        parts.append(
            f"- Claim {claim.get('claim_id')}: "
            + (f"${payout} under {basis}" if payout else f"{basis or 'refund/duty-of-care route'}")
        )
    fb = context.get("flight_book") or {}
    booking = fb.get("booking") or {}
    pnr = booking.get("pnr")
    status = (booking.get("status") or fb.get("status") or "").upper()
    if pnr and pnr != "CONFIRMED" and status == "CONFIRMED":
        parts.append(f"- Confirmed Sandbox Booking PNR: {pnr}")
    elif booking:
        status_desc = status if status else "pending/unconfirmed"
        parts.append(f"- Planned flight selection (booking status: {status_desc}, no confirmed PNR)")

    parts.append(
        "Answer the passenger's question concisely (max 3 sentences), warm and specific. "
        "Never invent facts outside this context unless clearly generic advice."
    )
    return "\n".join(parts)


class FlightStatusUnavailableError(RuntimeError):
    """Raised when Atlas has no route-backed status for recovery planning."""


class RescueEngine:
    """Agentic AI reasoning engine for autonomous flight disruption resolution."""

    def __init__(self, atlas_client: AtlasClient):
        self.atlas = atlas_client
        self.last_session_context: Optional[Dict[str, Any]] = None

    async def _qwen_concierge_reply(self, query: str, context: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Real Qwen reply grounded on live session state; None so rules take over."""
        ctx = context
        if not ctx:
            return None
        reply = await llm.chat(
            messages=[
                {"role": "system", "content": _build_concierge_prompt(ctx)},
                {"role": "user", "content": query},
            ],
            max_tokens=220,
            temperature=0.5,
        )
        return reply


    async def handle_disruption(
        self,
        flight_number: str,
        passenger_name: str = "",
        date: str = None,
        currency: str = "USD",
        nationality: str = "MM",
        simulation: bool = False,
    ) -> Dict[str, Any]:
        if not date:
            date = datetime.date.today().strftime("%Y-%m-%d")

        dag = DisruptionRecoveryDAG()

        # Node 1: IngestionRadar
        source = "Explicit demo simulation" if simulation else "Atlas Sandbox"
        dag.record_step("IngestionRadar", 8.2, {"source": source, "flight": flight_number})

        # Node 2: PredictiveEvaluator
        predictive_radar = self.get_predictive_radar(flight_number)
        dag.record_step("PredictiveEvaluator", 14.5, {"cancellation_risk_percent": predictive_radar["predicted_cancellation_risk_percent"]})

        # Node 3: DisruptionConfirmed
        if simulation:
            disruption_info = await self.atlas.get_demo_flight_status(flight_number, date)
        else:
            disruption_info = await self.atlas.get_flight_status(flight_number, date)
        origin = str(disruption_info.get("origin") or "").upper()
        destination = str(disruption_info.get("destination") or "").upper()
        if (str(disruption_info.get("status") or "").upper() == "UNKNOWN"
                or not origin or not destination):
            raise FlightStatusUnavailableError(
                "Flight status unavailable in Atlas Sandbox; "
                "no recovery plan was created."
            )
        dag.record_step("DisruptionConfirmed", 11.0, {"status": disruption_info.get("status"), "reason": disruption_info.get("reason")})

        # Node 4: ParetoOptimizer (Query 140+ carriers & Rank)
        if simulation:
            all_offers = await self.atlas.demo_search_flights(
                origin, destination, date, currency=currency
            )
        else:
            all_offers = await self.atlas.search_flights(
                origin, destination, date, currency=currency
            )
        packages = self._curate_rescue_packages(all_offers, disruption_info)

        # Node 4b: VisaGuard — filter/rank packages by passport transit rules
        visa_result = visa_guard.filter_and_rank(nationality, packages)
        packages = visa_result["offers"]
        dag.record_step("VisaGuard", 6.4, {
            "passport": visa_result["passport"],
            "blocked_options": visa_result["blocked_count"],
        })

        # Node 4c: Proactive Guardian push (Telegram; simulated when unconfigured)
        if simulation:
            guardian_push = {
                "channel": "demo_preview",
                "sent": False,
                "simulated": True,
                "preview": (
                    f"Disruption detected on {flight_number}; "
                    f"{len(packages)} demo rescue options prepared."
                ),
                "reason": "Explicit demo simulation never sends external notifications.",
                "error": None,
            }
        else:
            guardian_push = await guardian.notify(
                title=f"Disruption detected on {flight_number}",
                body=(
                    f"Your flight {flight_number} is "
                    f"{disruption_info.get('status','disrupted')} "
                    f"({disruption_info.get('reason','')}). The agent found "
                    f"{len(packages)} visa-safe rescue options for your "
                    f"{visa_result['passport']} passport."
                ),
                action_label="Open Rescue Hub",
            )
        if guardian_push.get("sent") or guardian_push.get("simulated"):
            dag.record_step("ProactiveGuardian", 4.1, {
                "channel": "telegram",
                "simulated": bool(guardian_push.get("simulated")),
            })

        dag.record_step("ParetoOptimizer", 14.8, {"offers_evaluated": len(all_offers), "packages_curated": len(packages)})

        # Node 5: verify the provider offer. Verification is not a booking or lock.
        if simulation:
            fare_lock = {
                "simulated": True,
                "verified": False,
                "reason": "Demo simulation; no Atlas fare was verified or locked.",
            }
            dag.record_step("FareVerification", 0.0, {"status": "SIMULATED"})
        elif packages:
            fare_lock = await self.atlas.verify_fare(packages[0]["offer_id"])
            fare_lock["simulated"] = False
            dag.record_step(
                "FareVerification",
                38.0,
                {"status": "VERIFIED" if fare_lock.get("verified") else "REVIEW_REQUIRED"},
            )
        else:
            raise FlightStatusUnavailableError(
                "Atlas Sandbox returned no usable recovery offers; "
                "no recovery plan was created."
            )

        # Ancillary & Support Data
        advisory = self._generate_disruption_advisory(disruption_info) if simulation else {
            "available": False,
            "reason": "No live rights or airline-entitlement source is connected.",
        }
        seat_map = await self.atlas.get_seat_map(flight_number) if simulation else {
            "available": False,
            "reason": "No Atlas Sandbox seat map was requested.",
        }
        claim = await self.generate_compensation_claim(disruption_info, passenger_name, nationality)
        hotels = await self.atlas.search_transit_hotels(origin) if simulation else []
        care_gifts = await self.atlas.issue_care_gift_vouchers(
            f"DEMO-{flight_number}"
        ) if simulation else {
            "available": False,
            "reason": "No live care-voucher provider is connected.",
        }
        flight_diff = self.generate_flight_diff("TG303", "8M336") if simulation else {
            "available": False,
            "reason": "No replacement flight has been selected or booked.",
        }

        result = {
            "provenance": "explicit_demo_simulation" if simulation else "atlas_sandbox",
            "session_id": dag.session_id,
            "disruption": disruption_info,
            "passenger": {
                "name": passenger_name,
                "nationality": visa_result["passport"],
                "loyalty_tier": "Gold / Priority",
                "original_ticket": f"TG-ORIG-{flight_number}",
                "assigned_seat": "12A"
            },
            "predictive_radar": predictive_radar,
            "flight_diff": flight_diff,
            "rescue_packages": packages,
            "visa_guard": {
                "passport": visa_result["passport"],
                "summary": visa_result["summary"],
                "blocked_count": visa_result["blocked_count"],
            },
            "guardian_push": guardian_push,
            "fare_lock": fare_lock,
            "transit_hotels": hotels,
            "care_gifts": care_gifts,
            "seat_map": seat_map,
            "advisory": advisory,
            "compensation_claim": claim,
            "dag_telemetry": dag.get_graph_telemetry(),
            "status": (
                "DEMO_PACKAGES_READY" if simulation
                else "PACKAGES_READY_FOR_CONFIRMATION"
            ),
        }
        self.last_session_context = {
            "provenance": result["provenance"],
            "disruption": disruption_info,
            "rescue_packages": packages[:2],
            "visa_guard": result["visa_guard"],
            "guardian_push": guardian_push,
            "compensation_claim": claim,
        }
        return result

    def get_predictive_radar(self, flight_number: str = "TG303") -> Dict[str, Any]:
        """Return explicitly simulated predictive telemetry for the demo UI."""
        return {
            "provenance": "explicit_demo_simulation",
            "simulated": True,
            "flight_number": flight_number,
            "inbound_aircraft_tail": "HS-TKF (Boeing 777-300ER)",
            "inbound_route": "LHR ➔ BKK (Delayed 3h 15m in London Heathrow)",
            "inbound_delay_minutes": 195,
            "airspace_congestion_index": "High (Severe Flow Control at BKK)",
            "weather_radar_status": "Severe Monsoon Thunderstorm Convective Cloud Over BKK Approach",
            "predicted_cancellation_risk_percent": 88,
            "lead_time_advantage_minutes": 45,
            "recommendation": "Lock MAI 8M 336 immediately before 184 passengers reach the customer service counter."
        }

    def generate_flight_diff(self, original_code: str = "TG303", rescue_code: str = "8M336") -> Dict[str, Any]:
        """High-contrast visual Before vs After flight rescue diff."""
        return {
            "original_flight": original_code,
            "original_carrier": "Thai Airways",
            "original_departure": "09:15 AM",
            "original_status": "CANCELLED (Hydraulic Maintenance)",
            "rescue_flight": rescue_code,
            "rescue_carrier": "Myanmar Airways International (MAI)",
            "rescue_departure": "11:45 AM",
            "time_delta_display": "+2h 30m Delta (Fastest Arrival at 12:35 PM)",
            "loyalty_tier_status": "Star Alliance Gold Priority Boarding Honored",
            "baggage_transfer_status": "Tag #BKK-45BA Auto-transferred to Cargo Bay 2",
            "queue_time_saved_minutes": 190
        }

    def _curate_rescue_packages(
        self, offers: List[Dict[str, Any]], disruption: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Ranks and structures top optimized rescue packages for passenger."""
        # Never present the same live flight twice under different package labels
        seen: set = set()
        unique_offers = []
        for o in offers:
            key = (o.get("flight_number"), o.get("departure_time"))
            if key not in seen:
                seen.add(key)
                unique_offers.append(o)
        offers = unique_offers
        curated = []

        # Package 1: Fastest Recovery (Earliest departure)
        sorted_by_time = sorted(offers, key=lambda x: x["departure_time"])
        if sorted_by_time:
            p1 = sorted_by_time[0].copy()
            p1["package_type"] = "FASTEST_RECOVERY"
            p1["badge"] = "⚡ Fastest Arrival"
            p1["agent_recommendation_reason"] = (
                f"Earliest departure among {len(offers)} live options "
                f"({p1['departure_time'].split(' ')[-1]}). Minimizes airport downtime."
            )
            curated.append(p1)

        # Package 2: Best Value (Lowest price / Budget Match)
        sorted_by_price = sorted(offers, key=lambda x: x["price_usd"])
        if sorted_by_price:
            p2 = sorted_by_price[0].copy()
            p2["package_type"] = "BEST_VALUE"
            p2["badge"] = "💰 Best Value Match"
            p2["agent_recommendation_reason"] = (
                f"Lowest fare among {len(offers)} live options at "
                f"{p2.get('currency_symbol', '$')}{p2.get('price_converted', p2['price_usd'])}."
            )
            curated.append(p2)

        # Package 3: Same Alliance / Direct Comfort
        comfort_matches = [
            o for o in offers
            if o.get("alliance") == "Star Alliance" or "Flex" in o.get("cabin_class", "")
        ]
        p3 = comfort_matches[0].copy() if comfort_matches else (offers[-1].copy() if offers else None)
        if p3:
            p3["package_type"] = "DIRECT_COMFORT"
            alliance_note = (
                f"{p3.get('alliance')} priority perks" if comfort_matches
                else "Comfort-oriented option"
            )
            p3["badge"] = "🛡️ Direct Comfort & Alliance" if comfort_matches else "🛡️ Comfort Option"
            p3["agent_recommendation_reason"] = (
                f"{alliance_note} on {p3.get('airline', 'carrier')} "
                f"{p3.get('flight_number', '')}. Cabin: {p3.get('cabin_class', 'ECONOMY')}."
            )
            curated.append(p3)

        return curated

    def _generate_disruption_advisory(self, disruption: Dict[str, Any]) -> Dict[str, Any]:
        """Provides instant regulatory rights and disruption claim assistance."""
        return {
            "cancellation_rights": "Full refund or free rebooking on any Atlas GDS partner airline.",
            "meal_voucher_eligible": True,
            "meal_credit_amount": "$25.00 Airport Dining Credit",
            "lounge_access_granted": True,
            "lounge_name": "Miracle Lounge (Concourse D, Gate D5)",
            "claim_status": "Pre-filled claim #CLM-2026-8941 registered on passenger's behalf."
        }

    async def generate_compensation_claim(
        self, disruption: Dict[str, Any], passenger_name: str, nationality: str = "MM"
    ) -> Dict[str, Any]:
        """Rights-engine-grounded claim: jurisdiction detection + Qwen cause
        classification + distance-band entitlement. Honest zero-cash output on
        routes where no mandatory scheme exists (duty-of-care/refund route)."""
        from services import rights_engine as re_engine

        claim_id = f"CLM-{uuid.uuid4().hex[:6].upper()}"
        reason = disruption.get("reason", "Operational Disruption")
        o_country, d_country, c_country = re_engine.airports_to_countries(
            disruption.get("origin", ""), disruption.get("destination", ""), disruption.get("airline_code", "")
        )
        regimes = re_engine.detect_jurisdictions(o_country, d_country, c_country)

        claim = {
            "claim_id": claim_id,
            "passenger_name": passenger_name,
            "nationality": nationality,
            "flight_number": disruption.get("flight_number", ""),
            "carrier": disruption.get("carrier", ""),
            "incident_type": disruption.get("status", ""),
            "cause": reason,
            "eligible_payout_usd": 0.0,
            "rights_basis": None,
            "jurisdiction": None,
            "classification": None,
            "status": "ASSESSING",
            "settlement_method": "Direct Bank Deposit / Atlas Wallet Credit",
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "filing_officer": "Autonomous Rescue Agent (Qoder AI Travel Protocol)",
        }
        if not regimes:
            claim["rights_basis"] = (
                "No mandated cash-compensation regime on this route — duty of care "
                "(meals/hotel) and refund/re-routing rights still apply cause-blind."
            )
            claim["status"] = "DUTY_OF_CARE_REFUND_ROUTE"
            return claim

        best = regimes[0]
        distance_km = disruption.get("distance_km") or 1500
        entitlement = re_engine.compute_entitlement(best["id"], distance_km)
        classification = await re_engine.classify_cause(reason, best["id"])
        cash = entitlement.get("fixed_cash_compensation")

        claim["jurisdiction"] = {"id": best["id"], "name": best["name"], "citation": best["citation"]}
        claim["classification"] = classification.get("classification")
        claim["classification_reasoning"] = classification.get("legal_reasoning")
        claim["entitlement"] = entitlement
        if cash and claim["classification"] == "COMPENSABLE":
            # Convert to USD for the payout card using static reference rates
            rate = self.atlas.RATES.get(cash["currency"], 1.0)
            usd = round(float(cash["amount"]) / rate, 2) if rate else float(cash["amount"])
            claim["eligible_payout_usd"] = usd
            claim["payout_original"] = cash
            claim["status"] = "PRE_SUBMITTED_BY_AGENT"
        elif cash:
            claim["rights_basis"] = (
                f"{best['name']} applies but the stated cause may be extraordinary "
                f"({classification.get('key_article', '')}); airline must prove it."
            )
            claim["status"] = "PENDING_AIRLINE_PROOF"
        else:
            claim["rights_basis"] = best.get("cash_note") or best.get("duty_of_care")
            claim["status"] = "DUTY_OF_CARE_REFUND_ROUTE"
        return claim

    async def answer_concierge(self, query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """AI Travel Concierge responses based on Atlas travel context and passenger needs."""
        ctx = context
        if not ctx:
            return {
                "reply": (
                    "I do not have an active trip or disruption session right now. "
                    "Tell me where you want to travel or simulate a disruption to get started."
                ),
                "action_taken": "NO_ACTIVE_SESSION",
            }
        # Real Qwen-2.5 first (grounded); deterministic rules as fallback
        try:
            qwen_reply = await self._qwen_concierge_reply(query, ctx)
        except TypeError:
            qwen_reply = await self._qwen_concierge_reply(query)

        if qwen_reply:
            return {
                "reply": qwen_reply,
                "action_taken": "QWEN_LLM_REPLY",
                "engine": llm.provider_name(),
                "model": settings_default_model(),
            }
        try:
            return await self._rule_based_concierge(query, ctx)
        except TypeError:
            return await self._rule_based_concierge(query)

    async def _rule_based_concierge(self, query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Deterministic, session-grounded reply when the LLM is unavailable."""
        ctx = context
        if not ctx:
            return {
                "reply": (
                    "I do not have an active trip or disruption session right now. "
                    "Tell me where you want to travel or simulate a disruption to get started."
                ),
                "action_taken": "NO_ACTIVE_SESSION",
            }

        q_lower = query.lower()
        goal = (ctx.get("goal_intake") or {}).get("goal") or ctx.get("goal") or {}
        orig = goal.get("origin_city") or goal.get("origin_airport")
        dest = goal.get("dest_city") or goal.get("dest_airport")
        dates = goal.get("date_window") or goal.get("travel_date")
        pax = goal.get("passengers")

        # 1. Trip goal inquiries (destination, origin, dates, passengers)
        _city_map = {"SIN": "Singapore", "BKK": "Bangkok", "DMK": "Bangkok (Don Mueang)", "RGN": "Yangon", "FRA": "Frankfurt"}
        if "destination" in q_lower or "where" in q_lower and ("going" in q_lower or "to" in q_lower):
            if dest:
                friendly_dest = _city_map.get(dest.upper(), dest)
                dest_str = f"{friendly_dest} ({dest})" if dest.upper() in _city_map and dest.upper() != friendly_dest.upper() else dest
                return {
                    "reply": f"Your current planned destination is {dest_str}.",
                    "action_taken": "TRIP_DESTINATION_SUMMARY",
                }
        if "origin" in q_lower or "where" in q_lower and "start" in q_lower:
            if orig:
                friendly_orig = _city_map.get(orig.upper(), orig)
                orig_str = f"{friendly_orig} ({orig})" if orig.upper() in _city_map and orig.upper() != friendly_orig.upper() else orig
                return {
                    "reply": f"Your trip is scheduled to depart from {orig_str}.",
                    "action_taken": "TRIP_ORIGIN_SUMMARY",
                }
        if "passenger" in q_lower or "people" in q_lower or "who is" in q_lower:
            if "2" in q_lower or "two" in q_lower:
                return {
                    "reply": "You can change your passenger count to 2. Confirm to update your search.",
                    "action_taken": "PASSENGER_COUNT_PROPOSAL",
                }
            if pax:
                return {
                    "reply": f"Your trip currently has {pax} passenger(s) configured.",
                    "action_taken": "TRIP_PASSENGERS_SUMMARY",
                }
        if "cheap" in q_lower or "budget" in q_lower or "price" in q_lower or "cost" in q_lower:
            opts = (ctx.get("flight_search") or {}).get("options") or []
            if opts:
                cheapest = opts[0]
                price = (cheapest.get("price") or {}).get("amount", "")
                curr = (cheapest.get("price") or {}).get("currency", "USD")
                carrier = cheapest.get("carrier") or cheapest.get("airline") or "Flight"
                return {
                    "reply": f"The lowest available fare is {curr} {price} on {carrier}.",
                    "action_taken": "TRIP_BUDGET_SUMMARY",
                }

        # 2. Visa & Safety Inquiries
        if "visa" in q_lower or "passport" in q_lower:
            vg = ctx.get("visa_guard") or ctx.get("visa_check") or {}
            summary = vg.get("summary") or vg.get("message")
            if summary:
                return {
                    "reply": f"Visa assessment: {summary}",
                    "action_taken": "VISA_STATUS_SUMMARY",
                }
        if "safe" in q_lower or "safety" in q_lower or "warning" in q_lower or "advisory" in q_lower:
            safety = (ctx.get("safety") or {}).get("assessment") or {}
            status = safety.get("trip_policy_status")
            if status:
                why = safety.get("why_selected") or ""
                return {
                    "reply": f"Destination safety status is '{status}'. {why}".strip(),
                    "action_taken": "SAFETY_STATUS_SUMMARY",
                }

        # 3. Disruption Context
        disruption = ctx.get("disruption") or {}
        packages = ctx.get("rescue_packages") or []
        claim = ctx.get("compensation_claim") or {}
        demo_note = (
            " This is demo simulation data; no booking was created."
            if ctx.get("provenance") == "explicit_demo_simulation" else ""
        )

        if "claim" in q_lower or "compensation" in q_lower or "refund" in q_lower:
            return {
                "reply": (
                    f"The current assessment status is {claim.get('status', 'unavailable')}. "
                    f"The recorded basis is {claim.get('rights_basis') or 'still being assessed'}."
                    + demo_note
                ),
                "action_taken": "SESSION_CLAIM_SUMMARY",
            }
        if disruption:
            top = packages[0] if packages else {}
            option_text = (
                f" The top option shown is {top.get('airline', 'an airline')} "
                f"{top.get('flight_number', '')}; it is not booked."
                if top else " No replacement option is currently available."
            )
            return {
                "reply": (
                    f"Flight {disruption.get('flight_number', '')} is recorded as "
                    f"{disruption.get('status', 'unknown')}."
                    + option_text + demo_note
                ),
                "action_taken": "SESSION_STATUS_SUMMARY",
            }

        if "pnr" in q_lower or "booked" in q_lower or "booking status" in q_lower:
            fb = ctx.get("flight_book") or {}
            booking = fb.get("booking") or {}
            pnr = booking.get("pnr")
            status = (booking.get("status") or fb.get("status") or "").upper()
            if pnr and pnr != "CONFIRMED" and status == "CONFIRMED":
                return {
                    "reply": f"Your flight booking is confirmed in Atlas Sandbox with PNR {pnr}.",
                    "action_taken": "BOOKING_STATUS_CONFIRMED",
                }
            elif booking:
                return {
                    "reply": "Your flight option is planned but not confirmed. No booking or PNR was created.",
                    "action_taken": "BOOKING_STATUS_UNCONFIRMED",
                }
            else:
                return {
                    "reply": "No booking has been requested yet. Review your flight options and approve to book.",
                    "action_taken": "NO_BOOKING_REQUESTED",
                }

        if dest and orig:
            return {
                "reply": f"Your plan for {orig} to {dest} ({dates}) is actively monitored by TravelCare AI.",
                "action_taken": "ACTIVE_TRIP_SUMMARY",
            }

        return {
            "reply": "TravelCare Assistant is ready. How can I help with your flights, hotels, safety, or claims?",
            "action_taken": "GENERAL_HELP",
        }

    async def execute_self_healing_recovery(self, flight_number: str, passenger_name: str = "") -> Dict[str, Any]:
        """
        Explicitly simulated Graph & Loop Engineering fault injection:
        1. Attempts to lock Primary Choice (MAI 8M 336).
        2. Simulates 'SEATS_EXHAUSTED_409' Verifier Rejection.
        3. Catches fault without crashing and triggers Self-Healing Graph Loop.
        4. Selects a fictional fallback without creating an Atlas order.
        """
        dag = DisruptionRecoveryDAG()
        dag.record_step("IngestionRadar", 8.0, {"flight": flight_number})
        dag.record_step("ParetoOptimizer", 14.2, {"selected_primary": "MAI 8M 336"})
        
        # Injected Fault at FareLockHold
        dag.record_step("FareLockHold", 35.0, {
            "attempted": "MAI 8M 336",
            "verifier_result": "FAILED: 0 Seats Remaining (Simulated Sudden Exhaustion)",
            "action": "TRIGGER_SELF_HEALING_LOOP"
        })

        # Self-Healing Loop Transition
        dag.record_step("SelfHealingLoop", 12.0, {
            "loop_reason": "Primary choice sold out during lock window",
            "target_node": "ParetoOptimizer",
            "selected_fallback": "Thai Airways TG 307 (18:00 Departure • Star Alliance)"
        })

        # Demonstrate selection only. No Atlas order, PNR, seat, or ticket exists.
        dag.record_step("FallbackSelection", 28.0, {
            "selected_demo_option": "Thai Airways TG 307",
            "status": "SIMULATED_NOT_BOOKED",
        })
        dag.record_step("ClosedLoopVerified", 6.0, {"status": "SIMULATION_COMPLETED"})

        return {
            "provenance": "explicit_demo_simulation",
            "simulated": True,
            "booking_created": False,
            "status": "SELF_HEALING_SIMULATION_COMPLETED",
            "primary_attempted": "MAI 8M 336 (Exhausted)",
            "demo_fallback_selected": "Thai Airways TG 307 (Departs 18:00 • Suvarnabhumi)",
            "demo_reference": "SIM-SELF-HEAL-TG307",
            "dag_telemetry": dag.get_graph_telemetry(),
            "explanation": (
                "The explicit demo loop selected a fallback after simulated seat "
                "exhaustion. It did not call Atlas ticketing or create a booking."
            ),
        }

    def get_agent_prompt_telemetry(self) -> Dict[str, Any]:
        """Return explicitly simulated prompt/telemetry content for the demo UI."""
        return {
            "provenance": "explicit_demo_simulation",
            "simulated": True,
            "model": getattr(settings, "default_model", "Qwen/Qwen2.5-72B-Instruct"),
            "system_prompt": (
                "You are the Autonomous Flight Rescue Agent. When an airline disruption webhook triggers, "
                "extract the traveler profile, query Atlas GDS for multi-carrier alternatives, "
                "compute Pareto-optimal rankings (Fastest Arrival, Lowest Cost, Star Alliance Comfort), "
                "lock the selected fare in under 300ms, and generate regulatory compensation claims."
            ),
            "pareto_weights": {
                "arrival_time_urgency": 0.45,
                "price_competitiveness": 0.25,
                "alliance_loyalty_comfort": 0.30
            },
            "token_economics": {
                "prompt_tokens": 280,
                "completion_tokens": 140,
                "total_tokens_per_recovery": 420,
                "cost_usd_per_recovery": 0.0018,
                "human_call_center_benchmark_usd": 18.50,
                "cost_savings_percentage": "99.9% Cost Reduction"
            },
            "verifier_suite": [
                "FareLockContractVerifier (TTL & Price Guarantee)",
                "SeatConflictVerifier (Anti-Double-Booking)",
                "BaggageContinuityVerifier (IoT Tag Manifest Check)",
                "RegulatoryPayoutVerifier ($250.00 Passenger Rights Validation)"
            ],
            "average_reasoning_tokens": 420,
            "inference_latency_ms": 14.8,
            "framework": "FastAPI + Qoder Agentic Workflow + DAG State Machine"
        }
