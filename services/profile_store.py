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
            raw_text = path.read_text(encoding="utf-8")
            raw_json = json.loads(raw_text)

            def _has_forbidden(obj: Any) -> bool:
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if k in FORBIDDEN_PROFILE_FIELDS:
                            return True
                        if _has_forbidden(v):
                            return True
                elif isinstance(obj, list):
                    return any(_has_forbidden(x) for x in obj)
                return False

            had_forbidden = _has_forbidden(raw_json)

            def _clean_dict(d: dict) -> dict:
                out = {}
                for k, v in d.items():
                    if k in FORBIDDEN_PROFILE_FIELDS:
                        continue
                    if isinstance(v, dict):
                        out[k] = _clean_dict(v)
                    elif isinstance(v, list):
                        out[k] = [_clean_dict(x) if isinstance(x, dict) else x for x in v]
                    else:
                        out[k] = v
                return out

            cleaned_json = _clean_dict(raw_json)
            profile = Profile.model_validate(cleaned_json)
            self._memory[user_id] = profile
            if had_forbidden and profile.consent.store_local:
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
            confirmation="confirmed"
        )
        setattr(profile, name, field)
        profile.fields[name] = field
        if name == "passport_country":
            profile.identity.passport_country = str(value)
        elif name == "home_city":
            profile.identity.home_city = str(value)
        elif name == "cabin":
            profile.prefs.cabin = str(value)
        elif name == "preferred_origin_airport":
            profile.prefs.preferred_origin_airport = str(value)
        elif name == "display_currency":
            profile.prefs.display_currency = str(value)
        elif name == "budget_range":
            profile.prefs.budget_range = str(value)
        elif name == "diet":
            profile.prefs.diet = str(value)
        elif name == "accessibility_notes":
            profile.prefs.accessibility_notes = str(value)
        elif name == "airlines_like":
            profile.prefs.airlines_like = value if isinstance(value, list) else [str(value)]
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
        setattr(profile, name, None)
        profile.fields.pop(name, None)
        if name == "passport_country":
            profile.identity.passport_country = None
        elif name == "home_city":
            profile.identity.home_city = None
        elif name == "airlines_like":
            profile.prefs.airlines_like = []
        elif hasattr(profile.prefs, name):
            setattr(profile.prefs, name, None)
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
        now_iso = datetime.now(timezone.utc).isoformat()
        if passport_country is not None:
            profile.identity.passport_country = passport_country
            profile.passport_country = ProfileFieldValue(
                value=passport_country, source="user", updated_at=now_iso, confirmation="confirmed")
            profile.fields["passport_country"] = profile.passport_country
        if home_city is not None:
            profile.identity.home_city = home_city
            profile.home_city = ProfileFieldValue(
                value=home_city, source="user", updated_at=now_iso, confirmation="confirmed")
            profile.fields["home_city"] = profile.home_city
        self._persist(user_id)
        return profile

    # -- display/export (safe fields only) ------------------------------------

    def display(self, user_id: str) -> Dict[str, Any]:
        """Export-safe view: the model holds no passport-number/expiry/
        payment/legal-identity fields to begin with (canonical §5)."""
        return json.loads(self.get_or_create(user_id).model_dump_json())
