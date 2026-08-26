"""Profile store (contract phase, G1) — JSON-backed per-user profiles.

Contract (MASTER_BUILD_PACKAGE.md §5/F5):
- storage: data/profiles/{user_id}.json (root injectable for tests)
- atomic write: tempfile in the same dir + os.replace, then os.chmod 0o600
- field-level get/set/delete with source tags (user | ai_inferred)
- delete clears the field; it NEVER deletes the file
- consent{store_local} gates persistence: nothing hits disk without consent
- passport numbers are masked in every display/export/persist path
- new-user profiles start EMPTY — no default identity values, and nothing
  auto-loads the opt-in victor demo fixture
"""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from models.schemas import Profile, ProfileFieldValue, mask_passport

DEFAULT_ROOT = Path(__file__).resolve().parent.parent / "data" / "profiles"


class ProfileStore:
    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root) if root is not None else DEFAULT_ROOT
        self._memory: Dict[str, Profile] = {}

    # -- paths ---------------------------------------------------------------

    def _path(self, user_id: str) -> Path:
        safe = "".join(c for c in user_id if c.isalnum() or c in "-_")
        if not safe:
            raise ValueError("user_id must contain alphanumeric characters")
        return self.root / f"{safe}.json"

    # -- lifecycle -------------------------------------------------------------

    def get_or_create(self, user_id: str) -> Profile:
        """Load from disk if consented+persisted, else from memory, else empty."""
        if user_id in self._memory:
            return self._memory[user_id]
        path = self._path(user_id)
        if path.exists():
            profile = Profile.model_validate_json(path.read_text(encoding="utf-8"))
        else:
            profile = Profile(user_id=user_id)  # starts empty, no consent
        self._memory[user_id] = profile
        return profile

    def _persist(self, user_id: str) -> None:
        """Atomic owner-only write; silently skipped without consent."""
        profile = self._memory.get(user_id)
        if profile is None or not profile.consent.store_local:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        payload = profile.model_dump_json(indent=2)
        fd, tmp_name = tempfile.mkstemp(dir=self.root, prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.chmod(tmp_name, 0o600)
            os.replace(tmp_name, self._path(user_id))
        except BaseException:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
            raise

    # -- consent ---------------------------------------------------------------

    def set_consent(self, user_id: str, store_local: bool) -> Profile:
        profile = self.get_or_create(user_id)
        profile.consent.store_local = store_local
        if store_local:
            self._persist(user_id)
        else:
            # withdrawal is effective: the persisted copy is removed; the
            # in-memory profile survives so the session keeps working
            path = self._path(user_id)
            if path.exists():
                path.unlink()
        return profile

    # -- fields ------------------------------------------------------------------

    def set_field(self, user_id: str, name: str, value: Any, source: str) -> Profile:
        profile = self.get_or_create(user_id)
        # ProfileFieldValue validates source against the closed set; raises ValueError
        field = ProfileFieldValue(
            value=value,
            source=source,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        profile.fields[name] = field
        self._persist(user_id)
        return profile

    def get_field(self, user_id: str, name: str) -> Optional[ProfileFieldValue]:
        return self.get_or_create(user_id).fields.get(name)

    def delete_field(self, user_id: str, name: str) -> Profile:
        """Clears the field; the profile file is never deleted."""
        profile = self.get_or_create(user_id)
        profile.fields.pop(name, None)
        self._persist(user_id)
        return profile

    # -- identity (masked at the boundary) -----------------------------------------

    def set_identity(
        self,
        user_id: str,
        passport_country: Optional[str] = None,
        passport_no: Optional[str] = None,
        expiry: Optional[str] = None,
        home_city: Optional[str] = None,
    ) -> Profile:
        profile = self.get_or_create(user_id)
        if passport_country is not None:
            profile.identity.passport_country = passport_country
        if passport_no is not None:
            # raw number is masked immediately; it is never stored or exported raw
            profile.identity.passport_no_masked = mask_passport(passport_no)
        if expiry is not None:
            profile.identity.expiry = expiry
        if home_city is not None:
            profile.identity.home_city = home_city
        self._persist(user_id)
        return profile

    # -- display/export (always masked) -----------------------------------------------

    def display(self, user_id: str) -> Dict[str, Any]:
        """Export-safe view: model only ever holds the masked passport."""
        return json.loads(self.get_or_create(user_id).model_dump_json())
