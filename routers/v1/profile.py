"""Profile API router (§6 contracts, F5).

- GET    /api/profile/{user_id}                masked display only
- PUT    /api/profile/{user_id}/{field}        upsert; source ENFORCED to "user"
                                               server-side regardless of payload
- DELETE /api/profile/{user_id}/{field}        clears the field (never the file)
- POST   /api/profile/{user_id}/consent        {store_local} consent gate

Identity-shaped fields route to ProfileStore.set_identity (passport numbers
are masked at the boundary); pref fields land on Profile.prefs; everything
else goes through the generic source-tagged fields map. All persistence is
consent-gated inside the store. Errors surface via the shared §6 error
contract {error:{code,message,recoverable}}.
"""

from typing import Any, Optional, Tuple

from fastapi import APIRouter
from pydantic import BaseModel, ValidationError

from models.schemas import ProfileIdentity, ProfilePrefs
from services.profile_store import ProfileStore

router = APIRouter(prefix="/api/profile", tags=["Profile"])

# --- shared store singleton (the trip orchestrator reuses this instance) ----

_store: Optional[ProfileStore] = None


def get_profile_store() -> ProfileStore:
    global _store
    if _store is None:
        _store = ProfileStore()
    return _store


def set_profile_store(store: Optional[ProfileStore]) -> None:
    """Test hook: install/reset the shared store instance."""
    global _store
    _store = store


# --- error contract (shared shape, raised/handled via main.py) --------------


class TripApiError(Exception):
    """§6 error contract carrier: {error:{code,message,recoverable}}."""

    def __init__(self, status_code: int, code: str, message: str,
                 recoverable: bool = True, hint: Optional[str] = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.recoverable = recoverable
        self.hint = hint


_IDENTITY_FIELDS = {"passport_country", "passport_no", "passport_number",
                    "passport", "expiry", "home_city"}
_PREF_FIELDS = {"cabin", "diet", "budget_range", "airlines_like"}


class FieldPut(BaseModel):
    value: Any
    source: str = "user"  # accepted for shape parity; ENFORCED to "user"


class ConsentRequest(BaseModel):
    store_local: bool


def _guard_user_id(user_id: str) -> None:
    try:
        get_profile_store().get_or_create(user_id)
    except ValidationError:
        # a profile that cannot parse (e.g. previously corrupted out-of-band)
        # degrades to a RECOVERABLE envelope — never a bare 500 and never a
        # mislabeled invalid_user_id (G3-DA fix)
        raise TripApiError(
            400, "profile_unreadable",
            f"the stored profile for '{user_id}' could not be read",
            recoverable=True,
            hint="the stored profile is unreadable — contact support or "
                 "start fresh with a different user_id")
    except ValueError as exc:
        raise TripApiError(
            400, "invalid_user_id", str(exc), recoverable=True,
            hint="use only letters, digits, '_' or '-' in user_id")


def _store_error(exc: ValueError) -> TripApiError:
    return TripApiError(400, "invalid_profile_request", str(exc),
                        recoverable=True,
                        hint="check field name and value shape")


def _field_value_error(field: str, expectation: str) -> TripApiError:
    """§6 envelope for hostile PUT values; the message is scoped to the field
    and never echoes pydantic internals or raw user input (G3-DA fix)."""
    return TripApiError(
        400, "invalid_profile_request",
        f"value for field '{field}' failed validation: {expectation}",
        recoverable=True,
        hint=f"check the value shape for '{field}' (identity/pref fields "
             "expect strings; expiry expects an ISO date; airlines_like "
             "expects a list of strings)")


def _validate_identity_value(field: str, key: str,
                             value: Any) -> Tuple[str, Any]:
    """Boundary type guard + model validation BEFORE any store write.

    Prevents (a) non-string values reaching mask_passport's len() (bare 500)
    and (b) unparseable values (e.g. expiry='not-a-date') persisting and
    corrupting the profile file. Returns (key, normalized value): valid
    inputs are coerced through the identity model so the model never holds a
    raw unvalidated value (e.g. expiry lands as a real date, not the input
    string) — same validate-before-assignment contract as prefs (G3-DA fixes
    1+2)."""
    if not isinstance(value, str):
        raise _field_value_error(field, "expected a string")
    if key == "passport_no":
        return key, value  # any string is acceptable; the store masks it
    try:
        validated = ProfileIdentity(**{key: value})
    except ValidationError:
        raise _field_value_error(
            field, "expected a valid value (expiry: ISO date YYYY-MM-DD)")
    return key, getattr(validated, key)


@router.get("/{user_id}")
async def get_profile(user_id: str):
    """Masked, export-safe profile view (never raw passport bytes)."""
    _guard_user_id(user_id)
    return get_profile_store().display(user_id)


@router.put("/{user_id}/{field}")
async def put_profile_field(user_id: str, field: str, body: FieldPut):
    """Upsert one field. `source` is enforced to "user" server-side —
    clients cannot launder ai_inferred writes through this endpoint."""
    _guard_user_id(user_id)
    store = get_profile_store()
    try:
        if field in _IDENTITY_FIELDS:
            key = "passport_no" if field in ("passport_number", "passport") \
                else field
            key, normalized = _validate_identity_value(field, key, body.value)
            store.set_identity(user_id, **{key: normalized})
        elif field in _PREF_FIELDS:
            profile = store.get_or_create(user_id)
            # G3-DA fix: validate BEFORE assignment — rebuild the prefs model
            # with the new value so a ValidationError fires at the boundary
            # instead of persisting corrupt bytes that break every later load
            try:
                prefs = ProfilePrefs(
                    **{**profile.prefs.model_dump(mode="json"),
                       field: body.value})
            except ValidationError:
                raise _field_value_error(field, "value rejected by the "
                                                "profile prefs schema")
            profile.prefs = prefs
            store._persist(user_id)  # consent-gated atomic write
        else:
            store.set_field(user_id, field, body.value, source="user")
    except ValueError as exc:
        raise _store_error(exc)
    updated = store.display(user_id)
    field_view = updated.get("fields", {}).get(field)
    return {"user_id": user_id, "field": field,
            "source": "user",  # enforced, never echoed back as supplied
            "field_view": field_view, "profile": updated}


@router.delete("/{user_id}/{field}")
async def delete_profile_field(user_id: str, field: str):
    """Clears the field; the profile file is never deleted (S3 contract)."""
    _guard_user_id(user_id)
    store = get_profile_store()
    try:
        if field in _IDENTITY_FIELDS:
            profile = store.get_or_create(user_id)
            key = "passport_no_masked" if field in (
                "passport_no", "passport_number", "passport") else field
            setattr(profile.identity, key, None)
            store._persist(user_id)
        elif field in _PREF_FIELDS:
            profile = store.get_or_create(user_id)
            setattr(profile.prefs, field,
                    [] if field == "airlines_like" else None)
            store._persist(user_id)
        else:
            store.delete_field(user_id, field)
    except ValueError as exc:
        raise _store_error(exc)
    return {"user_id": user_id, "field": field, "deleted": True,
            "profile": store.display(user_id)}


@router.post("/{user_id}/consent")
async def set_consent(user_id: str, body: ConsentRequest):
    """Consent gate: nothing persists without store_local=true; withdrawal
    removes the persisted copy while the session keeps working in memory."""
    _guard_user_id(user_id)
    try:
        profile = get_profile_store().set_consent(user_id, body.store_local)
    except ValueError as exc:
        raise _store_error(exc)
    return {"user_id": user_id, "consent": profile.consent.model_dump(),
            "profile": get_profile_store().display(user_id)}
