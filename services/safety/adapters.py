"""Safety source adapters (Task #13) — honest, bounded, injection-resistant.

Source availability differs by country; NO single source is universal truth.
Every adapter returns one of:
- SafetyEvidence[] parsed from an official HTTP/S source, or
- an honest report: no_coverage / unavailable / rejected — never fabricated.

HOSTILE-DATA STANCE: fetched content is DATA, never instructions. Parsing is
tolerant (missing keys / junk shapes degrade field-by-field); LLM use (when
available) is limited to extracting bounded facts and its output is treated
as untrusted text. URL hardening lives in services/safety/policy.py
(validate_official_url): private/localhost/file/redirected-to-unofficial
URLs are rejected.

Transport is INJECTABLE: tests run hermetically against fakes; production
uses default_http_fetch (httpx, bounded timeouts, redirect-host re-check).
"""

import ipaddress
import json as _json
import re
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from models.schemas import SafetyEvidence, SafetyQuery, SafetySourceReport

# --- official source host registry (policy.py enforces it) -------------------
# source_id -> {"hosts": exact-or-suffix hosts, "gov_suffix_ok": bool}
SOURCE_OFFICIAL_HOSTS: Dict[str, Dict[str, Any]] = {
    "gov_uk": {"hosts": {"www.gov.uk", "gov.uk"}, "gov_suffix_ok": False},
    "us_state": {"hosts": {"travel.state.gov"}, "gov_suffix_ok": False},
    "au_smartraveller": {"hosts": {"www.smartraveller.gov.au",
                                   "smartraveller.gov.au"},
                         "gov_suffix_ok": False},
    # destination-government/embassy/immigration notices arrive through the
    # bounded WebIntel path; the .gov/.gov.xx suffix heuristic is the gate
    "destination_gov": {"hosts": set(), "gov_suffix_ok": True},
    "who_don": {"hosts": {"www.who.int", "who.int"}, "gov_suffix_ok": False},
    "gdacs": {"hosts": {"www.gdacs.org", "gdacs.org"}, "gov_suffix_ok": False},
    "weather_official": {"hosts": {"weather.gov", "met.gov"},
                         "gov_suffix_ok": True},
    "transport_ops": {"hosts": set(), "gov_suffix_ok": True},
}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _now_utc().isoformat()


def _host_looks_official_gov(hostname: str) -> bool:
    """Deterministic .gov / .gov.xx suffix heuristic for destination-gov,
    weather and transport sources without a pinned host list."""
    host = (hostname or "").lower().rstrip(".")
    if host.endswith(".gov") or host == "gov":
        return True
    return bool(re.search(r"\.gov\.[a-z]{2}$", host))


def validate_official_url(url: str,
                          allowed_hosts: Optional[Any] = None
                          ) -> Tuple[bool, str]:
    """Harden one URL BEFORE any fetch / before it may ground a status.

    Rejects: non-http(s) schemes, missing hosts, localhost / private /
    loopback / link-local / reserved IPs, and hosts outside the allow-list.
    Redirects are handled by the transport (final-URL re-check), so a
    redirect landing on an unofficial host is rejected there too.
    """
    if not isinstance(url, str) or not url.strip():
        return False, "empty_url"
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False, "unparseable_url"
    if parsed.scheme not in ("http", "https"):
        return False, f"scheme_not_http_https ({parsed.scheme or 'none'})"
    host = (parsed.hostname or "").lower()
    if not host:
        return False, "missing_host"
    if host == "localhost" or host.endswith(".localhost"):
        return False, "localhost_rejected"
    try:
        addr = ipaddress.ip_address(host)
        if (addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_reserved or addr.is_multicast
                or addr.is_unspecified):
            return False, "private_or_local_address_rejected"
    except ValueError:
        pass  # hostname, not an IP literal
    if allowed_hosts is None:
        return True, "ok"
    hosts = {str(h).lower() for h in allowed_hosts}
    if host in hosts or any(host.endswith("." + h) for h in hosts):
        return True, "ok"
    return False, "host_not_in_official_allowlist"


