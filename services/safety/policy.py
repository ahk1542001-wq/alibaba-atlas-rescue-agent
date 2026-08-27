"""SafetyPolicyEngine (Task #13) — PURE deterministic policy code.

PRIME RULE: an LLM NEVER decides whether a country is safe. This engine is
the only authority that computes a displayed status, from a closed
normalized vocabulary:

    normal_precautions | increased_caution | reconsider_travel |
    do_not_travel | unable_to_verify

Rules enforced in code (each pinned by tests/test_safety.py):

- every source's native wording/level is preserved alongside the
  normalized level;
- applicability: destination/transit country match; city/route intersecting
  the affected region (regional advice NEVER applies country-wide;
  country-wide advice applies to every leg); travel dates intersect
  validity; advisory applies to the traveler OR is clearly labeled as
  another government's advice;
- category-specific freshness windows; expired data stays visible with a
  stale label and NEVER silently clears a prior warning;
- URLs must be allowed official HTTP/S (private/localhost/file/
  redirected-to-unofficial rejected); snippet-only evidence rejected;
- conflicts: NEVER averaged; all applicable official assessments retained,
  disagreements shown; trip-policy status = the highest applicable current
  official level; no escalation from non-applicable regions; third-party
  and lower ratings never downgrade official assessments; unverified social
  content never sets or clears a status;
- missing evidence -> unable_to_verify, never normal_precautions;
- the absolute word "safe" can never appear in an output (enforced here
  and in UI strings).
"""

import ipaddress  # noqa: F401  (re-exported for adapters' hardening tests)
import re
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from models.schemas import (
    SafetyAssessment,
    SafetyEvidence,
    SafetyQuery,
    SafetySourceReport,
)
from services.safety.adapters import url_ok_for_source

SAFETY_LEVELS = ("normal_precautions", "increased_caution",
                 "reconsider_travel", "do_not_travel", "unable_to_verify")

LEVEL_RANK = {
    "normal_precautions": 0,
    "increased_caution": 1,
    "reconsider_travel": 2,
    "do_not_travel": 3,
}

# Category-specific freshness windows (hours): severe weather/disaster
# 15–30 min (worst-case 30 used), transport disruption 5–15 min (15 used),
# security alert 1 h, health outbreak 6 h, general advisory 24 h,
# local laws/cultural 7 d.
FRESHNESS_TTL_HOURS = {
    "severe_weather": 0.5,
    "disaster": 0.5,
    "transport_disruption": 0.25,
    "security": 1.0,
    "health": 6.0,
    "advisory": 24.0,
    "local_laws": 168.0,
    "cultural": 168.0,
}
_DEFAULT_TTL_HOURS = 24.0

# Official source families whose CURRENT verified assessments may set the
# trip-policy status. Transport operators surface operational warnings but
# never set the destination status; third_party/social NEVER set or clear.
_STATUS_SOURCES = {"official_government", "official_multilateral"}

_COUNTRY_ALIASES = {
    "SG": "SINGAPORE", "SGP": "SINGAPORE", "SINGAPORE": "SINGAPORE",
    "TH": "THAILAND", "THA": "THAILAND", "THAILAND": "THAILAND",
    "MM": "MYANMAR", "MMR": "MYANMAR", "MYANMAR": "MYANMAR",
    "BURMA": "MYANMAR",
    "MY": "MALAYSIA", "MYS": "MALAYSIA", "MALAYSIA": "MALAYSIA",
    "GB": "UNITED KINGDOM", "UK": "UNITED KINGDOM",
    "UNITED KINGDOM": "UNITED KINGDOM",
    "US": "UNITED STATES", "USA": "UNITED STATES",
    "UNITED STATES": "UNITED STATES",
    "AU": "AUSTRALIA", "AUS": "AUSTRALIA", "AUSTRALIA": "AUSTRALIA",
    "DE": "GERMANY", "GERMANY": "GERMANY",
    "FR": "FRANCE", "FRANCE": "FRANCE",
    "JP": "JAPAN", "JAPAN": "JAPAN",
    "IN": "INDIA", "INDIA": "INDIA",
    "CN": "CHINA", "CHINA": "CHINA",
    "ID": "INDONESIA", "INDONESIA": "INDONESIA",
    "VN": "VIETNAM", "VIETNAM": "VIETNAM",
    "KH": "CAMBODIA", "CAMBODIA": "CAMBODIA",
    "LA": "LAOS", "LAOS": "LAOS",
    "PH": "PHILIPPINES", "PHILIPPINES": "PHILIPPINES",
    "LK": "SRI LANKA", "SRI LANKA": "SRI LANKA",
    "BD": "BANGLADESH", "BANGLADESH": "BANGLADESH",
    "NP": "NEPAL", "NEPAL": "NEPAL",
    "KR": "SOUTH KOREA", "SOUTH KOREA": "SOUTH KOREA",
    "AE": "UNITED ARAB EMIRATES", "UNITED ARAB EMIRATES":
        "UNITED ARAB EMIRATES",
    "NZ": "NEW ZEALAND", "NEW ZEALAND": "NEW ZEALAND",
    "CA": "CANADA", "CANADA": "CANADA",
}

