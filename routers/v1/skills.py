"""Skills manifest router (§6, F12).

GET /api/skills — listing built from the boot registry: every *.SKILL.md
frontmatter is parsed by services.skills.load_skill_registry(); the
when_to_use text comes from the paired SkillBase subclass (progressive
disclosure: manifest summary + class-level usage). Adding/removing a skill
pair changes this listing.
"""

import importlib
from typing import Dict, List

from fastapi import APIRouter

from services.skills import load_skill_registry
from services.skills.base import SkillBase

router = APIRouter(prefix="/api/skills", tags=["Skills"])


def _when_to_use(entry: Dict) -> str:
    """Prefer the SkillBase subclass's when_to_use; fall back to the
    manifest description (never an empty listing)."""
    try:
        module = importlib.import_module(entry["module_path"])
    except Exception:  # noqa: BLE001 — a broken module degrades, never 500s
        return entry["description"]
    for value in vars(module).values():
        if (isinstance(value, type) and issubclass(value, SkillBase)
                and getattr(value, "name", "") == entry["name"]):
            when = getattr(value, "when_to_use", "") or ""
            if when:
                return when
    return entry["description"]


@router.get("")
async def list_skills():
    """Live manifest listing (name, when_to_use) from the boot registry."""
    registry = load_skill_registry()
    skills: List[Dict[str, str]] = [
        {"name": entry["name"],
         "when_to_use": _when_to_use(entry),
         "description": entry["description"]}
        for entry in registry
    ]
    return {"skills": skills, "count": len(skills)}
