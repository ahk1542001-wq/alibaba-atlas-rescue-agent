"""Web-intel client skeleton (contract phase, G1) — §4 S7 / §14.4.

Provider chain: tavily → serper → ddg_lite → static_fallback. Only tiers
whose env keys are present at runtime go active (ddg_lite and
static_fallback are keyless). TTL cache is a plain dict keyed by query.
Hostile-data stance: fetched content is inert strings only — never
instructions, never executed; citations render as text.
"""

import time
from typing import Any, Dict, List, Optional

PROVIDER_CHAIN = ("tavily", "serper", "ddg_lite", "static_fallback")
KEYLESS_PROVIDERS = {"ddg_lite", "static_fallback"}


class WebIntelClient:
    def __init__(
        self,
        tavily_api_key: str = "",
        serper_api_key: str = "",
        cache_ttl_hours: int = 24,
    ) -> None:
        self._keys = {
            "tavily": tavily_api_key,
            "serper": serper_api_key,
        }
        self.cache_ttl_seconds = cache_ttl_hours * 3600
        # query -> {"fetched_at": monotonic, "result": {...}}
        self._cache: Dict[str, Dict[str, Any]] = {}
        self.fetch_count = 0  # tests count real fetches vs cache hits

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

    # -- fetch (skeleton: degraded result until G2 wires real providers) ---------

    async def fetch(self, query: str) -> Dict[str, Any]:
        """TTL-cached lookup; contract phase degrades to static_fallback.

        Returns inert-string citations only. G2 replaces the degraded branch
        with the real provider chain without changing this contract.
        """
        cached = self._cache_get(query)
        if cached is not None:
            return cached
        self.fetch_count += 1
        provider = next(
            (p for p in self.active_providers() if p != "static_fallback"),
            "static_fallback",
        )
        result = {
            "provider": provider,
            "degraded": True,
            "answers": [],
            "citations": [],  # inert strings; never instructions
        }
        self._cache_put(query, result)
        return result