_ABSOLUTE_SAFE_RE = re.compile(r"\bsafe\b", re.IGNORECASE)


def contains_absolute_safe(text: str) -> bool:
    """True when a string asserts the absolute word "safe". "Safer",
    "safety" etc. are allowed — an absolute safety claim is never made."""
    return bool(text and _ABSOLUTE_SAFE_RE.search(text))


def _strip_absolute_claims(texts: List[str]) -> List[str]:
    return [t for t in texts if isinstance(t, str)
            and not contains_absolute_safe(t)]


def _desafe(text: Optional[str]) -> Optional[str]:
    """Hostile source text may embed the absolute word "safe"; the engine
    strips that one word (everything else is preserved verbatim)."""
    if not text or not contains_absolute_safe(text):
        return text
    cleaned = _ABSOLUTE_SAFE_RE.sub("[claim removed]", text)
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def _without_urls(obj: Any) -> Any:
    """Deep-copy of a dumped structure WITHOUT canonical_url values. URLs
    are locators, not claims: they stay verbatim in the output but are
    excluded from the absolute-safe scan, so a URL path containing the
    word can never crash the engine (G4.6-DA fix F6)."""
    if isinstance(obj, dict):
        return {k: _without_urls(v) for k, v in obj.items()
                if k != "canonical_url"}
    if isinstance(obj, list):
        return [_without_urls(v) for v in obj]
    return obj


def normalize_country(raw: Optional[str]) -> str:
    if not isinstance(raw, str) or not raw.strip():
        return ""
    key = raw.strip().upper()
    return _COUNTRY_ALIASES.get(key, key)


def _parse_dt(raw: Optional[str]) -> Optional[datetime]:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_date(raw: Optional[str]) -> Optional[date]:
    dt = _parse_dt(raw)
    if dt:
        return dt.date()
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw.strip()[:10])
        except ValueError:
            return None
    return None


def validate_official_url(url: str,
                          allowed_hosts: Optional[Any] = None
                          ) -> Tuple[bool, str]:
    """Public URL hardening gate (also used directly by tests)."""
    from services.safety.adapters import validate_official_url as _v
    return _v(url, allowed_hosts)


def _fuzzy_place(a: str, b: str) -> bool:
    a, b = a.strip().lower(), b.strip().lower()
    if not a or not b:
        return False
    return a in b or b in a


