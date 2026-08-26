"""G2 behavior tests for the §4 S7 web-intel client.

Covers: TTL cache is counted (second lookup avoids a real fetch), offline
degrade (provider failure -> degraded null, never an exception), tolerant
parsing (hostile/messy provider payloads survive with fields defaulted and
snippets truncated), and TTL expiry forcing a refetch. Fetched content is
inert data: snippets are plain strings, never executed.
"""

import asyncio

from services.web_intel_client import WebIntelClient


def _run(coro):
    return asyncio.run(coro)


class CallCounter:
    """Injectable fetcher: counts real provider calls; result configurable."""

    def __init__(self, result=None, exc=None):
        self.calls = 0
        self.result = result
        self.exc = exc

    async def __call__(self, query: str):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return self.result


# --- cache counting ----------------------------------------------------------

def test_cache_hit_avoids_second_fetch():
    fetcher = CallCounter(result={"answers": ["a"], "citations": []})
    client = WebIntelClient(ddg_fetcher=fetcher)
    first = _run(client.fetch("hotels near Marina Bay Sands"))
    second = _run(client.fetch("hotels near Marina Bay Sands"))
    assert fetcher.calls == 1  # second lookup served from TTL cache
    assert client.cache_hits == 1
    assert first["answers"] == second["answers"]
    assert first["degraded"] is False


def test_distinct_queries_each_fetch_once():
    fetcher = CallCounter(result={"answers": [], "citations": []})
    client = WebIntelClient(ddg_fetcher=fetcher)
    _run(client.fetch("q1"))
    _run(client.fetch("q2"))
    _run(client.fetch("q1"))
    assert fetcher.calls == 2
    assert client.cache_hits == 1


def test_ttl_expiry_forces_refetch():
    fetcher = CallCounter(result={"answers": ["x"], "citations": []})
    client = WebIntelClient(ddg_fetcher=fetcher, cache_ttl_hours=24)
    _run(client.fetch("q"))
    # age the entry beyond the TTL window
    entry = client._cache["q"]
    entry["fetched_at"] -= client.cache_ttl_seconds + 1
    _run(client.fetch("q"))
    assert fetcher.calls == 2


# --- offline / failure degrade -------------------------------------------------

def test_offline_degrades_to_null_not_exception():
    fetcher = CallCounter(exc=ConnectionError("network down"))
    client = WebIntelClient(ddg_fetcher=fetcher)
    result = _run(client.fetch("visa rules MM to SG"))
    assert result["degraded"] is True
    assert result["offline"] is True
    assert result["answers"] == []
    assert result["citations"] == []
    assert result["provider"] == "static_fallback"


def test_malformed_provider_payload_degrades_honestly():
    fetcher = CallCounter(exc=ValueError("bad envelope"))
    client = WebIntelClient(ddg_fetcher=fetcher)
    result = _run(client.fetch("anything"))
    assert result["degraded"] is True
    assert result["answers"] == []


# --- tolerant parsing ---------------------------------------------------------

def test_tolerant_parse_survives_missing_fields():
    # DDG-layout-change simulation: items missing title/snippet/url pieces
    fetcher = CallCounter(result={
        "answers": [None, 42, "real answer"],
        "citations": [
            {"title": "ok", "url": "https://example.org/a"},
            {"title": None},                     # no url -> dropped
            "not-a-mapping",                     # hostile junk -> dropped
            {"url": "https://example.org/b", "snippet": "s"},
        ],
    })
    client = WebIntelClient(ddg_fetcher=fetcher)
    result = _run(client.fetch("messy layout"))
    assert result["degraded"] is False
    assert result["answers"] == ["real answer"]  # non-string answers dropped
    urls = [c["url"] for c in result["citations"]]
    assert urls == ["https://example.org/a", "https://example.org/b"]
    for c in result["citations"]:
        assert c["retrieved_date"]  # stamped even when provider omits it


def test_tolerant_parse_truncates_oversized_snippets():
    fetcher = CallCounter(result={
        "answers": [],
        "citations": [{"url": "https://example.org", "title": "t",
                       "snippet": "x" * 500}],
    })
    client = WebIntelClient(ddg_fetcher=fetcher)
    result = _run(client.fetch("long snippet"))
    assert len(result["citations"][0]["snippet_max280"]) <= 280


def test_provider_selection_prefers_keyed_tier_over_ddg():
    fetcher = CallCounter(result={"answers": [], "citations": []})
    client = WebIntelClient(tavily_api_key="tvly-test", ddg_fetcher=fetcher)
    assert client.active_providers()[0] == "tavily"