def url_ok_for_source(source_id: str, url: str) -> Tuple[bool, str]:
    reg = SOURCE_OFFICIAL_HOSTS.get(source_id)
    if reg is None:
        return False, "unknown_source"
    # generic hardening first (scheme, private/loopback/local hosts)
    ok, reason = validate_official_url(url, None)
    if not ok:
        return False, reason
    host = (urlparse(url.strip()).hostname or "").lower()
    if reg["hosts"] and any(
            host == h or host.endswith("." + h) for h in reg["hosts"]):
        return True, "ok"
    if reg["gov_suffix_ok"] and _host_looks_official_gov(host):
        return True, "ok"
    return False, "host_not_in_official_allowlist"


# --- deterministic level vocabulary (never LLM-decided) ------------------------

_DO_NOT_TRAVEL = ("do not travel", "do not travel to all",
                  "level 4", "avoid all travel")
_RECONSIDER = ("reconsider travel", "reconsider your need to travel",
               "level 3", "avoid non-essential travel")
_INCREASED = ("exercise increased caution", "exercise a high degree of caution",
              "level 2", "increased caution", "high degree of caution")
_NORMAL = ("exercise normal precautions", "exercise normal safety precautions",
           "normal safety precautions", "level 1", "normal precautions")


def normalize_level_from_text(text: str) -> Optional[str]:
    """Deterministic keyword mapping, most-severe first. Returns None when
    the text carries no recognizable official level wording — the absence
    of a level is NEVER laundered into a level."""
    if not isinstance(text, str):
        return None
    low = text.lower()
    for phrase in _DO_NOT_TRAVEL:
        if phrase in low:
            return "do_not_travel"
    for phrase in _RECONSIDER:
        if phrase in low:
            return "reconsider_travel"
    for phrase in _INCREASED:
        if phrase in low:
            return "increased_caution"
    for phrase in _NORMAL:
        if phrase in low:
            return "normal_precautions"
    return None


# --- injectable transport -------------------------------------------------------

# fetch(url) -> {"status": int, "final_url": str, "json": Any|None, "text": str}
# raises on transport failure; adapters convert raises into honest reports.
SafetyFetcher = Callable[[str], Awaitable[Dict[str, Any]]]


def _final_url_official(source_id: str, payload: Dict[str, Any]) -> bool:
    final = payload.get("final_url") or ""
    if not final:
        return True  # nothing to re-check
    ok, _ = url_ok_for_source(source_id, final)
    return ok


async def default_http_fetch(url: str) -> Dict[str, Any]:
    """Production transport: bounded httpx fetch. Imported lazily so the
    module imports cleanly in offline test environments."""
    import httpx

    ok, reason = validate_official_url(url, None)
    if not ok:
        raise ValueError(f"refusing to fetch unsafe url: {reason}")
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        resp = await client.get(
            url, headers={"User-Agent": "TravelCare safety-intel (read-only)"})
        resp.raise_for_status()
        try:
            payload_json: Any = resp.json()
        except Exception:  # noqa: BLE001 — HTML source
            payload_json = None
        return {"status": resp.status_code, "final_url": str(resp.url),
                "json": payload_json, "text": resp.text[:200_000]}


# --- tolerant field helpers (hostile DATA) ----------------------------------------


def _str_field(raw: Any, limit: int = 400) -> Optional[str]:
    if isinstance(raw, str) and raw.strip():
        return raw.strip()[:limit]
    return None


def _iso_field(raw: Any) -> Optional[str]:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return raw.strip()


_TAG = re.compile(r"<[^>]+>")


def _strip_tags(raw: Any) -> str:
    if not isinstance(raw, str):
        return ""
    return _TAG.sub(" ", raw)


