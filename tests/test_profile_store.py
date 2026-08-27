"""Contract tests for the profile store (canonical R1 contract).

Profile files live under a tmp dir per test (never the real data/profiles/).
Covers: safe field allowlist, forbidden field rejection, source tagging,
delete semantics, consent gating, atomic write permissions, safe display,
old-profile migration, and user_id charset validation.
"""

import json
import os
import stat
from pathlib import Path

import pytest
from pydantic import ValidationError

from models.schemas import (
    FORBIDDEN_PROFILE_FIELDS,
    SAFE_PROFILE_FIELDS,
    FlightOption,
    Profile,
    WebIntelCitation,
)
from services.profile_store import ProfileStore


# --- store basics ------------------------------------------------------------

@pytest.fixture()
def store(tmp_path: Path) -> ProfileStore:
    return ProfileStore(root=tmp_path)


def test_new_profile_starts_empty(store: ProfileStore):
    profile = store.get_or_create("victor")
    assert profile.user_id == "victor"
    assert profile.identity.passport_country is None
    assert profile.identity.home_city is None
    assert not hasattr(profile.identity, "passport_no")
    assert not hasattr(profile.identity, "passport_no_masked")
    assert not hasattr(profile.identity, "expiry")
    assert profile.fields == {}
    assert profile.consent.store_local is False


def test_no_file_written_without_consent(store: ProfileStore, tmp_path: Path):
    store.get_or_create("victor")
    store.set_field("victor", "home_city", "Bangkok", source="ai_inferred")
    assert list(tmp_path.iterdir()) == []  # nothing persisted without consent


def test_consent_gate_enables_persistence(store: ProfileStore, tmp_path: Path):
    store.get_or_create("victor")
    store.set_consent("victor", store_local=True)
    store.set_field("victor", "home_city", "Bangkok", source="user")
    files = list(tmp_path.iterdir())
    assert len(files) == 1
    loaded = Profile.model_validate_json(files[0].read_text(encoding="utf-8"))
    assert loaded.fields["home_city"].value == "Bangkok"
    assert loaded.consent.store_local is True


def test_consent_withdrawal_stops_persistence(store: ProfileStore, tmp_path: Path):
    store.get_or_create("victor")
    store.set_consent("victor", store_local=True)
    store.set_consent("victor", store_local=False)
    store.set_field("victor", "diet", "vegetarian", source="user")
    assert list(tmp_path.iterdir()) == []


def test_profile_file_permissions_are_owner_only(store: ProfileStore, tmp_path: Path):
    store.get_or_create("victor")
    store.set_consent("victor", store_local=True)
    store.set_field("victor", "home_city", "Bangkok", source="user")
    mode = stat.S_IMODE(os.stat(tmp_path / "victor.json").st_mode)
    assert mode == 0o600


# --- source tagging ----------------------------------------------------------

def test_field_source_tagging(store: ProfileStore):
    store.get_or_create("victor")
    store.set_field("victor", "home_city", "Bangkok", source="ai_inferred")
    store.set_field("victor", "diet", "vegetarian", source="user")
    profile = store.get_or_create("victor")
    assert profile.fields["home_city"].source == "ai_inferred"
    assert profile.fields["diet"].source == "user"
    assert profile.fields["diet"].updated_at  # stamped


def test_invalid_source_rejected(store: ProfileStore):
    store.get_or_create("victor")
    with pytest.raises(ValueError):
        store.set_field("victor", "diet", "keto", source="system")


# --- allowlist & forbidden fields enforcement ---------------------------------

def test_safe_profile_fields_accepted(store: ProfileStore):
    store.get_or_create("victor")
    for field in SAFE_PROFILE_FIELDS:
        store.set_field("victor", field, "test_val", source="user")
        assert store.get_field("victor", field).value == "test_val"


def test_forbidden_fields_rejected_by_store(store: ProfileStore):
    store.get_or_create("victor")
    for forbidden in FORBIDDEN_PROFILE_FIELDS:
        with pytest.raises(ValueError) as exc:
            store.set_field("victor", forbidden, "SENTINEL_VAL", source="user")
        assert "not stored by this demo" in str(exc.value)


def test_unknown_fields_rejected_by_store(store: ProfileStore):
    store.get_or_create("victor")
    for unknown in ("shoe_size", "frequent_flyer_number", "random_prop"):
        with pytest.raises(ValueError) as exc:
            store.set_field("victor", unknown, "val", source="user")
        assert "not a recognized safe profile field" in str(exc.value)


# --- delete semantics --------------------------------------------------------

def test_delete_clears_field_not_file(store: ProfileStore, tmp_path: Path):
    store.get_or_create("victor")
    store.set_consent("victor", store_local=True)
    store.set_field("victor", "home_city", "Bangkok", source="user")
    store.delete_field("victor", "home_city")
    assert "home_city" not in store.get_or_create("victor").fields
    assert (tmp_path / "victor.json").exists()  # file survives deletion


def test_delete_nonexistent_safe_field_is_noop(store: ProfileStore):
    store.get_or_create("victor")
    store.delete_field("victor", "diet")  # safe field not present -> noop


def test_delete_forbidden_or_unknown_field_raises(store: ProfileStore):
    store.get_or_create("victor")
    with pytest.raises(ValueError):
        store.delete_field("victor", "passport_no")
    with pytest.raises(ValueError):
        store.delete_field("victor", "unknown_field")


# --- identity & display (safe fields only) ------------------------------------

