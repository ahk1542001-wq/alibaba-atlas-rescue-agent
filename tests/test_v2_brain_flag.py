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