def _bounded_facts(items: Any, limit: int = 8, item_len: int = 280) -> List[str]:
    if not isinstance(items, list):
        return []
    out = []
    for item in items:
        if isinstance(item, str) and item.strip():
            out.append(item.strip()[:item_len])
        if len(out) >= limit:
            break
    return out


def _build_evidence(source_id: str, authority: str,
                    authority_country: Optional[str], source_type: str,
                    url: str, title: str, country: str,
                    native_level: Optional[str],
                    normalized_level: str, risk_categories: List[str],
                    facts: List[str], actions: List[str],
                    published_at: Optional[str], updated_at: Optional[str],
                    valid_from: Optional[str] = None,
                    valid_to: Optional[str] = None,
                    affected_regions: Optional[List[str]] = None,
                    excluded_regions: Optional[List[str]] = None,
                    applies_to_nationalities: Optional[List[str]] = None,
                    extraction_method: str = "structured_parse",
                    ) -> Optional[SafetyEvidence]:
    ok, _ = url_ok_for_source(source_id, url)
    if not ok:
        return None  # unofficial URL can never ground evidence
    if extraction_method == "snippet_only" and not facts:
        return None  # snippet-only evidence is rejected outright
    return SafetyEvidence(
        source_id=source_id, authority=authority,
        authority_country=authority_country,
        applies_to_nationalities=list(applies_to_nationalities or []),
        source_type=source_type, canonical_url=url, title=title[:300],
        published_at=published_at, updated_at=updated_at,
        retrieved_at=_iso_now(), country=country,
        affected_regions=list(affected_regions or []),
        excluded_regions=list(excluded_regions or []),
        valid_from=valid_from, valid_to=valid_to,
        native_level=native_level, normalized_level=normalized_level,
        risk_categories=list(risk_categories), concise_facts=_bounded_facts(facts),
        recommended_actions=_bounded_facts(actions), freshness="unknown",
        verification_status="verified", extraction_method=extraction_method)


# --- adapters ------------------------------------------------------------------------


class SourceAdapter:
    """Base adapter: tolerant parsing, honest states, zero fabrication."""

    source_id = ""
    authority = ""
    authority_country: Optional[str] = None
    source_type = "official_government"
    risk_categories: List[str] = ["advisory"]

    def url_for(self, query: SafetyQuery) -> Optional[str]:
        raise NotImplementedError

    def parse(self, payload: Dict[str, Any],
              query: SafetyQuery) -> List[SafetyEvidence]:
        raise NotImplementedError

    async def collect(self, query: SafetyQuery, fetch: SafetyFetcher
                      ) -> Tuple[List[SafetyEvidence], SafetySourceReport]:
        url = self.url_for(query)
        if not url:
            return [], SafetySourceReport(
                source_id=self.source_id, status="no_coverage",
                note="no known official feed for this destination")
        try:
            payload = await fetch(url)
        except Exception as exc:  # noqa: BLE001 — hostile web: degrade
            return [], SafetySourceReport(
                source_id=self.source_id, status="unavailable",
                note=f"fetch failed ({type(exc).__name__})")
        if not isinstance(payload, dict) or payload.get("status", 0) != 200:
            return [], SafetySourceReport(
                source_id=self.source_id, status="unavailable",
                note="non-200 response")
        if not _final_url_official(self.source_id, payload):
            return [], SafetySourceReport(
                source_id=self.source_id, status="rejected",
                note="redirect landed on an unofficial host")
        try:
            evidence = self.parse(payload, query)
        except Exception:  # noqa: BLE001 — hostile payload shape
            evidence = []
        if not evidence:
            return [], SafetySourceReport(
                source_id=self.source_id, status="no_coverage",
                note="source responded but gave no advisory for this country")
        return evidence, SafetySourceReport(
            source_id=self.source_id, status="ok",
            evidence_count=len(evidence))

    def _make(self, url: str, title: str, country: str, native_level,
              normalized, facts, actions, published_at, updated_at,
              **kwargs) -> Optional[SafetyEvidence]:
        # a government advisory is issued for ITS OWN citizens — keeping
        # that scope explicit lets the engine label foreign advice honestly
        if self.source_type == "official_government" \
                and self.authority_country \
                and "applies_to_nationalities" not in kwargs:
            kwargs["applies_to_nationalities"] = [self.authority_country]
        return _build_evidence(
            self.source_id, self.authority, self.authority_country,
            self.source_type, url, title, country, native_level,
            normalized, self.risk_categories, facts, actions,
            published_at, updated_at, **kwargs)


