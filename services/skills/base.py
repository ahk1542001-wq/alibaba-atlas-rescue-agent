"""SkillBase — runtime contract for every TravelCare v2 skill (§4.0).

A skill pairs services/skills/<name>.py (this class) with
services/skills/<name>.SKILL.md (manifest frontmatter parsed at boot).
Real behavior lands at G2; contract-phase run() returns a minimal
structured result and never raises NotImplementedError at import time.
"""

from typing import Any, ClassVar, Dict, FrozenSet, Optional, Type

from pydantic import BaseModel

# Closed capability vocabulary (§4.0 rule 4) — executor enforces these.
CAPABILITY_VOCABULARY: FrozenSet[str] = frozenset(
    {
        "network_read",
        "atlas_call",
        "llm_call",
        "telegram_send",
        "profile_read",
        "profile_write",
        "approval_required",
    }
)


class SkillError(Exception):
    """Structured skill failure the executor records and surfaces.

    recoverable=True means the trip can continue after the user/agent fixes
    the underlying condition (e.g. stale visa data, missing confirmation).
    """

    def __init__(self, code: str, message: str, recoverable: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.recoverable = recoverable


class SkillBase:
    """Base class every skill extends. Subclasses set class-level metadata."""

    name: ClassVar[str] = ""
    when_to_use: ClassVar[str] = ""
    input_model: ClassVar[Optional[Type[BaseModel]]] = None
    output_model: ClassVar[Optional[Type[BaseModel]]] = None
    capabilities: ClassVar[FrozenSet[str]] = frozenset()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        unknown = cls.capabilities - CAPABILITY_VOCABULARY
        if unknown:
            raise ValueError(
                f"skill {cls.__name__} declares unknown capabilities: {sorted(unknown)}"
            )

    async def run(self, payload: Dict[str, Any],
                  context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Contract-phase stub: minimal structured result (behavior at G2)."""
        return {
            "skill": self.name,
            "status": "contract_stub",
            "received": sorted(payload.keys()) if payload else [],
        }
