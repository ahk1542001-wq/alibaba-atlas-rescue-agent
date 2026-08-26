"""profile_capture skill — §4 S2/S3 (G2 behavior).

Silent-save is IMPOSSIBLE: a value captured from conversation is held as a
pending ConfirmationChip and persisted ONLY after explicit confirmation.
Unconfirmed or rejected captures raise SkillError (the unit suite proves
the exception path); nothing ever reaches the store without confirmed=True.
"""

from typing import Any, Dict, Optional

from models.schemas import ConfirmationChip
from services.profile_store import ProfileStore
from services.skills.base import SkillBase, SkillError


class ProfileCaptureSkill(SkillBase):
    name = "profile_capture"
    when_to_use = (
        "when clarification reveals a personal fact; proposes a "
        "ConfirmationChip and saves only after the user confirms"
    )
    capabilities = frozenset({"profile_write"})

    def __init__(self, profile_store: Optional[ProfileStore] = None) -> None:
        self._store = profile_store or ProfileStore()

    async def run(self, payload: Dict[str, Any],
                  context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        user_id = str(payload.get("user_id") or "")
        field_name = str(payload.get("field") or "")
        value = payload.get("value")
        source = payload.get("source") or "ai_inferred"
        confirmed = payload.get("confirmed")

        if not user_id or not field_name:
            raise SkillError("invalid_capture",
                             "profile capture requires user_id and field",
                             recoverable=True)

        chip = ConfirmationChip(
            field=field_name,
            proposed_value=value,
            message=f"Save {field_name} = {value!r} to your profile?",
            state="confirmed" if confirmed is True else "pending",
        )

        if confirmed is not True:
            # silent-save impossible: no confirmation -> no write, ever
            code = ("confirmation_rejected" if confirmed is False
                    else "confirmation_required")
            raise SkillError(
                code,
                f"profile field '{field_name}' not saved — awaiting explicit "
                "ConfirmationChip confirmation",
                recoverable=True)

        self._store.set_field(user_id, field_name, value, source=source)
        return {
            "saved": True,
            "field": field_name,
            "source": source,
            "chip": chip.model_dump(mode="json"),
        }
