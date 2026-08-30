import os
import pytest
from config import Settings
from services.brain import active_brain, is_qwen_brain


def test_default_brain_is_legacy(monkeypatch):
    monkeypatch.delenv("TRAVELCARE_BRAIN", raising=False)
    s = Settings()
    assert s.travelcare_brain == "legacy"


def test_qwen_agent_flag(monkeypatch):
    monkeypatch.setenv("TRAVELCARE_BRAIN", "qwen_agent")
    s = Settings()
    assert s.travelcare_brain == "qwen_agent"


def test_garbage_flag_coerces_to_legacy(monkeypatch):
    monkeypatch.setenv("TRAVELCARE_BRAIN", "unknown_brain_value")
    s = Settings()
    assert s.travelcare_brain == "legacy"


def test_brain_module_accessors(monkeypatch):
    monkeypatch.setenv("TRAVELCARE_BRAIN", "qwen_agent")
    assert is_qwen_brain() is True
    assert active_brain() == "qwen_agent"

    monkeypatch.setenv("TRAVELCARE_BRAIN", "legacy")
    assert is_qwen_brain() is False
    assert active_brain() == "legacy"


def test_env_example_declares_brain_flag_and_provider_keys():
    """Audit finding #10: .env.example must declare TRAVELCARE_BRAIN with a
    safe default, the OpenRouter fallback key slot, and document DEMO_MODEL
    instead of leaving it as an undocumented override."""
    from pathlib import Path as _Path
    text = _Path(__file__).resolve().parent.parent.joinpath(".env.example").read_text()
    assert "TRAVELCARE_BRAIN=legacy" in text
    assert "OPENROUTER_API_KEY=" in text
    assert "DEMO_MODEL" in text, "DEMO_MODEL must be documented (or removed)"
