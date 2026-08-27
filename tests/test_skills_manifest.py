"""Manifest-loader tests for the §4.0 skill authoring standard.

The registry is built at boot from *.SKILL.md frontmatter (pyyaml). These
tests copy the skills dir into tmp before mutating anything — the real
services/skills/ tree is never touched. Covers F12: adding/removing a
SKILL.md file must change the listing.
"""

import shutil
from pathlib import Path

import pytest

from services.skills import (
    CAPABILITY_VOCABULARY,
    SKILLS_DIR,
    SkillManifestError,
    load_skill_registry,
)

EXPECTED_SKILLS = {
    "goal_intake",
    "clarify_loop",
    "profile_capture",
    "flight_search",
    "flight_book",
    "visa_check",
    "web_intel",
    "itinerary",
    "rights_check",
    "guardian_push",
    "disruption_monitor",
    "location_resolve",
    "recovery_plan",
}


@pytest.fixture()
def skills_copy(tmp_path: Path) -> Path:
    dest = tmp_path / "skills"
    shutil.copytree(SKILLS_DIR, dest)
    return dest


def test_registry_loads_exactly_thirteen_skills():
    registry = load_skill_registry()
    assert len(registry) == 13
    assert {entry["name"] for entry in registry} == EXPECTED_SKILLS


def test_registry_entries_carry_manifest_fields():
    for entry in load_skill_registry():
        assert entry["description"].strip(), entry["name"]
        assert entry["module_path"] == f"services.skills.{entry['name']}"
        assert isinstance(entry["allowed_tools"], list)


def test_all_capability_flags_in_closed_vocabulary():
    for entry in load_skill_registry():
        unknown = set(entry["allowed_tools"]) - CAPABILITY_VOCABULARY
        assert not unknown, f"{entry['name']} declares unknown flags: {unknown}"


def test_closed_vocabulary_is_exactly_spec_set():
    assert CAPABILITY_VOCABULARY == {
        "network_read",
        "atlas_call",
        "llm_call",
        "telegram_send",
        "profile_read",
        "profile_write",
        "approval_required",
    }


def test_adding_skill_file_changes_listing(skills_copy: Path):
    # §4.0 rule 1 pairing: SKILL.md registers only with its paired <stem>.py
    (skills_copy / "hotel_finder.py").write_text(
        "from services.skills.base import SkillBase\n\n"
        "class HotelFinderSkill(SkillBase):\n"
        "    name = \"hotel_finder\"\n"
        "    when_to_use = \"when lodging is requested\"\n"
        "    capabilities = frozenset({\"network_read\"})\n",
        encoding="utf-8",
    )
    extra = skills_copy / "hotel_finder.SKILL.md"
    extra.write_text(
        "---\n"
        "name: hotel_finder\n"
        "description: Finds hotels near the venue. Use when lodging is requested.\n"
        "allowed-tools: network_read\n"
        "---\n"
        "# Procedure\n1. search\n"
        "# Input-Output\nrefs §5 models\n"
        "# Verification\nmapped to §8\n",
        encoding="utf-8",
    )
    registry = load_skill_registry(skills_copy)
    assert len(registry) == 14
    assert "hotel_finder" in {entry["name"] for entry in registry}


def test_removing_skill_file_changes_listing(skills_copy: Path):
    (skills_copy / "web_intel.SKILL.md").unlink()
    registry = load_skill_registry(skills_copy)
    assert len(registry) == 12
    assert "web_intel" not in {entry["name"] for entry in registry}


def test_unknown_capability_flag_rejected(skills_copy: Path):
    rogue = skills_copy / "rogue.SKILL.md"
    (skills_copy / "rogue.py").write_text("# paired module\n", encoding="utf-8")
    rogue.write_text(
        "---\n"
        "name: rogue\n"
        "description: Rogue skill. Use when testing rejection.\n"
        "allowed-tools: network_read, rm_rf_everything\n"
        "---\n"
        "# Procedure\n1. n/a\n",
        encoding="utf-8",
    )
    with pytest.raises(SkillManifestError):
        load_skill_registry(skills_copy)


def test_missing_required_frontmatter_rejected(skills_copy: Path):
    broken = skills_copy / "broken.SKILL.md"
    (skills_copy / "broken.py").write_text("# paired module\n", encoding="utf-8")
    broken.write_text(
        "---\nname: broken\n---\n# Procedure\n1. no description\n",
        encoding="utf-8",
    )
    with pytest.raises(SkillManifestError):
        load_skill_registry(skills_copy)


def test_unclosed_frontmatter_rejected(skills_copy: Path):
    broken = skills_copy / "unclosed.SKILL.md"
    (skills_copy / "unclosed.py").write_text("# paired module\n", encoding="utf-8")
    broken.write_text(
        "---\nname: unclosed\ndescription: never closed. Use when testing.\n",
        encoding="utf-8",
    )
    with pytest.raises(SkillManifestError):
        load_skill_registry(skills_copy)