class SafetyPolicyEngine:
    """Pure, deterministic, clock-injectable (hermetic tests)."""

    def __init__(self, clock: Optional[Callable[[], datetime]] = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    # -- freshness ---------------------------------------------------------------

    def _ttl_hours(self, evidence: SafetyEvidence) -> float:
        ttls = [FRESHNESS_TTL_HOURS.get(cat, _DEFAULT_TTL_HOURS)
                for cat in evidence.risk_categories] or [_DEFAULT_TTL_HOURS]
        return min(ttls)

    def _freshness(self, evidence: SafetyEvidence,
                   now: datetime) -> str:
        ref = None
        for field in (evidence.updated_at, evidence.published_at,
                      evidence.retrieved_at):
            ref = _parse_dt(field)
            if ref is not None:
                break
        if ref is None:
            return "unknown"
        age_hours = (now - ref).total_seconds() / 3600.0
        return "fresh" if age_hours <= self._ttl_hours(evidence) else "stale"

    # -- applicability --------------------------------------------------------------

    def _user_places(self, query: SafetyQuery) -> List[str]:
        places = [p for p in (list(query.cities)
                              + list(query.destination_regions)
                              + [query.venue or ""]
                              + list(query.transit_airports)) if p]
        return places

    def _validity_ok(self, evidence: SafetyEvidence,
                     query: SafetyQuery) -> bool:
        v_from = _parse_date(evidence.valid_from)
        v_to = _parse_date(evidence.valid_to)
        if v_from is None and v_to is None:
            return True
        if query.travel_window is not None:
            win_start = query.travel_window.start
            win_end = query.travel_window.end
        else:
            today = self._clock().date()
            win_start, win_end = today, today
        if v_to is not None and v_to < win_start:
            return False
        if v_from is not None and v_from > win_end:
            return False
        return True

    def _applicability(self, query: SafetyQuery, evidence: SafetyEvidence
                       ) -> Tuple[bool, str, bool]:
        """(applies, reason, foreign_advice)."""
        e_country = normalize_country(evidence.country)
        dest = normalize_country(query.destination_country)
        transits = {normalize_country(c) for c in query.transit_countries}
        if e_country and e_country != dest and e_country not in transits:
            return False, "country does not match destination or transit", False

        places = self._user_places(query)
        if evidence.affected_regions:
            # REGIONAL RULE: regional advice NEVER applies country-wide.
            matched = [
                p for p in places
                if any(_fuzzy_place(p, r) for r in evidence.affected_regions)
                and not any(_fuzzy_place(p, x)
                            for x in evidence.excluded_regions)
            ]
            if not matched:
                return False, ("regional advice does not intersect the "
                               "traveler's route — never applied country-wide"
                               ), False
        elif evidence.excluded_regions and places:
            if all(any(_fuzzy_place(p, x) for x in evidence.excluded_regions)
                   for p in places):
                return False, "traveler's locations are excluded regions", False

        if not self._validity_ok(evidence, query):
            return False, "validity period does not intersect travel dates", False

        foreign = False
        if evidence.applies_to_nationalities:
            passport = normalize_country(query.passport_country)
            nations = {normalize_country(n)
                       for n in evidence.applies_to_nationalities}
            authority = normalize_country(evidence.authority_country)
            if passport and (passport in nations or authority == passport):
                foreign = False
            else:
                # another government's advice: still shown, clearly labeled
                foreign = True
        return True, "applies to this route", foreign

    # -- assessment ------------------------------------------------------------------

    def assess(self, query: SafetyQuery,
               evidence: List[SafetyEvidence],
               source_reports: Optional[List[SafetySourceReport]] = None
               ) -> SafetyAssessment:
        now = self._clock()
        per_source: List[Dict[str, Any]] = []
        current_official: List[SafetyEvidence] = []
        stale_official: List[SafetyEvidence] = []
        unverified_sources: List[str] = []
        all_actions: List[str] = []

        for ev in evidence:
            url_ok, url_reason = url_ok_for_source(ev.source_id,
                                                   ev.canonical_url)
            rejected_reason = None
            if not url_ok:
                rejected_reason = f"rejected: {url_reason}"
            elif ev.extraction_method == "snippet_only":
                rejected_reason = "rejected: snippet-only evidence"
            elif ev.verification_status != "verified":
                rejected_reason = "rejected: unverified evidence"

            freshness = self._freshness(ev, now)
            applies, reason, foreign = self._applicability(query, ev)

            entry: Dict[str, Any] = {
                "source_id": ev.source_id,
                "authority": _desafe(ev.authority),
                "authority_country": ev.authority_country,
                "source_type": ev.source_type,
                "canonical_url": ev.canonical_url,
                "title": _desafe(ev.title),
                "updated_at": ev.updated_at,
                "retrieved_at": ev.retrieved_at,
                "valid_from": ev.valid_from,
                "valid_to": ev.valid_to,
                "country": ev.country,
                "affected_regions": list(ev.affected_regions),
                "native_level": _desafe(ev.native_level),
                "normalized_level": ev.normalized_level,
                "risk_categories": list(ev.risk_categories),
                "concise_facts": _strip_absolute_claims(ev.concise_facts),
                "recommended_actions":
                    _strip_absolute_claims(ev.recommended_actions),
                "freshness": freshness,
                "applies": applies and rejected_reason is None,
                "applies_reason": rejected_reason or reason,
                "foreign_advice": foreign,
                "verification_status": ev.verification_status,
            }
            per_source.append(entry)

            if rejected_reason:
                if ev.source_id not in unverified_sources:
                    unverified_sources.append(ev.source_id)
                continue
            if ev.verification_status != "verified":
                if ev.source_id not in unverified_sources:
                    unverified_sources.append(ev.source_id)

            if not applies:
                continue

            sets_status = ev.source_type in _STATUS_SOURCES
            if not sets_status:
                # transport/third-party/social: visible, never sets status
                continue

            if ev.normalized_level == "unable_to_verify":
                continue  # no recognizable level: shown, never counted

            if freshness == "fresh":
                current_official.append(ev)
                all_actions.extend(entry["recommended_actions"])
            elif freshness == "stale":
                stale_official.append(ev)

        # --- conflict policy: never average; highest current official wins ---
        levels = sorted({ev.normalized_level for ev in current_official},
                        key=lambda lvl: LEVEL_RANK[lvl])
        disagreements: List[Dict[str, Any]] = []
        if len(levels) > 1:
            for ev in current_official:
                disagreements.append({
                    "source_id": ev.source_id,
                    "authority": _desafe(ev.authority),
                    "native_level": _desafe(ev.native_level),
                    "normalized_level": ev.normalized_level,
                    "canonical_url": ev.canonical_url,
                })

        stale_warnings = [{
            "source_id": ev.source_id,
            "authority": ev.authority,
            "normalized_level": ev.normalized_level,
            "native_level": _desafe(ev.native_level),
            "canonical_url": ev.canonical_url,
            "updated_at": ev.updated_at,
            "risk_categories": list(ev.risk_categories),
            "freshness": "stale",
            "note": "past its freshness window — visible with a stale label, "
                    "never silently cleared",
        } for ev in stale_official]

        if levels:
            trip_status = levels[-1]
        else:
            # missing evidence -> unable_to_verify, NEVER normal_precautions
            trip_status = "unable_to_verify"
        overall_status = trip_status

        # --- explanations (deterministic, absolute-claim-free) -----------------
        unavailable = [r.source_id for r in (source_reports or [])
                       if r.status in ("unavailable", "rejected")]
        if trip_status == "unable_to_verify":
            why = ("No current, verified official assessment applies to this "
                   "route — the status cannot be verified. Missing evidence "
                   "never counts as a clear status.")
            bits = []
            if unavailable:
                bits.append(f"sources unavailable: {', '.join(unavailable)}")
            if stale_official:
                bits.append("a prior official warning is past its freshness "
                            "window and is shown with a stale label")
            if not bits:
                bits.append("no applicable official evidence was retrieved")
            confidence = "Unable to verify — " + "; ".join(bits) + "."
        else:
            n = len({ev.source_id for ev in current_official})
            ids = sorted({ev.source_id for ev in current_official})
            why = (f"{trip_status} — the highest current official assessment "
                   f"among {n} applicable official source(s) "
                   f"({', '.join(ids)}). Official levels are never averaged"
                   + ("; official sources DISAGREE (all shown)."
                      if disagreements else "."))
            confidence = (f"{len(current_official)} applicable current "
                          "official assessment(s) verified."
                          + (f" Unavailable sources: {', '.join(unavailable)}."
                             if unavailable else ""))

        safer: List[str] = []
        if trip_status in ("reconsider_travel", "do_not_travel"):
            safer = [
                "Consider different travel dates if your plans are flexible.",
                "Consider a different destination or route where official "
                "advice carries a lower level.",
            ]

        actions: List[str] = []
        for action in all_actions:
            if action not in actions:
                actions.append(action)
        actions = actions[:8]

        assessment = SafetyAssessment(
            overall_status=overall_status,
            trip_policy_status=trip_status,
            assessments_per_source=per_source,
            disagreements=disagreements,
            why_selected=why,
            recommended_actions=actions,
            safer_alternatives=safer,
            checked_at=now.isoformat(),
            confidence_or_unable_to_verify=confidence,
            unverified_sources=unverified_sources,
            stale_warnings=stale_warnings,
        )
        # hard enforcement: no absolute "safe" may ever leave the engine
        # (canonical URLs are locators, not claims — scanned without them)
        blob = str(_without_urls(assessment.model_dump(mode="json")))
        if contains_absolute_safe(blob):
            raise AssertionError(
                "SafetyPolicyEngine output contained an absolute 'safe' "
                "claim — this must never happen")
        return assessment
