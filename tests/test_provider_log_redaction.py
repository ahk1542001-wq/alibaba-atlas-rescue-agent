import asyncio
import json
import logging

import services.atlas_client as atlas_module
import services.llm as llm
from config import settings
from services.atlas_client import AtlasClient
from services.radar import RescueRadar


SENTINEL = "SENTINEL_PROVIDER_SECRET"


def test_custom_llm_provider_name_never_exposes_configured_url(monkeypatch):
    monkeypatch.setattr(settings, "model_api_key", "configured-key")
    monkeypatch.setattr(
        settings,
        "llm_base_url",
        f"https://provider.example/private/{SENTINEL}",
    )

    assert llm.provider_name() == "custom_openai_compatible"
    assert SENTINEL not in llm.provider_name()


def test_llm_parse_and_call_failures_do_not_log_raw_content(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    assert llm.parse_json(f'{{"secret": {SENTINEL}}}') is None

    class FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            raise RuntimeError(SENTINEL)

    monkeypatch.setattr(
        llm,
        "_provider",
        lambda: ("https://provider.example", "configured-key"),
    )
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kwargs: FailingClient())
    assert asyncio.run(llm.chat([{"role": "user", "content": "hello"}])) is None
    assert SENTINEL not in caplog.text


def test_atlas_cli_exception_and_provider_message_are_redacted(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(atlas_module.settings, "atlas_use_cli", True)
    monkeypatch.setattr(atlas_module.shutil, "which", lambda binary: "/bin/atlas-flight")
    client = AtlasClient()

    async def explode(*args, **kwargs):
        raise RuntimeError(SENTINEL)

    monkeypatch.setattr(atlas_module.asyncio, "create_subprocess_exec", explode)
    assert asyncio.run(client._run_cli(["search"])) is None
    assert SENTINEL not in caplog.text

    class ProviderResponse:
        async def communicate(self):
            return (
                json.dumps({
                    "status": "action_required",
                    "code": "AUTH_REQUIRED",
                    "message": SENTINEL,
                }).encode(),
                b"",
            )

    async def provider_response(*args, **kwargs):
        return ProviderResponse()

    caplog.clear()
    monkeypatch.setattr(
        atlas_module.asyncio,
        "create_subprocess_exec",
        provider_response,
    )
    assert asyncio.run(client._run_cli(["search"])) is None
    assert SENTINEL not in caplog.text
    assert SENTINEL not in json.dumps(client.last_cli_envelope)


def test_radar_does_not_log_raw_status_or_plan_exceptions(caplog):
    caplog.set_level(logging.WARNING)

    class FailingStatusAtlas:
        async def get_flight_status(self, flight_number, date):
            raise RuntimeError(SENTINEL)

    class UnusedEngine:
        pass

    radar = RescueRadar(FailingStatusAtlas(), UnusedEngine())
    radar.watchlist = [{"flight_number": "ZZ999", "date": "2030-01-01"}]
    result = asyncio.run(radar.scan())
    assert result["flights"][0]["status"] == "UNKNOWN"
    assert SENTINEL not in caplog.text

    class DisruptedAtlas:
        async def get_flight_status(self, flight_number, date):
            return {
                "flight_number": flight_number,
                "status": "CANCELLED",
                "reason": "sandbox fixture",
            }

    class FailingPlanEngine:
        async def handle_disruption(self, **kwargs):
            raise RuntimeError(SENTINEL)

    caplog.clear()
    radar = RescueRadar(DisruptedAtlas(), FailingPlanEngine())
    radar.watchlist = [{"flight_number": "TG303", "date": "2030-01-01"}]
    result = asyncio.run(radar.scan())
    assert result["new_alerts"][0]["rescue_plan"] is None
    assert SENTINEL not in caplog.text
