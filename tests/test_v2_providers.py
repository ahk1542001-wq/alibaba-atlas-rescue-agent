import logging
import pytest
from unittest.mock import patch, MagicMock
from services import llm_providers


def test_resolve_llm_cfg_shape_and_no_stream(monkeypatch):
    monkeypatch.setenv("ALIBABA_MODEL_API_KEY", "test_alibaba_key_123")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test_openrouter_key_456")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    
    # Mock probe to treat modelscope as healthy
    monkeypatch.setattr(llm_providers, "_probe_provider_health", lambda name: True)
    
    cfg = llm_providers.resolve_llm_cfg()
    assert cfg is not None
    assert cfg["model"] == "Qwen/Qwen3-235B-A22B-Instruct-2507"
    assert cfg["model_server"] == "https://api-inference.modelscope.ai/v1"
    assert cfg["api_key"] == "test_alibaba_key_123"
    assert "generate_cfg" in cfg
    assert "stream" not in cfg["generate_cfg"]
    assert cfg["generate_cfg"]["fncall_prompt_type"] == "nous"
    assert cfg["generate_cfg"]["extra_body"] == {"enable_thinking": False}


def test_skip_missing_and_placeholder_keys(monkeypatch):
    monkeypatch.setenv("ALIBABA_MODEL_API_KEY", "your_alibaba_key_here")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    
    cfg = llm_providers.resolve_llm_cfg()
    assert cfg is None
    assert llm_providers.active_provider() == "none"


def test_fallback_to_openrouter_when_modelscope_unhealthy(monkeypatch):
    monkeypatch.setenv("ALIBABA_MODEL_API_KEY", "test_ms_key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test_or_key")
    
    # ModelScope fails probe (e.g. 429), OpenRouter succeeds
    def mock_probe(name):
        return name == "openrouter"
    
    monkeypatch.setattr(llm_providers, "_probe_provider_health", mock_probe)
    
    cfg = llm_providers.resolve_llm_cfg()
    assert cfg is not None
    assert cfg["model"] == "qwen/qwen3-235b-a22b-2507"
    assert cfg["model_server"] == "https://openrouter.ai/api/v1"
    assert cfg["api_key"] == "test_or_key"
    assert llm_providers.active_provider() == "openrouter"


def test_chat_with_fallback_modelscope_success(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv("ALIBABA_MODEL_API_KEY", "ms_secret_val_12345")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or_secret_val_67890")

    def mock_call_provider(name, messages, **kwargs):
        if name == "modelscope":
            return "MS response"
        raise RuntimeError("Should not call fallback")

    monkeypatch.setattr(llm_providers, "_call_provider_raw", mock_call_provider)
    
    reply, provider = llm_providers.chat_with_fallback([{"role": "user", "content": "hello"}])
    assert reply == "MS response"
    assert provider == "modelscope"
    assert "ms_secret_val_12345" not in caplog.text
    assert "or_secret_val_67890" not in caplog.text


def test_chat_with_fallback_modelscope_429_calls_openrouter(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv("ALIBABA_MODEL_API_KEY", "ms_secret_val_12345")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or_secret_val_67890")

    calls = []
    def mock_call_provider(name, messages, **kwargs):
        calls.append(name)
        if name == "modelscope":
            raise llm_providers.ProviderError("HTTP 429 Too Many Requests", status_code=429)
        if name == "openrouter":
            return "OpenRouter response"
        raise RuntimeError("Unknown provider")

    monkeypatch.setattr(llm_providers, "_call_provider_raw", mock_call_provider)
    
    reply, provider = llm_providers.chat_with_fallback([{"role": "user", "content": "hello"}])
    assert calls == ["modelscope", "openrouter"]
    assert reply == "OpenRouter response"
    assert provider == "openrouter"
    assert "ms_secret_val_12345" not in caplog.text
    assert "or_secret_val_67890" not in caplog.text
    
    outcome = llm_providers.last_provider_outcome()
    assert outcome["primary"] == "http_429"
    assert outcome["fallback"] == "ok"
    assert outcome["served_by"] == "openrouter"


def test_chat_with_fallback_both_fail(monkeypatch):
    monkeypatch.setenv("ALIBABA_MODEL_API_KEY", "ms_key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or_key")

    def mock_call_provider(name, messages, **kwargs):
        raise llm_providers.ProviderError("HTTP 500", status_code=500)

    monkeypatch.setattr(llm_providers, "_call_provider_raw", mock_call_provider)
    
    reply, provider = llm_providers.chat_with_fallback([{"role": "user", "content": "hello"}])
    assert reply is None
    assert provider is None
    outcome = llm_providers.last_provider_outcome()
    assert outcome["served_by"] is None