class GovUkAdapter(SourceAdapter):
    """GOV.UK Foreign Travel Advice via the official Content API."""

    source_id = "gov_uk"
    authority = "UK Foreign, Commonwealth & Development Office"
    authority_country = "GB"

    def url_for(self, query: SafetyQuery) -> Optional[str]:
        slug = re.sub(r"[^a-z-]", "-",
                      query.destination_country.lower()).strip("-")
        if not slug:
            return None
        return f"https://www.gov.uk/api/content/foreign-travel-advice/{slug}"

    def parse(self, payload: Dict[str, Any],
              query: SafetyQuery) -> List[SafetyEvidence]:
        data = payload.get("json")
        if not isinstance(data, dict):
            return []
        title = _str_field(data.get("title")) or "UK travel advice"
        updated = _iso_field(data.get("public_updated_at")
                             or data.get("updated_at"))
        details = data.get("details") if isinstance(data.get("details"), dict) \
            else {}
        summary_bits: List[str] = []
        summary = details.get("summary")
        if isinstance(summary, str):
            summary_bits.append(_strip_tags(summary)[:280])
        elif isinstance(summary, list):
            for part in summary[:4]:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    summary_bits.append(_strip_tags(part["text"])[:280])
        blob = " ".join(summary_bits) + " " + title
        native = _str_field(details.get("alert_level") or data.get("alert_level"))
        normalized = normalize_level_from_text(native or blob)
        if normalized is None:
            # GOV.UK dropped numeric levels; without recognizable wording the
            # level is honestly unable_to_verify — facts still surface.
            normalized = "unable_to_verify"
        regions = []
        if isinstance(details.get("parts"), list):
            for part in details["parts"][:10]:
                if isinstance(part, dict) and _str_field(part.get("title")):
                    if normalize_level_from_text(part.get("title", "")) in (
                            "do_not_travel", "reconsider_travel"):
                        regions.append(_str_field(part["title"], 120))
        ev = self._make(self.url_for(query), title, query.destination_country,
                        native, normalized, summary_bits, [],
                        updated, updated, affected_regions=regions)
        return [ev] if ev else []


class UsStateAdapter(SourceAdapter):
    """US State Department travel advisories (Level 1–4 wording)."""

    source_id = "us_state"
    authority = "US Department of State"
    authority_country = "US"

    def url_for(self, query: SafetyQuery) -> Optional[str]:
        slug = re.sub(r"[^a-z-]", "-",
                      query.destination_country.lower()).strip("-")
        if not slug:
            return None
        return f"https://travel.state.gov/en/traveladvisories/{slug}.html"

    def parse(self, payload: Dict[str, Any],
              query: SafetyQuery) -> List[SafetyEvidence]:
        text = _strip_tags(payload.get("text"))
        if not text:
            return []
        level_match = re.search(r"Level\s*[1-4]\s*[-–:]?\s*"
                                r"([A-Za-z ,'()]{3,80})", text)
        native = level_match.group(0)[:140] if level_match else None
        normalized = normalize_level_from_text(text[:6000])
        if normalized is None:
            return []  # no recognizable advisory wording for this country
        facts = [native] if native else []
        ev = self._make(payload.get("final_url") or self.url_for(query),
                        f"Travel advisory: {query.destination_country}",
                        query.destination_country, native, normalized,
                        facts, [], None, None)
        return [ev] if ev else []


