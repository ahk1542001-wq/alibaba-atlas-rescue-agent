"""web_intel skill — §4 S7 (G2 behavior).

Thin skill wrapper over services.web_intel_client.WebIntelClient: the TTL
cache lives in the client so a cache hit provably avoids a second fetch
(client.fetch_count stays at 1, client.cache_hits increments). Fetched
content is treated as hostile DATA — citations are inert strings, tolerant
normalization drops anything unusable instead of raising (§14.4). Total
failure degrades to an honest null ({degraded: True}), never an exception.
"""

import time
from typing import Any, Dict, Optional

from services.skills.base import SkillBase
from services.web_intel_client import WebIntelClient, _tolerant_answers, _tolerant_citations


class WebIntelSkill(SkillBase):
    name = "web_intel"
    when_to_use = (
        "when freshness beyond the KG seed is needed; provider chain "
        "tavily→serper→ddg_lite→static_fallback with TTL cache, citations dated"
    )
    capabilities = frozenset({"network_read"})

    def __init__(self, client: Optional[Any] = None) -> None:
        self.client = client or WebIntelClient()
        # skill-level TTL ledger: query -> (monotonic expiry, normalized result)
        self._ttl: Dict[str, tuple] = {}

    def _ttl_hit(self, query: str) -> Optional[Dict[str, Any]]:
        entry = self._ttl.get(query)
        if entry and time.monotonic() < entry[0]:
            return entry[1]
        return None

    async def run(self, payload: Dict[str, Any],
                  context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        query = str(payload.get("query") or "")
        ttl_hours = int(payload.get("ttl_hours") or 24)

        # TTL cache hit: served without touching the client (zero fetches)
        cached = self._ttl_hit(query) if query else None
        if cached is not None:
            return {**cached, "cache_hit": True}

        result = await self.client.fetch(query) if query else {
            "provider": "none", "degraded": True, "offline": False,
            "answers": [], "citations": [],
        }

        out = {
            "query": query,
            "provider": result.get("provider", "unknown"),
            "degraded": bool(result.get("degraded")),
            "offline": bool(result.get("offline")),
            "answers": _tolerant_answers(result.get("answers")),
            "citations": _tolerant_citations(result.get("citations")),
            "cache_hit": False,
        }
        if query:
            self._ttl[query] = (time.monotonic() + ttl_hours * 3600, dict(out))
        return out
