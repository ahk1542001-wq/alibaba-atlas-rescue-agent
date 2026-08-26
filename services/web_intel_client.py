"""Web-intel client (G2 behavior) — §4 S7 / §14.4.

Provider chain: tavily → serper → ddg_lite → static_fallback. Only tiers
whose env keys are present at runtime go active (ddg_lite and
static_fallback are keyless). TTL cache is a plain dict keyed by query;
cache hits are counted so tests can prove a second lookup avoids a fetch.

Hostile-data stance (§14.4): fetched content is inert strings only — never
instructions, never executed; citations render as text. Parsing is TOLERANT:
a provider layout change (missing keys, wrong types, junk entries) degrades
field-by-field instead of raising. Any total failure degrades to an honest
null result ({degraded, offline}) — never an exception to the caller.
"""

import time
from datetime import date, datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

PROVIDER_CHAIN = ("tavily", "serper", "ddg_lite", "static_fallback")
KEYLESS_PROVIDERS = {"ddg_lite", "static_fallback"}

# Injectable transport for the keyless ddg_lite tier (tests inject fakes;
# production wiring lands with the real provider integrations at G3).
DDGFetcher = Callable[[str], Awaitable[Optional[Dict[str, Any]]]]


def _valid_citation_date(raw: Any) -> Optional[str]:
    """An ISO-parseable citation date string, or None. Dates are never invented:
    a missing/unparseable provenance date is a missing fact, not today()."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        date.fromisoformat(raw.strip()[:10])
    except ValueError:
        return None
    return raw.strip()


def _has_source_url(item: Any) -> bool:
    return (isinstance(item, dict) and isinstance(item.get("url"), str)
            and bool(item.get("url").strip()))


def _tolerant_citations(raw: Any,
                        fetched_at: Optional[str] = None) -> List[Dict[str, Any]]:
    """Normalize hostile/messy citation payloads; drop anything unusable.

    HONESTY RULE (G2-DA fix): citations without a parseable retrieved_date are
    DROPPED — stamping date.today() onto them laundered missing provenance
    into "fresh" and let stale-gated bookings through. If no dated citation
    survives, downstream freshness resolves to "unknown" and the booking gate
    refuses. fetched_at (real fetch timestamp) is attached when known so
    freshness can age sub-day precision against a real clock.
    """
    out: List[Dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not isinstance(url, str) or not url.strip():
            continue  # citation without a source link is worthless — drop, don't invent
        retrieved = _valid_citation_date(item.get("retrieved_date"))
        if retrieved is None:
            continue  # undated citation: drop, never backdate (G2-DA fix)
        snippet = item.get("snippet") or item.get("snippet_max280") or ""
        if not isinstance(snippet, str):
            snippet = ""
        entry: Dict[str, Any] = {
            "url": url.strip(),
            "title": item.get("title") if isinstance(item.get("title"), str) else "",
            "retrieved_date": retrieved,
            "snippet_max280": snippet[:280],
        }
        stamp = item.get("fetched_at")
        stamp = stamp if isinstance(stamp, str) and stamp else fetched_at
        if stamp:
            entry["fetched_at"] = stamp
        out.append(entry)
    return out


def _tolerant_answers(raw: Any) -> List[str]:
    if not isinstance(raw, list):
        return []
    return [a for a in raw if isinstance(a, str) and a.strip()]


class WebIntelClient:
    def __init__(
        self,
        tavily_api_key: str = "",
        serper_api_key: str = "",
        cache_ttl_hours: int = 24,
        ddg_fetcher: Optional[DDGFetcher] = None,
    ) -> None:
        self._keys = {
            "tavily": tavily_api_key,
            "serper": serper_api_key,
        }
        self.cache_ttl_seconds = cache_ttl_hours * 3600
        # query -> {"fetched_at": monotonic, "result": {...}}
        self._cache: Dict[str, Dict[str, Any]] = {}
        self.fetch_count = 0   # real provider fetches (tests count these)
        self.cache_hits = 0    # TTL-cache-served lookups (tests count these)
        self._ddg_fetcher = ddg_fetcher

    # -- provider selection ----------------------------------------------------

    def active_providers(self) -> List[str]:
        return [
            p
            for p in PROVIDER_CHAIN
            if p in KEYLESS_PROVIDERS or self._keys.get(p)
        ]

    # -- cache -----------------------------------------------------------------

    def _cache_get(self, query: str) -> Optional[Dict[str, Any]]:
        entry = self._cache.get(query)
        if entry and time.monotonic() - entry["fetched_at"] < self.cache_ttl_seconds:
            return entry["result"]
        return None

    def _cache_put(self, query: str, result: Dict[str, Any]) -> None:
        self._cache[query] = {"fetched_at": time.monotonic(), "result": result}

    # -- provider tiers ----------------------------------------------------------

    async def _tier_keyed(self, provider: str, query: str) -> Dict[str, Any]:
        """Tavily/Serper transport. Without a wired transport for a keyed tier
        the result is an honest degraded null (key presence != fetch success)."""
        return {
            "provider": provider,
            "degraded": True,
            "offline": False,
            "answers": [],
            "citations": [],
            "note": f"{provider} key configured; transport not wired in this build",
        }

    async def _tier_ddg_lite(self, query: str) -> Dict[str, Any]:
        if self._ddg_fetcher is None:
            raise ConnectionError("ddg_lite transport not configured")
        raw = await self._ddg_fetcher(query)
        if not isinstance(raw, dict):
            raise ValueError("ddg_lite returned non-mapping envelope")
        fetched_at = datetime.now(timezone.utc).isoformat()  # real clock
        raw_citations = raw.get("citations")
        citations = _tolerant_citations(raw_citations, fetched_at=fetched_at)
        undated_dropped = sum(
            1 for item in (raw_citations if isinstance(raw_citations, list) else [])
            if _has_source_url(item)
            and _valid_citation_date(item.get("retrieved_date")) is None)
        return {
            "provider": "ddg_lite",
            "degraded": False,
            "offline": False,
            "fetched_at": fetched_at,
            "undated_citations_dropped": undated_dropped,
            "answers": _tolerant_answers(raw.get("answers")),
            "citations": citations,
        }

    def _static_fallback(self, offline: bool) -> Dict[str, Any]:
        return {
            "provider": "static_fallback",
            "degraded": True,
            "offline": offline,
            "answers": [],
            "citations": [],
        }

    # -- fetch ----------------------------------------------------------------------

    async def fetch(self, query: str) -> Dict[str, Any]:
        """TTL-cached lookup down the provider chain; degrades, never raises.

        Returns inert-string citations only. Every degraded result carries an
        honest flag so callers (visa/legal answers) can refuse to overclaim.
        """
        cached = self._cache_get(query)
        if cached is not None:
            self.cache_hits += 1
            return cached
        self.fetch_count += 1

        result: Optional[Dict[str, Any]] = None
        offline = True
        for provider in self.active_providers():
            if provider == "static_fallback":
                break
            try:
                if provider in KEYLESS_PROVIDERS:
                    result = await self._tier_ddg_lite(query)
                else:
                    offline = False
                    result = await self._tier_keyed(provider, query)
                break
            except Exception:  # noqa: BLE001 — hostile web: degrade, never raise
                continue
        if result is None:
            result = self._static_fallback(offline=offline)
        # honest aging: the envelope carries the REAL fetch timestamp; cached
        # hits keep the original stamp so age never resets on cache reads
        result.setdefault("fetched_at", datetime.now(timezone.utc).isoformat())
        self._cache_put(query, result)
        return result
