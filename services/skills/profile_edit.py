"""profile_edit skill — §4 S3 (G2 behavior).

User edits via UI/chat. IN{field,value,source=user} OUT{Profile}.
Ver: allowlist/redaction rules hold; deletion clears only the selected field.
This logic is primarily governed in routers.v1.profile, but exposed as a skill
for LLM awareness.
"""

from typing import Any, Dict, Optional

from services.profile_store import ProfileStore
from services.skills.base import SkillBase, SkillError

class ProfileEditSkill(SkillBase):
    name = "profile_edit"
    when_to_use = "when user edits profile facts via UI or chat"
    capabilities = frozenset({"profile_write"})

    def __init__(self, profile_store: Optional[ProfileStore] = None) -> None:
        self._store = profile_store or ProfileStore()

    async def run(self, payload: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        user_id = str(payload.get("user_id") or "")
        field = payload.get("field")
        value = payload.get("value")
        
        if not user_id or not field:
            raise SkillError("invalid_edit", "user_id and field required", recoverable=True)
            
        profile = self._store.load_profile(user_id)
        if profile is None:
             raise SkillError("not_found", "Profile not found", recoverable=True)
             
        try:
             self._store.update_field(user_id, field, value)
        except ValueError as e:
             raise SkillError("invalid_edit", str(e), recoverable=True)
             
        return {"saved": True, "field": field, "source": "user"}
