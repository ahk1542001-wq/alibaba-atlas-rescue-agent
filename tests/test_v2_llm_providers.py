"""Audit finding #8: llm_providers health cache must have a TTL with
re-probe, identical unhealthy classification (429/401/5xx/timeout) in BOTH
the resolve path and chat_with_fallback, success-path cache updates, and an
active_provider() that reads the name recorded at resolution time.
"""
import pytest

from services import llm_providers as lp
from services.llm_providers import ProviderError


@pytest.fixture(autouse=True)
def _reset_provider_state(monkeypatch):
    monkeypatch.setattr(lp, "_PROVIDER_HEALTH", {})
    monkeypatch.setattr(lp, "_RESOLVED_PROVIDER", None)
    monkeypatch.setattr(lp, "_LAST_OUTCOME", {"primary": "unprobed", "fallback": "unprobed", "served_by": None})
    monkeypatch.delenv("ALIBABA_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    yield


def test_health_cache_expires_and_reprobes_after_ttl(monkeypatch):
    monkeypatch.setenv("ALIBABA_MODEL_API_KEY", "sk-test-primary")
    calls = []

    def fake_raw(name, messages, **kwargs):
        calls.append(name)
        return "pong"

    monkeypatch.setattr(lp, "_call_provider_raw", fake_raw)
    clock = [1000.0]
    monkeypatch.setattr(lp.time, "monotonic", lambda: clock[0])

    assert lp._probe_provider_health("modelscope") is True
    assert lp._probe_provider_health("modelscope") is True
    assert len(calls) == 1, "fresh cache must suppress re-probe"

    clock[0] += lp.HEALTH_TTL_SECONDS + 1.0
    assert lp._probe_provider_health("modelscope") is True
    assert len(calls) == 2, "expired cache must trigger re-probe"


@pytest.mark.parametrize("status_code", [429, 401, 503, 408])
def test_chat_path_marks_unhealthy_for_classified_errors(monkeypatch, status_code):
    monkeypatch.setenv("ALIBABA_MODEL_API_KEY", "sk-test-primary")

    def raise_err(name, messages, **kwargs):
        raise ProviderError(f"HTTP {status_code}", status_code=status_code)

    monkeypatch.setattr(lp, "_call_provider_raw", raise_err)
    content, prov = lp.chat_with_fallback([{"role": "user", "content": "hi"}])
    assert content is None and prov is None
    entry = lp._PROVIDER_HEALTH.get("modelscope")
    assert entry is not None and entry[0] is False, (
        f"chat path must record unhealthy for HTTP {status_code}"
    )


def test_chat_success_updates_health_cache(monkeypatch):
    monkeypatch.setenv("ALIBABA_MODEL_API_KEY", "sk-test-primary")
    monkeypatch.setattr(lp, "_call_provider_raw", lambda *a, **k: "ok")

    content, prov = lp.chat_with_fallback([{"role": "user", "content": "hi"}])
    assert content == "ok" and prov == "modelscope"
    entry = lp._PROVIDER_HEALTH.get("modelscope")
    assert entry is not None and entry[0] is True


def test_resolve_skips_cached_unhealthy_without_reprobing(monkeypatch):
    monkeypatch.setenv("ALIBABA_MODEL_API_KEY", "sk-test-primary")
    calls = []

    def flaky_raw(name, messages, **kwargs):
        calls.append(name)
        raise ProviderError("HTTP 429", status_code=429)

    monkeypatch.setattr(lp, "_call_provider_raw", flaky_raw)
    clock = [1000.0]
    monkeypatch.setattr(lp.time, "monotonic", lambda: clock[0])

    assert lp.resolve_llm_cfg() is None
    assert len(calls) == 1
    assert lp.resolve_llm_cfg() is None
    assert len(calls) == 1, "cached-unhealthy provider must not be re-probed inside TTL"

    clock[0] += lp.HEALTH_TTL_SECONDS + 1.0
    assert lp.resolve_llm_cfg() is None
    assert len(calls) == 2, "resolve path must re-probe after TTL expiry"


def test_resolve_and_chat_paths_classify_timeout_identically(monkeypatch):
    monkeypatch.setenv("ALIBABA_MODEL_API_KEY", "sk-test-primary")

    def timeout_raw(name, messages, **kwargs):
        raise ProviderError("Request timed out", status_code=408)

    monkeypatch.setattr(lp, "_call_provider_raw", timeout_raw)
    assert lp.resolve_llm_cfg() is None
    assert lp._PROVIDER_HEALTH["modelscope"][0] is False

    lp._PROVIDER_HEALTH.clear()
    content, prov = lp.chat_with_fallback([{"role": "user", "content": "hi"}])
    assert content is None
    assert lp._PROVIDER_HEALTH["modelscope"][0] is False


def test_active_provider_reads_recorded_name_without_probing(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    calls = []

    def fake_raw(name, messages, **kwargs):
        calls.append(name)
        return "pong"

    monkeypatch.setattr(lp, "_call_provider_raw", fake_raw)

    assert lp.active_provider() == "none", "cold cache must not trigger a probe"
    assert calls == []

    cfg = lp.resolve_llm_cfg()
    assert cfg is not None
    probe_count = len(calls)
    assert lp.active_provider() == "openrouter"
    assert len(calls) == probe_count, "active_provider() must not probe providers"