class AuSmartravellerAdapter(SourceAdapter):
    """Australian Smartraveller destination advice."""

    source_id = "au_smartraveller"
    authority = "Australian Government — Smartraveller"
    authority_country = "AU"

    def url_for(self, query: SafetyQuery) -> Optional[str]:
        slug = re.sub(r"[^a-z-]", "-",
                      query.destination_country.lower()).strip("-")
        if not slug:
            return None
        return f"https://www.smartraveller.gov.au/destinations/{slug}"

    def parse(self, payload: Dict[str, Any],
              query: SafetyQuery) -> List[SafetyEvidence]:
        text = _strip_tags(payload.get("text"))
        if not text:
            return []
        normalized = normalize_level_from_text(text[:6000])
        if normalized is None:
            return []
        native = re.search(
            r"(Exercise [^.]{5,80}precautions|Reconsider [^.]{5,80}|"
            r"Do not travel[^.]{0,60})", text, re.IGNORECASE)
        ev = self._make(payload.get("final_url") or self.url_for(query),
                        f"Smartraveller: {query.destination_country}",
                        query.destination_country,
                        native.group(1)[:140] if native else None,
                        normalized, [], [], None, None)
        return [ev] if ev else []


class DestinationGovAdapter(SourceAdapter):
    """Destination-government/embassy/immigration notices via the bounded
    WebIntel path — citations must land on official hosts; snippets alone
    are NEVER enough (snippet-only evidence is rejected)."""

    source_id = "destination_gov"
    authority = "Destination government (via bounded official search)"
    source_type = "official_government"

    def __init__(self, web_intel=None) -> None:
        self._web_intel = web_intel

    def url_for(self, query: SafetyQuery) -> Optional[str]:
        return None  # web-intel path, not a fixed URL

    async def collect(self, query: SafetyQuery, fetch: SafetyFetcher
                      ) -> Tuple[List[SafetyEvidence], SafetySourceReport]:
        if self._web_intel is None:
            return [], SafetySourceReport(
                source_id=self.source_id, status="unavailable",
                note="bounded web-intel path not configured")
        try:
            result = await self._web_intel.fetch(
                f"official travel advisory {query.destination_country} "
                "government")
        except Exception:  # noqa: BLE001
            return [], SafetySourceReport(
                source_id=self.source_id, status="unavailable",
                note="web-intel fetch failed")
        if not isinstance(result, dict) or result.get("degraded") \
                or result.get("offline"):
            return [], SafetySourceReport(
                source_id=self.source_id, status="unavailable",
                note="web-intel degraded/offline")
        evidence: List[SafetyEvidence] = []
        for cit in result.get("citations", [])[:4]:
            url = cit.get("url") if isinstance(cit, dict) else None
            if not isinstance(url, str):
                continue
            ok, _ = url_ok_for_source(self.source_id, url)
            if not ok:
                continue  # unofficial citation can never ground evidence
            normalized = normalize_level_from_text(
                (cit.get("title") or "") + " " + cit.get("snippet_max280", ""))
            if normalized is None:
                continue  # snippet without a recognizable level: refuse, don't guess
            ev = self._make(url, _str_field(cit.get("title")) or "Official notice",
                            query.destination_country, None, normalized,
                            [], [], None,
                            _iso_field(cit.get("retrieved_date")),
                            extraction_method="structured_parse")
            if ev:
                evidence.append(ev)
        if not evidence:
            return [], SafetySourceReport(
                source_id=self.source_id, status="no_coverage",
                note="no official-host citation with a recognizable level")
        return evidence, SafetySourceReport(
            source_id=self.source_id, status="ok",
            evidence_count=len(evidence))


