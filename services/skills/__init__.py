"""Skills package — boot-time manifest loader (§4.0 skill authoring standard).

Single source of truth: every *.SKILL.md frontmatter is parsed with pyyaml
into an in-memory registry at boot. No hand-maintained skills.yaml
(subtract-before-you-add). F12: adding/removing a SKILL.md file changes
the listing.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from services.skills.base import CAPABILITY_VOCABULARY, SkillBase

SKILLS_DIR = Path(__file__).resolve().parent

__all__ = [
    "CAPABILITY_VOCABULARY",
    "SKILLS_DIR",
    "SkillBase",
    "SkillManifestError",
    "load_skill_registry",
]


class SkillManifestError(ValueError):
    """Raised when a *.SKILL.md manifest is malformed or over-privileged."""


def _parse_frontmatter(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillManifestError(f"{path.name}: missing frontmatter opener '---'")
    try:
        closing = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise SkillManifestError(f"{path.name}: missing frontmatter closer '---'")
    try:
        meta = yaml.safe_load("\n".join(lines[1:closing])) or {}
    except yaml.YAMLError as exc:
        raise SkillManifestError(f"{path.name}: invalid yaml frontmatter: {exc}")
    if not isinstance(meta, dict):
        raise SkillManifestError(f"{path.name}: frontmatter must be a mapping")
    return meta


def _allowed_tools(meta: Dict[str, Any], path: Path) -> List[str]:
    """Parse allowed-tools as comma string OR yaml list (AUTO- decision)."""
    raw = meta.get("allowed-tools")
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return [str(t).strip() for t in raw if str(t).strip()]
    return [t.strip() for t in str(raw).split(",") if t.strip()]


def load_skill_registry(
    skills_dir: Optional[Path] = None,
    *,
    include_internal: bool = False,
) -> List[Dict[str, Any]]:
    """Parse every *.SKILL.md under skills_dir into registry entries.

    Entry shape: {name, description, allowed_tools, module_path, path}.
    Manifests marked ``visibility: internal`` are validated on every load but
    omitted from the public product registry unless ``include_internal`` is
    true. This keeps orchestration helpers governed without advertising them
    as one of the canonical S1-S13 product skills.
    Raises SkillManifestError on missing required keys, unknown capability
    flags (closed vocabulary, §4.0 rule 4), unpaired manifests, name/stem
    mismatch, unsafe name charset, or duplicate names (§4.0 rule 1).
    """
    base = Path(skills_dir) if skills_dir is not None else SKILLS_DIR
    registry: List[Dict[str, Any]] = []
    seen: set = set()
    for path in sorted(base.glob("*.SKILL.md")):
        meta = _parse_frontmatter(path)
        name = str(meta.get("name") or "").strip()
        description = str(meta.get("description") or "").strip()
        if not name:
            raise SkillManifestError(f"{path.name}: 'name' is required")
        if not description:
            raise SkillManifestError(f"{path.name}: 'description' is required")
        stem = path.name[: -len(".SKILL.md")]
        if name != stem:
            raise SkillManifestError(
                f"{path.name}: name '{name}' must equal file stem '{stem}' (§4.0 rule 1)"
            )
        if not re.fullmatch(r"[a-z0-9_]+", name):
            raise SkillManifestError(
                f"{path.name}: unsafe skill name '{name}' "
                "(allowed charset: a-z 0-9 _)"
            )
        if not (path.parent / f"{stem}.py").exists():
            raise SkillManifestError(
                f"{path.name}: orphan manifest — paired module '{stem}.py' missing "
                "(§4.0 rule 1: both required, neither optional)"
            )
        if name in seen:
            raise SkillManifestError(f"{path.name}: duplicate skill name '{name}'")
        seen.add(name)
        tools = _allowed_tools(meta, path)
        unknown = set(tools) - CAPABILITY_VOCABULARY
        if unknown:
            raise SkillManifestError(
                f"{path.name}: unknown capability flag(s) {sorted(unknown)}; "
                f"closed vocabulary: {sorted(CAPABILITY_VOCABULARY)}"
            )
        visibility = str(meta.get("visibility") or "public").strip().lower()
        if visibility not in {"public", "internal"}:
            raise SkillManifestError(
                f"{path.name}: visibility must be 'public' or 'internal'"
            )
        if visibility == "internal" and not include_internal:
            continue
        registry.append(
            {
                "name": name,
                "description": description,
                "allowed_tools": tools,
                "module_path": f"services.skills.{name}",
                "path": str(path),
            }
        )
    return registry
