"""Profile API router (§6 contracts, F5/F17 — canonical R1 contract).

- GET    /api/profile/{user_id}                safe profile display
- PUT    /api/profile/{user_id}/{field}        upsert; source ENFORCED to "user"
                                               server-side regardless of payload
- DELETE /api/profile/{user_id}/{field}        clears the field (never the file)
- POST   /api/profile/{user_id}/consent        {store_local} consent gate

SAFE FIELD ALLOWLIST ONLY (canonical §5): passport_country, home_city,
preferred_origin_airport, cabin, airlines_like, diet, budget_range,
display_currency, accessibility_notes. NO passport number exists anywhere:
passport-number/expiry/identity-document/payment shapes are REFUSED with a
recoverable §6 envelope, and unknown fields are refused too. All
persistence is consent-gated inside the store. Errors surface via the
shared §6 error contract {error:{code,message,recoverable}}.
"""

from typing import Any, Optional, Tuple

from fastapi import APIRouter
from pydantic import BaseModel, ValidationError

from models.schemas import (FORBIDDEN_PROFILE_FIELDS, ProfileIdentity,
                            ProfilePrefs)
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


_IDENTITY_FIELDS = {"passport_country", "home_city"}
_PREF_FIELDS = {"cabin", "diet", "budget_range", "airlines_like",
                "preferred_origin_airport", "display_currency",
                "accessibility_notes"}


class FieldPut(BaseModel):
    value: Any
    source: str = "user"  # accepted for shape parity; ENFORCED to "user"


class ConsentRequest(BaseModel):
    store_local: bool


def _forbidden_field_error(field: str) -> TripApiError:
    """R1/P0 canonical contract: passport numbers, document ids, legal
    identity and payment data are NEVER requested, accepted, or stored.
    The refusal message never echoes the submitted value."""
    return TripApiError(
        400, "forbidden_profile_field",
        f"field '{field}' is not stored by this demo: passport numbers, "
        "document numbers, legal identity and payment details are never "
        "collected. Passport country is sufficient for visas and routing.",
        recoverable=True,
        hint="store only safe preferences (home city, cabin, budget, "
             "currency, accessibility notes)")


def _unknown_field_error(field: str) -> TripApiError:
    return TripApiError(
        400, "unknown_profile_field",
        f"field '{field}' is not a recognized safe profile field",
        recoverable=True,
        hint=f"allowed fields: {', '.join(sorted(_IDENTITY_FIELDS | _PREF_FIELDS))}")


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
        hint=f"check the value shape for '{field}' (safe identity/pref "
             "fields expect strings; airlines_like expects a list of "
             "strings)")


def _validate_identity_value(field: str, key: str,
                             value: Any) -> Tuple[str, Any]:
    """Boundary type guard + model validation BEFORE any store write.

    Prevents non-string values and unparseable values from persisting and
    corrupting the profile file. Returns (key, normalized value): valid
    inputs are coerced through the identity model so the model never holds
    a raw unvalidated value (G3-DA validate-before-assignment contract)."""
    if not isinstance(value, str):
        raise _field_value_error(field, "expected a string")
    try:
        validated = ProfileIdentity(**{key: value})
    except ValidationError:
        raise _field_value_error(field, "expected a valid value")
    return key, getattr(validated, key)


@router.get("/{user_id}")
async def get_profile(user_id: str):
    """Safe, export-safe profile view (safe fields only; no passport number exists)."""
    _guard_user_id(user_id)
    return get_profile_store().display(user_id)


@router.put("/{user_id}/{field}")
async def put_profile_field(user_id: str, field: str, body: FieldPut):
    """Upsert one SAFE field. `source` is enforced to "user" server-side —
    clients cannot launder ai_inferred writes through this endpoint.
    Passport-number/identity-document/payment shapes are REFUSED (R1/P0)."""
    _guard_user_id(user_id)
    if field in FORBIDDEN_PROFILE_FIELDS:
        raise _forbidden_field_error(field)
    store = get_profile_store()
    try:
        if field in _IDENTITY_FIELDS:
            key, normalized = _validate_identity_value(field, field,
                                                       body.value)
            store.set_identity(user_id, **{key: normalized})
        elif field in _PREF_FIELDS:
            profile = store.get_or_create(user_id)
            # validate BEFORE assignment — rebuild the prefs model with the
            # new value so a ValidationError fires at the boundary instead
            # of persisting corrupt bytes that break every later load
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
            raise _unknown_field_error(field)
    except ValueError as exc:
        raise _store_error(exc)
    updated = store.display(user_id)
    return {"user_id": user_id, "field": field,
            "source": "user",  # enforced, never echoed back as supplied
            "profile": updated}


@router.delete("/{user_id}/{field}")
async def delete_profile_field(user_id: str, field: str):
    """Clears one SAFE field; the profile file is never deleted (S3)."""
    _guard_user_id(user_id)
    if field in FORBIDDEN_PROFILE_FIELDS:
        raise _forbidden_field_error(field)
    store = get_profile_store()
    try:
        if field in _IDENTITY_FIELDS:
            profile = store.get_or_create(user_id)
            setattr(profile.identity, field, None)
            store._persist(user_id)
        elif field in _PREF_FIELDS:
            profile = store.get_or_create(user_id)
            setattr(profile.prefs, field,
                    [] if field == "airlines_like" else None)
            store._persist(user_id)
        else:
            raise _unknown_field_error(field)
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
