"""visa_check skill — §4 S6 (G2 behavior).

Baseline-first, citations on top:

1. KG baseline: frozen services.visa_guard transit rules + services/kg_seed
   entry rules (<50ms, local file I/O only).
2. Web-intel enrichment via the injected client; every citation carries a
   retrieved_date and is aged against max_age_hours → freshness_state
   fresh|stale|unknown (owner correction C — never silently 'fresh').
   Aging runs on REAL timestamps (citation fetched_at first, conservative
   start-of-day for date-only stamps) so sub-day policies are honored.
3. Network failure degrades VISIBLY to baseline_only=True + degraded=True;
   freshness becomes "unknown", never "fresh".

Unknown passports are honest (no invented rules) AND BLOCKING:
passport_unknown=True + freshness_state="unknown" — flight_book refuses.

BLOCKED_RISK contract (leader addendum, §3.1): a baseline block
(risk_level=block, e.g. MM via FRA) returns visa_blocked=True with reasons
+ citations so the planner replans (reroute back to flight_search); once the
reroute budget is exhausted the skill RAISES visa_route_blocked — a booking
on a blocked route is impossible, with no user override.

The frozen visa_guard is imported, never modified.
"""

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.skills.base import SkillBase, SkillError
from services.visa_guard import VISA_RULES, assess_offer
from services.web_intel_client import WebIntelClient

_KG_PATH = Path(__file__).resolve().parent.parent / "kg_seed.json"
_BASELINE_URL = "baseline://visa_guard"

_STATUS_TO_RISK = {
    "CLEAR": "info",
    "TRANSIT_VISA_REQUIRED": "warn",
    "BLOCKED_RISK": "block",
    "UNKNOWN": "info",
}