def test_empty_allowed_tools_loads_cleanly(skills_copy: Path):
    # rights_check declares no capabilities; empty flag lists must load
    entry = next(
        e for e in load_skill_registry(skills_copy) if e["name"] == "rights_check"
    )
    assert entry["allowed_tools"] == []


def test_reload_reflects_filesystem_changes(skills_copy: Path):
    """Registry is rebuilt per call — no stale cache across add/remove."""
    assert len(load_skill_registry(skills_copy)) == 13
    (skills_copy / "web_intel.SKILL.md").unlink()
    assert len(load_skill_registry(skills_copy)) == 12
    (skills_copy / "web_intel.SKILL.md").write_text(
        "---\n"
        "name: web_intel\n"
        "description: Fetches fresh web evidence. Use when freshness needed.\n"
        "allowed-tools: network_read\n"
        "---\n"
        "# Procedure\n1. fetch\n",
        encoding="utf-8",
    )
    assert len(load_skill_registry(skills_copy)) == 13


def test_duplicate_skill_name_rejected(skills_copy: Path):
    """DA-review fix: duplicate names raise instead of relying on caller dedupe."""
    dup = skills_copy / "visa_check_copy.SKILL.md"
    (skills_copy / "visa_check_copy.py").write_text(
        "# paired module\n", encoding="utf-8")
    dup.write_text(
        "---\n"
        "name: visa_check\n"
        "description: Duplicate entry. Use when testing duplicates.\n"
        "allowed-tools: network_read\n"
        "---\n"
        "# Procedure\n1. n/a\n",
        encoding="utf-8",
    )
    with pytest.raises(SkillManifestError):
        load_skill_registry(skills_copy)


# --- DA-review regressions: §4.0 rule 1 pairing + drift ------------------------

def test_orphan_skill_md_without_paired_module_rejected(skills_copy: Path):
    orphan = skills_copy / "hotel_finder.SKILL.md"
    orphan.write_text(
        "---\n"
        "name: hotel_finder\n"
        "description: Orphan manifest. Use when testing pairing.\n"
        "allowed-tools: network_read\n"
        "---\n"
        "# Procedure\n1. n/a\n",
        encoding="utf-8",
    )
    with pytest.raises(SkillManifestError):
        load_skill_registry(skills_copy)


def test_name_mismatch_with_file_stem_rejected(skills_copy: Path):
    (skills_copy / "mismatch.py").write_text("# paired module\n", encoding="utf-8")
    (skills_copy / "mismatch.SKILL.md").write_text(
        "---\n"
        "name: totally_different\n"
        "description: Name differs from stem. Use when testing pairing.\n"
        "allowed-tools: network_read\n"
        "---\n"
        "# Procedure\n1. n/a\n",
        encoding="utf-8",
    )
    with pytest.raises(SkillManifestError):
        load_skill_registry(skills_copy)


def test_unsafe_name_charset_rejected(skills_copy: Path):
    (skills_copy / "Bad-Name.SKILL.md").write_text(
        "---\n"
        "name: Bad-Name\n"
        "description: Unsafe charset. Use when testing name validation.\n"
        "allowed-tools: network_read\n"
        "---\n"
        "# Procedure\n1. n/a\n",
        encoding="utf-8",
    )
    (skills_copy / "Bad-Name.py").write_text("# paired module\n", encoding="utf-8")
    with pytest.raises(SkillManifestError):
        load_skill_registry(skills_copy)


def test_yaml_list_form_allowed_tools_accepted(skills_copy: Path):
    (skills_copy / "listy.py").write_text("# paired module\n", encoding="utf-8")
    (skills_copy / "listy.SKILL.md").write_text(
        "---\n"
        "name: listy\n"
        "description: List-form flags. Use when testing yaml list parsing.\n"
        "allowed-tools:\n"
        "  - network_read\n"
        "---\n"
        "# Procedure\n1. n/a\n",
        encoding="utf-8",
    )
    entry = next(e for e in load_skill_registry(skills_copy)
                 if e["name"] == "listy")
    assert entry["allowed_tools"] == ["network_read"]


def test_manifest_flags_match_class_capabilities():
    """DA-review fix: no drift between SKILL.md allowed-tools and the class."""
    import importlib

    from services.skills.base import SkillBase

    for entry in load_skill_registry():
        module = importlib.import_module(entry["module_path"])
        classes = [
            obj for obj in vars(module).values()
            if isinstance(obj, type) and issubclass(obj, SkillBase)
            and obj is not SkillBase and getattr(obj, "name", "") == entry["name"]
        ]
        assert classes, f"{entry['name']}: no SkillBase subclass in module"
        assert set(entry["allowed_tools"]) == set(classes[0].capabilities), (
            f"{entry['name']}: manifest {sorted(entry['allowed_tools'])} != "
            f"class {sorted(classes[0].capabilities)}"
        )
