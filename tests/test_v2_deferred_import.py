"""Audit finding #9: when the qwen-agent package is absent, the deferred
qwen_brain imports must NOT produce a raw 500 — the app must serve a
LABELED legacy fallback instead.
"""
import importlib.util
import json

import pytest
from fastapi.testclient import TestClient
from main import app

from services import brain


@pytest.fixture()
def _block_qwen_agent(monkeypatch):
    real_find_spec = importlib.util.find_spec

    def blocked(name, *args, **kwargs):
        if name == "qwen_agent":
            return None
        return real_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", blocked)
    yield


def test_qwen_brain_available_false_when_package_absent(_block_qwen_agent):
    assert brain.qwen_brain_available() is False


def test_trip_start_labeled_legacy_fallback_when_package_missing(
    _block_qwen_agent, monkeypatch
):
    monkeypatch.setenv("TRAVELCARE_BRAIN", "qwen_agent")
    client = TestClient(app)
    res = client.post("/api/trip/start", json={
        "goal_text": "Fly from BKK to RGN on 2026-09-28 to 2026-09-30",
        "user_id": "deferred_import_trip_tester",
    })
    assert res.status_code == 200, "must NOT be a raw 500 when qwen-agent is absent"
    trip_id = res.json()["trip_id"]
    state = client.get(f"/api/trip/{trip_id}/state").json()
    assert "legacy_fallback" in json.dumps(state), (
        "goal-intake record must carry the labeled legacy fallback marker"
    )


def test_concierge_labeled_legacy_fallback_when_package_missing(
    _block_qwen_agent, monkeypatch
):
    monkeypatch.setenv("TRAVELCARE_BRAIN", "qwen_agent")
    client = TestClient(app)
    res = client.post("/api/chat/concierge", json={
        "query": "Hello concierge, can you help me?",
        "user_id": "deferred_import_concierge_tester",
    })
    assert res.status_code == 200, "must NOT be a raw 500 when qwen-agent is absent"
    data = res.json()
    assert data.get("brain_fallback") == "legacy_fallback"
    assert "reply" in data and "action_taken" in data