def _load_kg_entry_rules(kg_path: Path) -> List[Dict[str, Any]]:
    """VisaRule entities from the KG seed; unreadable seed → honest empty."""
    import json
    try:
        raw = json.loads(kg_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — missing/corrupt seed degrades, never raises
        return []
    rules = []
    for ent in raw.get("entities", []):
        if not isinstance(ent, dict) or ent.get("type") != "VisaRule":
            continue
        props = ent.get("props") or {}
        rules.append(props)
    return rules


class VisaCheckSkill(SkillBase):
    name = "visa_check"
    when_to_use = (
        "when an itinerary crosses borders or the user asks visa questions; "
        "KG baseline first, web-intel citations with as-of dates on top"
    )
    capabilities = frozenset({"network_read"})

    def __init__(self, web_intel: Optional[Any] = None,
                 kg_path: Optional[Path] = None,
                 max_age_hours: int = 24) -> None:
        self._web_intel = web_intel or WebIntelClient()
        self._kg_path = Path(kg_path) if kg_path else _KG_PATH
        self._max_age_hours = max_age_hours

    # -- baseline (KG + frozen visa_guard) -------------------------------------

    def _baseline(self, passport: str, route: List[str]) -> Dict[str, Any]:
        today = date.today().isoformat()
        requirements: List[Dict[str, Any]] = []
        risk_flags: List[str] = []

        # Transit posture applies only to intermediate hubs. The final airport
        # is the entry destination and must never be mislabeled as a layover.
        if passport in VISA_RULES and len(route) > 2:
            for hub in route[1:-1]:
                verdict = assess_offer(passport, {"stops": 1, "via": [hub]})
                status = verdict.get("visa_status", "UNKNOWN")
                note = verdict.get("visa_note") or ""
                requirements.append({
                    "country": hub,
                    "kind": "transit",
                    "name": f"{hub} transit check for {passport} passport",
                    "risk_level": _STATUS_TO_RISK.get(status, "info"),
                    "source": {"url": _BASELINE_URL, "retrieved_date": today},
                    "as_of": today,
                    "note": note,
                })
                if status != "CLEAR":
                    risk_flags.append(f"{hub} {status}: {note}")
        elif route:
            # honest: no rule table for this passport — say so, never invent
            risk_flags.append(
                f"no baseline rule table for passport '{passport}'; "
                "verify with official sources")

        # destination entry rules from the KG seed (as_of stamped)
        destination_country = None
        if route:
            from services.rights_engine import AIRPORT_COUNTRY
            destination_country = AIRPORT_COUNTRY.get(route[-1], "")
        for rule in _load_kg_entry_rules(self._kg_path):
            if rule.get("passport") != passport:
                continue
            if destination_country and rule.get("destination") != destination_country:
                continue
            requirements.append({
                "country": rule.get("destination", ""),
                "kind": "entry",
                "name": (f"{rule.get('rule', 'entry rule')} "
                         f"({rule.get('duration_days', '?')} days)"),
                "risk_level": "info",
                "source": {"url": rule.get("source", _BASELINE_URL),
                           "retrieved_date": rule.get("as_of", today)},
                "as_of": rule.get("as_of", today),
                "note": f"KG seed rule for {passport}→{rule.get('destination')}",
            })
        return {"requirements": requirements, "risk_flags": risk_flags,
                "destination_country": destination_country}

    # -- freshness gate ----------------------------------------------------------

    def _freshness(self, citations: List[Dict[str, Any]]) -> str:
        """Age citations against REAL timestamps (G2-DA fix).

        Preference order per citation: fetched_at (true fetch instant) →
        retrieved_date at UTC start-of-day (conservative oldest reading of a
        date-only stamp — never treats "yesterday" as <24h fresh). Strict
        comparison honors sub-day max_age_hours.
        """
        newest: Optional[datetime] = None
        for cit in citations:
            stamp: Optional[datetime] = None
            fetched = cit.get("fetched_at")
            if isinstance(fetched, str) and fetched:
                try:
                    stamp = datetime.fromisoformat(fetched)
                except ValueError:
                    stamp = None
                if stamp is not None:
                    if stamp.tzinfo is None:
                        stamp = stamp.replace(tzinfo=timezone.utc)
                    stamp = stamp.astimezone(timezone.utc)
            if stamp is None:
                raw = cit.get("retrieved_date")
                try:
                    day = datetime.fromisoformat(str(raw)[:10]).date()
                except (ValueError, TypeError):
                    continue
                # conservative: a date-only stamp is at BEST start of that day
                stamp = datetime(day.year, day.month, day.day,
                                 tzinfo=timezone.utc)
            newest = stamp if newest is None or stamp > newest else newest
        if newest is None:
            return "unknown"
        age_hours = (datetime.now(timezone.utc) - newest).total_seconds() / 3600
        return "fresh" if age_hours < self._max_age_hours else "stale"

    # -- run ------------------------------------------------------------------------

    async def run(self, payload: Dict[str, Any],
                  context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        passport = str(payload.get("passport_country") or "").strip().upper()
        route = [str(a).strip().upper() for a in (payload.get("route") or [])
                 if str(a).strip()]

        # unknown passport (empty or no baseline rule table) is BLOCKING:
        # flight_book refuses passport_unknown regardless of citation freshness
        passport_unknown = (not passport) or (passport not in VISA_RULES)

        baseline = self._baseline(passport, route)
        requirements = baseline["requirements"]
        risk_flags = baseline["risk_flags"]
        block_reasons = [
            f"{r.get('country')} {r.get('kind')}: {r.get('name')} "
            f"({r.get('note', '')})".strip()
            for r in requirements if r.get("risk_level") == "block"
        ]

        # BLOCKED_RISK contract: first block pass returns the blocking state
        # (planner replans/reroutes via the §3.1 edge back to flight_search);
        # once the reroute budget is exhausted the skill raises — a blocked
        # route can NEVER reach booking, and there is no user override.
        if block_reasons and context is not None:
            replans = int(context.get("visa_block_replan", 0))
            context["visa_block_replan"] = replans + 1
            if replans >= 1:
                raise SkillError(
                    "visa_route_blocked",
                    "route blocked by baseline visa rules: "
                    f"{block_reasons}; reroute budget exhausted — booking on "
                    "this route is refused with no override",
                    recoverable=True)

        query = (f"visa entry transit requirements {passport} passport "
                 f"{' '.join(route)}")
        result = await self._web_intel.fetch(query)
        degraded = bool(result.get("degraded") or result.get("offline"))
        citations = result.get("citations") or []

        if degraded or not citations:
            # offline/degraded: baseline still answers, VISIBLY labeled
            return {
                "passport_country": passport,
                "route": route,
                "requirements": requirements,
                "risk_flags": risk_flags,
                "citations": [{"url": _BASELINE_URL, "title": "visa_guard baseline",
                               "retrieved_date": date.today().isoformat(),
                               "snippet_max280": "local baseline rules (demo 2026-08)"}],
                "baseline_only": True,
                "degraded": True,
                "freshness_state": "unknown",  # honest: never 'fresh' offline
                "passport_unknown": passport_unknown,
                "visa_blocked": bool(block_reasons),
                "block_reasons": block_reasons,
            }

        return {
            "passport_country": passport,
            "route": route,
            "requirements": requirements,
            "risk_flags": risk_flags,
            "citations": citations,
            "baseline_only": False,
            "degraded": False,
            # unknown passports can never be rescued into 'fresh' by citations
            "freshness_state": "unknown" if passport_unknown
            else self._freshness(citations),
            "passport_unknown": passport_unknown,
            "visa_blocked": bool(block_reasons),
            "block_reasons": block_reasons,
        }