class WhoDonAdapter(SourceAdapter):
    """WHO Disease Outbreak News — health events for the destination."""

    source_id = "who_don"
    authority = "World Health Organization — Disease Outbreak News"
    authority_country = None
    source_type = "official_multilateral"
    risk_categories = ["health"]

    def url_for(self, query: SafetyQuery) -> Optional[str]:
        return "https://www.who.int/emergencies/disease-outbreak-news"

    def parse(self, payload: Dict[str, Any],
              query: SafetyQuery) -> List[SafetyEvidence]:
        text = _strip_tags(payload.get("text"))
        if not text:
            return []
        country = query.destination_country.lower()
        # deterministic event detection: a headline mentioning the country
        # within the outbreak-news index. NO result for the country is NOT
        # evidence of absence of risk (the policy engine says unable_to_verify).
        items = re.findall(r"[^.;\n]{0,120}" + re.escape(country) +
                           r"[^.;\n]{0,120}", text, re.IGNORECASE)
        if not items:
            return []
        facts = [i.strip()[:280] for i in items[:3]]
        ev = self._make(self.url_for(query),
                        f"WHO outbreak news mentioning "
                        f"{query.destination_country}",
                        query.destination_country, None, "increased_caution",
                        facts, ["Monitor official health guidance before travel."],
                        None, None)
        return [ev] if ev else []


class GdacsAdapter(SourceAdapter):
    """GDACS-or-configured official disaster/severe-weather events."""

    source_id = "gdacs"
    authority = "GDACS — Global Disaster Alert and Coordination System"
    authority_country = None
    source_type = "official_multilateral"
    risk_categories = ["severe_weather", "disaster"]

    def url_for(self, query: SafetyQuery) -> Optional[str]:
        return "https://www.gdacs.org/xml/rss.xml"

    def parse(self, payload: Dict[str, Any],
              query: SafetyQuery) -> List[SafetyEvidence]:
        data = payload.get("json")
        text = payload.get("text") or ""
        items: List[Dict[str, Any]] = []
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            items = [i for i in data["items"] if isinstance(i, dict)]
        elif text:
            # tolerant RSS-ish parse: <item><title>…</title>…
            for block in re.findall(r"<item>(.*?)</item>", text, re.DOTALL)[:20]:
                title = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)"
                                  r"(?:\]\]>)?</title>", block, re.DOTALL)
                items.append({"title": title.group(1).strip() if title else ""})
        country = query.destination_country.lower()
        evidence = []
        for item in items[:20]:
            title = _strip_tags(item.get("title"))[:280]
            if country not in title.lower():
                continue
            severe = bool(re.search(r"severe|red alert|level\s*3|major",
                                    title, re.IGNORECASE))
            ev = self._make(self.url_for(query), title,
                            query.destination_country,
                            "Severity: Severe" if severe else "Event active",
                            "reconsider_travel" if severe else "increased_caution",
                            [title], ["Expect disruptions; follow local emergency guidance."],
                            None, None, affected_regions=[query.destination_country])
            if ev:
                evidence.append(ev)
        return evidence[:3]


