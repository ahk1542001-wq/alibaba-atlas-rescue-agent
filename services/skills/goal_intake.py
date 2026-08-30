"""goal_intake skill — §4 S1 (G2 behavior).

LLM extract → validate → deterministic stub fallback flagged degraded when
the LLM is unavailable (AUTO- decision §16.1). Never raises on hostile text:
unparseable input yields a partial TripGoal with honest degraded flags.
"""

import re
import uuid
from datetime import date
from typing import Any, Awaitable, Callable, Dict, List, Optional

from models.schemas import RequestedServices, TripGoal
from services.skills.base import SkillBase
from services import llm as llm_service

_CITIES = {
    "SIN": ["singapore", "changi", "marina bay sands", "wit singapore", "sin"],
    "BKK": ["bangkok", "suvarnabhumi", "bkk"],
    "DMK": ["don mueang", "don muang", "dmk"],
    "RGN": ["yangon", "rangoon", "rgn"],
    "FRA": ["frankfurt", "fra"],
}

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7,
    "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12,
    "december": 12,
}

_WORD_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                 "six": 6, "seven": 7, "eight": 8, "nine": 9}


def _airport_resolution(text: str, code: Optional[str]) -> tuple[List[str], Optional[str]]:
    """Preserve city-level ambiguity while accepting explicit airports.

    The deterministic extractor historically collapsed the word ``Bangkok``
    to BKK.  That is useful for legacy search, but it is not a user-confirmed
    airport choice because Bangkok also has DMK.  Candidate/confirmation
    fields carry that distinction without changing the legacy city field.
    """
    if not code:
        return [], None
    upper = text.upper()
    if re.search(rf"\b{re.escape(code)}\b", upper):
        return [code], code
    if code == "BKK" and "BANGKOK" in upper:
        if "SUVARNABHUMI" in upper:
            return ["BKK"], "BKK"
        if "DON MUEANG" in upper or "DON MUANG" in upper:
            return ["DMK"], "DMK"
        return ["BKK", "DMK"], None
    return [code], code


def _find_city(text: str, start: int = 0, end: Optional[int] = None) -> Optional[str]:
    """Return IATA for the first city alias occurring in text[start:end]."""
    seg = text[start:end] if end is not None else text[start:]
    best: Optional[tuple] = None
    for iata, aliases in _CITIES.items():
        for alias in aliases:
            idx = seg.find(alias)
            if idx != -1 and (best is None or idx < best[0]):
                best = (idx, iata)
    return best[1] if best else None


def _extract_dates(text: str) -> Optional[Dict[str, str]]:
    year_default = date.today().year
    # ISO range: 2026-09-28 to 2026-09-30
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})\s*(?:to|-|–|through|until)\s*"
                  r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        return {"start": f"{m.group(1)}-{m.group(2)}-{m.group(3)}",
                "end": f"{m.group(4)}-{m.group(5)}-{m.group(6)}"}
    # single ISO date
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        iso = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        return {"start": iso, "end": iso}
    # month-name forms: "Sep 28-30" | "September 28 and 30" | "28 Sep" |
    # "29-30 conference" (month carried from earlier mention)
    m = re.search(r"([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:\s*[-–to]+\s*(\d{1,2}))?", text)
    if m and m.group(1).lower() in _MONTHS:
        month = _MONTHS[m.group(1).lower()]
        day1 = int(m.group(2))
        day2 = int(m.group(3)) if m.group(3) else day1
        year = year_default
        m2 = re.search(r"\b(20\d{2})\b", text)
        if m2:
            year = int(m2.group(1))
        start = f"{year}-{month:02d}-{day1:02d}"
        end = f"{year}-{month:02d}-{max(day1, day2):02d}"
        return {"start": start, "end": end}
    # bare day range with month mentioned elsewhere: "September 29 and 30"
    m = re.search(r"(\d{1,2})\s*(?:and|to|-|–)\s*(\d{1,2})", text)
    if m:
        for token in re.findall(r"[A-Za-z]{3,9}", text):
            if token.lower() in _MONTHS:
                month = _MONTHS[token.lower()]
                day1, day2 = int(m.group(1)), int(m.group(2))
                return {"start": f"{year_default}-{month:02d}-{day1:02d}",
                        "end": f"{year_default}-{month:02d}-{max(day1, day2):02d}"}
    return None


