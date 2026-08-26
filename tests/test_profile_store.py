"""Contract tests for the §5 passport-masking util and the profile store.

Profile files live under a tmp dir per test (never the real data/profiles/).
Covers: mask_passport vectors, source tagging, delete-clears-field-not-file,
consent gating, atomic write permissions, and masked passport display.
"""

import os
import stat
from pathlib import Path

import pytest
from pydantic import ValidationError

from models.schemas import FlightOption, Profile, WebIntelCitation, mask_passport
from services.profile_store import ProfileStore


# --- mask_passport vectors -------------------------------------------------

def test_mask_passport_standard_vector():
    assert mask_passport("MD1234567") == "MD*****67"


def test_mask_passport_keeps_first2_last2():
    assert mask_passport("AB1234") == "AB**34"
    assert mask_passport("ABCDE") == "AB*DE"
    assert mask_passport("N12345678901") == "N1********01"


def test_mask_passport_short_input_graceful():
    assert mask_passport("X1") == "X1"
    assert mask_passport("AB12") == "AB12"
    assert mask_passport("") == ""


# --- store basics ------------------------------------------------------------

@pytest.fixture()
def store(tmp_path: Path) -> ProfileStore:
    return ProfileStore(root=tmp_path)


def test_new_profile_starts_empty(store: ProfileStore):
    profile = store.get_or_create("victor")
    assert profile.user_id == "victor"
    assert profile.identity.passport_country is None
    assert profile.identity.passport_no_masked is None
    assert profile.identity.home_city is None
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


# --- delete semantics --------------------------------------------------------

def test_delete_clears_field_not_file(store: ProfileStore, tmp_path: Path):
    store.get_or_create("victor")
    store.set_consent("victor", store_local=True)
    store.set_field("victor", "home_city", "Bangkok", source="user")
    store.delete_field("victor", "home_city")
    assert "home_city" not in store.get_or_create("victor").fields
    assert (tmp_path / "victor.json").exists()  # file survives deletion


def test_delete_unknown_field_is_noop(store: ProfileStore):
    store.get_or_create("victor")
    store.delete_field("victor", "never_existed")  # must not raise


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


# --- masking in display/export paths ------------------------------------------

def test_identity_passport_always_masked(store: ProfileStore, tmp_path: Path):
    store.get_or_create("victor")
    store.set_consent("victor", store_local=True)
    store.set_identity("victor", passport_country="MM", passport_no="MD1234567")
    profile = store.get_or_create("victor")
    assert profile.identity.passport_no_masked == "MD*****67"
    raw = (tmp_path / "victor.json").read_text(encoding="utf-8")
    assert "MD1234567" not in raw  # raw passport never persisted


def test_display_export_masks_passport(store: ProfileStore):
    store.get_or_create("victor")
    store.set_identity("victor", passport_country="MM", passport_no="MD1234567")
    exported = store.display("victor")
    assert exported["identity"]["passport_no_masked"] == "MD*****67"
    assert "MD1234567" not in str(exported)