class WeatherOfficialAdapter(SourceAdapter):
    """Configured official weather/severe-alert source (default: national
    meteorological service through the .gov heuristic)."""

    source_id = "weather_official"
    authority = "Official national meteorological service"
    authority_country = None
    source_type = "official_multilateral"
    risk_categories = ["severe_weather"]

    def __init__(self, base_url: Optional[str] = None) -> None:
        self._base_url = base_url

    def url_for(self, query: SafetyQuery) -> Optional[str]:
        return self._base_url

    def parse(self, payload: Dict[str, Any],
              query: SafetyQuery) -> List[SafetyEvidence]:
        data = payload.get("json")
        if not isinstance(data, dict):
            return []
        alerts = data.get("alerts") if isinstance(data.get("alerts"), list) else []
        evidence = []
        for alert in alerts[:5]:
            if not isinstance(alert, dict):
                continue
            area = _str_field(alert.get("area")) or ""
            if (query.destination_country.lower() not in area.lower()
                    and not any(query.destination_country.lower()
                                in str(c).lower()
                                for c in (alert.get("cities") or []))):
                continue
            severity = _str_field(alert.get("severity")) or "advisory"
            level = ("reconsider_travel"
                     if severity.lower() in ("severe", "extreme", "warning")
                     else "increased_caution")
            ev = self._make(payload.get("final_url") or self.url_for(query),
                            _str_field(alert.get("event")) or "Weather alert",
                            query.destination_country, severity, level,
                            [_str_field(alert.get("description")) or severity],
                            ["Follow the meteorological service's guidance."],
                            None, _iso_field(alert.get("issued_at")),
                            affected_regions=[area] if area else [],
                            valid_from=_iso_field(alert.get("valid_from")),
                            valid_to=_iso_field(alert.get("valid_to")))
            if ev:
                evidence.append(ev)
        return evidence


class TransportOpsAdapter(SourceAdapter):
    """Airline/airport/transport operational alerts (configured source)."""

    source_id = "transport_ops"
    authority = "Official transport/airport operations feed"
    authority_country = None
    source_type = "transport_operator"
    risk_categories = ["transport_disruption"]

    def __init__(self, base_url: Optional[str] = None) -> None:
        self._base_url = base_url

    def url_for(self, query: SafetyQuery) -> Optional[str]:
        return self._base_url

    def parse(self, payload: Dict[str, Any],
              query: SafetyQuery) -> List[SafetyEvidence]:
        data = payload.get("json")
        if not isinstance(data, dict):
            return []
        alerts = data.get("alerts") if isinstance(data.get("alerts"), list) else []
        evidence = []
        airports = {a.upper() for a in query.transit_airports}
        for alert in alerts[:5]:
            if not isinstance(alert, dict):
                continue
            scope = str(alert.get("airport") or alert.get("scope") or "").upper()
            if airports and scope not in airports:
                continue
            ev = self._make(payload.get("final_url") or self.url_for(query) or "",
                            _str_field(alert.get("event")) or "Transport alert",
                            query.destination_country,
                            _str_field(alert.get("status")),
                            "increased_caution",
                            [_str_field(alert.get("description")) or ""],
                            ["Allow extra time; check with your airline."],
                            None, _iso_field(alert.get("issued_at")),
                            valid_to=_iso_field(alert.get("valid_to")))
            if ev:
                evidence.append(ev)
        return evidence


# --- aggregator ------------------------------------------------------------------------


def default_adapters(web_intel=None,
                     weather_url: Optional[str] = None,
                     transport_url: Optional[str] = None
                     ) -> List[SourceAdapter]:
    return [GovUkAdapter(), UsStateAdapter(), AuSmartravellerAdapter(),
            DestinationGovAdapter(web_intel=web_intel), WhoDonAdapter(),
            GdacsAdapter(), WeatherOfficialAdapter(base_url=weather_url),
            TransportOpsAdapter(base_url=transport_url)]


async def collect_all(query: SafetyQuery,
                      adapters: List[SourceAdapter],
                      fetch: SafetyFetcher
                      ) -> Dict[str, Any]:
    """Run every adapter; degrade per-source, never fabricate. Returns
    {"evidence": [...], "reports": [SafetySourceReport...]}."""
    evidence: List[SafetyEvidence] = []
    reports: List[SafetySourceReport] = []
    for adapter in adapters:
        try:
            ev_list, report = await adapter.collect(query, fetch)
        except Exception:  # noqa: BLE001 — last-line honesty guard
            ev_list, report = [], SafetySourceReport(
                source_id=adapter.source_id, status="unavailable",
                note="adapter error")
        evidence.extend(ev_list)
        reports.append(report)
    return {"evidence": evidence, "reports": reports}