def _extract_origin_dest(text: str):
    """Extract (origin, dest) IATA pair; either may be None when unstated."""
    origin = dest = None
    # 1) explicit paired patterns "from X to Y" / "X to Y" / "X going Y"
    for pat in (
        r"from\s+([A-Za-z .]{3,25}?)\s+(?:to|->|→)\s+([A-Za-z .]{3,25}?)"
        r"(?=,|\.|$|\s+on\b|\s+\d|\s+i\b)",
        r"\b([A-Za-z]{3})\s*(?:to|->|→)\s*([A-Za-z]{3})\b",
        r"([A-Za-z .]{3,25}?)\s+going\s+([A-Za-z .]{3,25}?)(?=,|\.|$)",
    ):
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            origin = origin or _find_city(m.group(1))
            if m.lastindex and m.lastindex >= 2:
                dest = dest or _find_city(m.group(2))
            if origin and dest:
                return origin, dest
    # 2) standalone origin markers ("from X", "out of X", "departing X")
    for pat in (
        r"from\s+([A-Za-z .]{3,25}?)(?=,|\.|$|\s+on\b|\s+for\b|\s+to\b|\s+with\b|\s+by\b)",
        r"out of\s+([A-Za-z .]{3,25}?)(?=,|\.|$|\s+on\b|\s+for\b|\s+to\b|\s+with\b|\s+by\b)",
        r"departing\s+([A-Za-z .]{3,25}?)(?=,|\.|$|\s+on\b|\s+for\b|\s+to\b|\s+with\b|\s+by\b)",
    ):
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            origin = origin or _find_city(m.group(1))
            break
    # 3) positional fallback: order of first city mentions (earliest alias
    #    wins per city — substring aliases like 'bkk' inside 'singapore'
    #    must not outrank the real mention position)
    mentions: List[tuple] = []
    for iata, aliases in _CITIES.items():
        positions = [text.find(alias) for alias in aliases]
        positions = [p for p in positions if p != -1]
        if positions:
            mentions.append((min(positions), iata))
    mentions.sort()
    codes = [iata for _, iata in mentions]
    if len(codes) == 1:
        # single city: "to X" phrasing implies destination, else origin
        if re.search(r"\b(?:to|get to|going to)\s", text):
            dest = dest or codes[0]
        else:
            origin = origin or codes[0]
    else:
        if origin is None and codes:
            origin = codes[0]
        if dest is None:
            for c in codes:
                if c != origin:
                    dest = c
                    break
    return origin, dest


def _extract_passengers_info(text: str) -> tuple[int, bool]:
    m = re.search(r"(\d+)\s*(?:people|pax|passengers?|persons?|adults?|travelers?|travellers?|of us)", text,
                  flags=re.IGNORECASE)
    if m:
        return max(1, min(9, int(m.group(1)))), True
    m_for = re.search(r"\bfor\s+(\d+)\b", text, flags=re.IGNORECASE)
    if m_for:
        return max(1, min(9, int(m_for.group(1)))), True
    for word, n in _WORD_NUMBERS.items():
        if re.search(rf"\b(?:for\s+)?{word}\s+(?:people|pax|passengers?|persons?|adults?|travelers?|travellers?)\b", text,
                     flags=re.IGNORECASE):
            return n, True
    if re.search(r"\b(?:solo|just\s+me|for\s+myself|for\s+me|my\s+(?:complete\s+|whole\s+)?trip|my\s+flight|a\s+flight|a\s+trip|book\s+a)\b", text, flags=re.IGNORECASE):
        return 1, True
    return 1, False


def _extract_passengers(text: str) -> int:
    return _extract_passengers_info(text)[0]


def _infer_services(text: str) -> Dict[str, str]:
    low = text.lower()
    rs: Dict[str, str] = {k: "unknown" for k in
                          ("flight_search", "flight_booking", "visa_check",
                           "hotel", "activities", "local_transport")}
    flight_kw = ("flight", "fly", "flying", "ticket", "get to", "travel to",
                 "going", "reach", "attend")
    if any(k in low for k in flight_kw) or _extract_dates(text):
        rs["flight_search"] = "requested"
    if "book" in low:
        rs["flight_booking"] = "requested"
    if any(k in low for k in ("whole trip", "full package", "plan my whole",
                              "entire trip", "complete trip", "everything",
                              "arrange my whole")):
        rs.update({"flight_search": "requested", "flight_booking": "requested",
                   "visa_check": "requested", "hotel": "requested",
                   "activities": "requested", "local_transport": "requested"})
    else:
        if "hotel" in low or "stay" in low:
            rs["hotel"] = "not_requested" if "no hotel" in low else "requested"
        if "activit" in low or "attraction" in low or "sightsee" in low:
            rs["activities"] = "requested"
        if "local transport" in low or "transport" in low:
            rs["local_transport"] = "requested"
        if "flights only" in low or "flight only" in low or "just the flight" in low:
            rs.update({"flight_booking": rs["flight_booking"],
                       "hotel": "not_requested", "activities": "not_requested",
                       "local_transport": "not_requested"})
    return rs