def test_set_identity_safe_fields(store: ProfileStore, tmp_path: Path):
    store.get_or_create("victor")
    store.set_consent("victor", store_local=True)
    store.set_identity("victor", passport_country="MM", home_city="Bangkok")
    profile = store.get_or_create("victor")
    assert profile.identity.passport_country == "MM"
    assert profile.identity.home_city == "Bangkok"
    raw = (tmp_path / "victor.json").read_text(encoding="utf-8")
    assert "MM" in raw
    assert "Bangkok" in raw
    assert "passport_no" not in raw


def test_display_export_safe_only(store: ProfileStore):
    store.get_or_create("victor")
    store.set_identity("victor", passport_country="MM", home_city="Bangkok")
    store.set_field("victor", "cabin", "economy", source="user")
    exported = store.display("victor")
    assert exported["identity"]["passport_country"] == "MM"
    assert exported["identity"]["home_city"] == "Bangkok"
    assert "passport_no" not in exported["identity"]
    assert "passport_no_masked" not in exported["identity"]
    assert "expiry" not in exported["identity"]


# --- old-profile migration ----------------------------------------------------

def test_old_profile_migration_strips_legacy_fields(tmp_path: Path):
    """Old stored profiles on disk containing legacy fields are cleaned on load."""
    legacy_json = {
        "user_id": "legacy_user",
        "identity": {
            "passport_country": "MM",
            "home_city": "Bangkok",
            "passport_no_masked": "MD*****67",
            "expiry": "2030-01-01"
        },
        "prefs": {
            "cabin": "economy",
            "airlines_like": ["TG"]
        },
        "fields": {
            "home_city": {"value": "Bangkok", "source": "user", "updated_at": "2026-08-26T00:00:00Z"},
            "passport_no": {"value": "MD*****67", "source": "user", "updated_at": "2026-08-26T00:00:00Z"},
            "unknown_extra": {"value": "bad", "source": "user", "updated_at": "2026-08-26T00:00:00Z"}
        },
        "consent": {"store_local": True}
    }
    file_path = tmp_path / "legacy_user.json"
    file_path.write_text(json.dumps(legacy_json), encoding="utf-8")

    store = ProfileStore(root=tmp_path)
    loaded = store.get_or_create("legacy_user")

    # Safe fields survive
    assert loaded.identity.passport_country == "MM"
    assert loaded.identity.home_city == "Bangkok"
    assert "home_city" in loaded.fields
    assert loaded.prefs.cabin == "economy"

    # Legacy / forbidden / unknown fields are stripped
    assert "passport_no" not in loaded.fields
    assert "unknown_extra" not in loaded.fields
    assert not hasattr(loaded.identity, "passport_no_masked")
    assert not hasattr(loaded.identity, "expiry")

    # Persisted copy is cleaned
    disk_blob = file_path.read_text(encoding="utf-8")
    assert "passport_no" not in disk_blob
    assert "unknown_extra" not in disk_blob


# --- adversarial: schema contracts ---------------------------------------------

def test_web_intel_snippet_over_280_rejected():
    with pytest.raises(ValidationError):
        WebIntelCitation(
            url="https://example.org",
            title="t",
            retrieved_date="2026-08-26",
            snippet_max280="x" * 281,
        )


def test_web_intel_snippet_exactly_280_accepted():
    citation = WebIntelCitation(
        url="https://example.org",
        title="t",
        retrieved_date="2026-08-26",
        snippet_max280="x" * 280,
    )
    assert len(citation.snippet_max280) == 280


def test_flight_option_provenance_cannot_be_forged():
    base = dict(
        id="o1",
        carrier="TG",
        flight_no="TG403",
        dep={"airport": "BKK", "time": "2026-09-28T08:00"},
        arr={"airport": "SIN", "time": "2026-09-28T11:20"},
        duration_min=140,
        price={"amount": 120.0, "currency": "USD"},
    )
    assert FlightOption(**base).sandbox_provenance is True
    with pytest.raises(ValidationError):
        FlightOption(sandbox_provenance=False, **base)


# --- adversarial: duplicate/overwrite writes -------------------------------------

def test_duplicate_field_write_overwrites_not_duplicates(store: ProfileStore):
    store.get_or_create("victor")
    store.set_field("victor", "diet", "vegetarian", source="ai_inferred")
    store.set_field("victor", "diet", "halal", source="user")
    profile = store.get_or_create("victor")
    assert list(profile.fields).count("diet") == 1
    assert profile.fields["diet"].value == "halal"
    assert profile.fields["diet"].source == "user"


def test_persisted_profile_round_trips_after_overwrite(store: ProfileStore, tmp_path: Path):
    store.get_or_create("victor")
    store.set_consent("victor", store_local=True)
    store.set_field("victor", "diet", "vegetarian", source="ai_inferred")
    store.set_field("victor", "diet", "halal", source="user")
    reloaded = ProfileStore(root=tmp_path).get_or_create("victor")
    assert reloaded.fields["diet"].value == "halal"
    assert reloaded.fields["diet"].source == "user"


# --- user_id security ---------------------------------------------------------

def test_user_id_path_traversal_alias_rejected(store: ProfileStore):
    """'vic/tor' must not alias onto victor.json (cross-user overwrite)."""
    with pytest.raises(ValueError):
        store.get_or_create("vic/tor")
    with pytest.raises(ValueError):
        store.get_or_create("../etc")
    with pytest.raises(ValueError):
        store.get_or_create("")


def test_safe_user_id_charset_accepted(store: ProfileStore):
    profile = store.get_or_create("vic-tor_2")
    assert profile.user_id == "vic-tor_2"
