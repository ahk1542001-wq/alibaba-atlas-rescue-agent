"""Tests for Gate G6: Atlas Ticketing Capability Boundary."""

import pytest
import asyncio
from models.schemas import AtlasCapabilityBoundary
from services.atlas_client import AtlasClient, AtlasTicketingUnavailableError
from services.skills.flight_book import FlightBookSkill
from services.skills.base import SkillError


def test_capability_boundary_object_has_eight_fields():
    client = AtlasClient()
    boundary = client.get_capability_boundary()
    required_fields = {
        "search_available",
        "verification_available",
        "order_creation_available",
        "payment_available",
        "ticketing_available",
        "blocker_code",
        "activation_url",
        "environment",
    }
    assert required_fields.issubset(set(boundary.keys()))
    assert boundary["ticketing_available"] is False
    assert boundary["payment_available"] is False
    assert boundary["activation_url"] is None
    assert boundary["environment"] == "sandbox"

    # Schema model test
    schema = AtlasCapabilityBoundary()
    assert schema.activation_url is None
    assert schema.blocker_code is None
    assert schema.ticketing_available is False
    assert schema.payment_available is False
    assert schema.order_creation_available is False


def test_production_environment_can_never_be_selected():
    client = AtlasClient()
    with pytest.raises((ValueError, RuntimeError, TypeError)):
        # Attempting to set production environment must fail closed
        AtlasClient(environment="production")


def test_unsupported_payment_methods_fail_closed():
    client = AtlasClient()
    boundary = client.get_capability_boundary()
    assert boundary["payment_available"] is False


def test_ticketing_activation_required_does_not_fabricate_pnr():
    class BlockedAtlas:
        async def verify_fare(self, offer_id: str):
            raise AtlasTicketingUnavailableError(
                "TICKETING_ACTIVATION_REQUIRED",
                "Atlas Sandbox ticketing is not activated for this account."
            )

    skill = FlightBookSkill(atlas=BlockedAtlas())
    with pytest.raises(SkillError) as exc_info:
        asyncio.run(skill.run({
            "trip_id": "t1",
            "option_id": "opt_test",
            "origin": "BKK",
            "destination": "SIN",
        }, context={"visa_check": {"freshness_state": "fresh", "visa_blocked": False, "passport_unknown": False}}))
    assert exc_info.value.code == "atlas_ticketing_unavailable"
    assert exc_info.value.recoverable is True