def deterministic_extract(free_text: str) -> Dict[str, Any]:
    """Deterministic stub extractor — identical output for identical input."""
    text = (free_text or "").strip()
    low = text.lower()
    origin, dest = _extract_origin_dest(low) if text else (None, None)
    dates = _extract_dates(text) if text else None
    purpose = None
    for kw in ("meeting", "conference", "summit", "wedding", "holiday",
               "business", "wit"):
        if kw in low:
            purpose = kw
            break
    budget = None
    m = re.search(r"budget\s*(?:of|:)?\s*(\d+)\s*([A-Za-z]{3})?", low)
    if m:
        budget = f"{m.group(1)} {m.group(2) or 'USD'}".strip()
    pax_count, pax_explicit = _extract_passengers_info(low) if text else (1, False)
    return {
        "origin_city": origin,
        "dest_city": dest,
        "date_window": dates,
        "passengers": pax_count,
        "passengers_explicit": pax_explicit,
        "budget_hint": budget,
        "purpose": purpose,
    }


_EXTRACT_SYSTEM = (
    "Extract travel intent as compact JSON with keys origin_city(IATA), "
    "dest_city(IATA), date_window{start,end YYYY-MM-DD}, passengers(int), "
    "budget_hint, purpose. Unknown values: null."
)


class GoalIntakeSkill(SkillBase):
    name = "goal_intake"
    when_to_use = "when the user submits a free-text travel goal in any phrasing"
    capabilities = frozenset({"llm_call"})

    def __init__(self, llm_chat: Optional[Callable[..., Awaitable[Optional[str]]]] = None):
        self._llm_chat = llm_chat if llm_chat is not None else llm_service.chat

    async def run(self, payload: Dict[str, Any],
                  context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        free_text = str(payload.get("free_text") or "")
        fields: Optional[Dict[str, Any]] = None
        extraction = "deterministic_stub"
        degraded = True
        try:
            reply = await self._llm_chat(
                [{"role": "system", "content": _EXTRACT_SYSTEM},
                 {"role": "user", "content": free_text[:2000]}],
                max_tokens=220, temperature=0.1)
            parsed = llm_service.parse_json(reply)
            if isinstance(parsed, dict) and (parsed.get("origin_city")
                                             or parsed.get("dest_city")):
                fields = parsed
                extraction = "llm"
                degraded = False
        except Exception:  # noqa: BLE001 — LLM is optional enrichment only
            fields = None
        if fields is None:
            fields = deterministic_extract(free_text)
        def build_goal(extracted: Dict[str, Any]) -> TripGoal:
            origin = extracted.get("origin_city") or None
            destination = extracted.get("dest_city") or None
            origin_candidates, confirmed_origin = _airport_resolution(
                free_text, origin)
            destination_candidates, confirmed_destination = _airport_resolution(
                free_text, destination)
            pax_explicit = bool(extracted.get("passengers_explicit", False))
            if not pax_explicit:
                _, pax_explicit = _extract_passengers_info(free_text)
            return TripGoal(
                goal_id=f"goal_{uuid.uuid4().hex[:8]}",
                raw_text=free_text,
                origin_city=origin,
                origin_airport_candidates=origin_candidates,
                confirmed_origin_airport=confirmed_origin,
                dest_city=destination,
                destination_airport_candidates=destination_candidates,
                confirmed_destination_airport=confirmed_destination,
                date_window=extracted.get("date_window") or None,
                passengers=int(extracted.get("passengers") or 1),
                passengers_explicit=pax_explicit,
                budget_hint=extracted.get("budget_hint") or None,
                purpose=extracted.get("purpose") or None,
            )

        try:
            goal = build_goal(fields)
        except (TypeError, ValueError):
            # LLM extraction is optional enrichment.  A syntactically valid
            # JSON reply can still carry an impossible date or malformed
            # passenger value, so validate it before trusting it and degrade
            # to the deterministic parser instead of failing the whole intake.
            if extraction != "llm":
                raise
            fields = deterministic_extract(free_text)
            extraction = "deterministic_stub"
            degraded = True
            goal = build_goal(fields)
        requested = _infer_services(free_text)
        return {
            "goal": goal.model_dump(mode="json"),
            "requested_services": RequestedServices(**requested).model_dump(),
            "extraction": extraction,
            "degraded": degraded,
        }
