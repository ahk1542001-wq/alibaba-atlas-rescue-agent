"""profile_edit skill — §4 S3 (G2 behavior).

User edits via UI/chat. IN{field,value,source=user} OUT{Profile}.
Ver: allowlist/redaction rules hold; deletion clears only the selected field.
The skill uses the same ProfileStore allowlist and consent-gated persistence as
the profile API. A delete request clears only the named field.
"""

from typing import Any, Dict, Optional

from services.profile_store import ProfileStore
from services.skills.base import SkillBase, SkillError

class ProfileEditSkill(SkillBase):
    name = "profile_edit"
    when_to_use = "when user edits profile facts via UI or chat"
    capabilities = frozenset({"profile_read", "profile_write"})

    def __init__(self, profile_store: Optional[ProfileStore] = None) -> None:
        self._store = profile_store or ProfileStore()

    async def run(self, payload: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        user_id = str(payload.get("user_id") or "")
        field = str(payload.get("field") or "")
        value = payload.get("value")
        source = str(payload.get("source") or "user")

        if not user_id or not field:
            raise SkillError("invalid_edit", "user_id and field required", recoverable=True)
        if source != "user":
            raise SkillError(
                "invalid_edit_source",
                "profile edits must have source='user'; inferred values use "
                "profile_capture and explicit confirmation",
                recoverable=True,
            )

        try:
            if payload.get("delete") is True:
                self._store.delete_field(user_id, field)
                operation = "deleted"
            else:
                self._store.set_field(user_id, field, value, source="user")
                operation = "updated"
        except ValueError as e:
            raise SkillError("invalid_edit", str(e), recoverable=True) from e

        return {
            "saved": operation == "updated",
            "deleted": operation == "deleted",
            "operation": operation,
            "field": field,
            "source": "user",
            "profile": self._store.display(user_id),
        }
