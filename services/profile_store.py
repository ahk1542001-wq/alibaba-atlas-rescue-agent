"""Profile store (contract phase, G1) — JSON-backed per-user profiles.

Contract (canonical MASTER_BUILD_PACKAGE.md §5/F5/F17, R1 reconciliation):
- storage: data/profiles/{user_id}.json (root injectable for tests)
- atomic write: tempfile in the same dir + os.replace, then os.chmod 0o600
- field-level get/set/delete with source tags (user | ai_inferred)
- delete clears the field; it NEVER deletes the file
- consent{store_local} gates persistence: nothing hits disk without consent
- NO passport number is ever requested, accepted, masked, stored, or
  exported — passport-number-shaped fields are REJECTED at the boundary
- new-user profiles start EMPTY — no default identity values, and nothing
  auto-loads any demo fixture
"""

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from models.schemas import (FORBIDDEN_PROFILE_FIELDS, SAFE_PROFILE_FIELDS,
                            Profile, ProfileFieldValue)

DEFAULT_ROOT = Path(__file__).resolve().parent.parent / "data" / "profiles"

# DA-review fix: reject user_ids that could alias onto another user's file
_USER_ID_RE = re.compile(r"[A-Za-z0-9_-]+")


class ProfileStore:
    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root) if root is not None else DEFAULT_ROOT
        self._memory: Dict[str, Profile] = {}

    # -- paths ---------------------------------------------------------------

    def _path(self, user_id: str) -> Path:
        if not re.fullmatch(_USER_ID_RE, user_id):
            raise ValueError(
                "user_id must match [A-Za-z0-9_-]+ — refusing potentially "
                "aliasing/traversing identifier"
            )
        return self.root / f"{user_id}.json"

    # -- lifecycle -------------------------------------------------------------

    def get_or_create(self, user_id: str) -> Profile:
        """Load from disk if consented+persisted, else from memory, else empty."""
        if user_id in self._memory:
            return self._memory[user_id]
        path = self._path(user_id)
        if path.exists():
            profile = Profile.model_validate_json(path.read_text(encoding="utf-8"))
            # Old profile migration: strip any non-allowlisted / forbidden fields
            cleaned_fields = {
                k: v for k, v in profile.fields.items()
                if k in SAFE_PROFILE_FIELDS and k not in FORBIDDEN_PROFILE_FIELDS
            }
            if len(cleaned_fields) != len(profile.fields):
                profile.fields = cleaned_fields
                self._memory[user_id] = profile
                if profile.consent.store_local:
                    self._persist(user_id)
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
        # R1/P0 canonical contract: passport-number-shaped (and other
        # identity-document/payment) fields are REJECTED at the boundary —
        # never requested, accepted, masked, or stored.
        if name in FORBIDDEN_PROFILE_FIELDS:
            raise ValueError(
                f"field '{name}' is not stored by this demo: passport "
                "numbers, document ids, legal identity and payment data "
                "are never collected")
        if name not in SAFE_PROFILE_FIELDS:
            raise ValueError(f"field '{name}' is not a recognized safe profile field")
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
        if name in FORBIDDEN_PROFILE_FIELDS:
            raise ValueError(
                f"field '{name}' is not stored by this demo: passport "
                "numbers, document ids, legal identity and payment data "
                "are never collected")
        if name not in SAFE_PROFILE_FIELDS:
            raise ValueError(f"field '{name}' is not a recognized safe profile field")
        profile = self.get_or_create(user_id)
        profile.fields.pop(name, None)
        self._persist(user_id)
        return profile

    # -- identity (safe fields only) -----------------------------------------

    def set_identity(
        self,
        user_id: str,
        passport_country: Optional[str] = None,
        home_city: Optional[str] = None,
    ) -> Profile:
        profile = self.get_or_create(user_id)
        if passport_country is not None:
            profile.identity.passport_country = passport_country
        if home_city is not None:
            profile.identity.home_city = home_city
        self._persist(user_id)
        return profile

    # -- display/export (safe fields only) ------------------------------------

    def display(self, user_id: str) -> Dict[str, Any]:
        """Export-safe view: the model holds no passport-number/expiry/
        payment/legal-identity fields to begin with (canonical §5)."""
        return json.loads(self.get_or_create(user_id).model_dump_json())
