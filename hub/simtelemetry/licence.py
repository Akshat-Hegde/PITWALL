"""Licence codes: parse, verify (offline, no clock) and turn into entitlements.

A code is one copy-pasteable line, `PW1-<base64url payload>.<base64url Ed25519 signature>`, and the payload is
canonical JSON (see `encode_payload`): the factory signs exactly the bytes the hub verifies.

API (errors are exceptions, never return values):
- `parse(code) -> Parsed`                       raises LicenceError (INVALID)
- `verify(code, keys=None) -> Licence`          raises LicenceError (INVALID); keys=None means licence_pubkey.TRUSTED_KEYS
- `entitlements_from(licence) -> Entitlements`
- `encode_payload(dict | LicencePayload) -> bytes`, `check_payload(bytes) -> LicencePayload`, `make_code(payload, sig)`
                                                for the factory, which signs exactly these bytes
- `accept_new(current, new) -> Entitlements`    raises LicenceError (OTHER_CAFE, OLDER, ALREADY_INSTALLED)
- `FALLBACK`                                    used when there is no licence or it is damaged

LicenceError's message is plain English, shown to the owner as-is.
"""

from __future__ import annotations

import base64
import binascii
import datetime as dt
import json
import re
from dataclasses import dataclass
from typing import Annotated, Any, Literal, NamedTuple

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from . import brand, licence_pubkey
from .config import FeaturesConfig

PREFIX = "PW1-"
SIG_LEN = 64
MAX_CODE_LEN = 20_000      # a real code is well under 1,000 characters; anything far longer is refused unread

INVALID = "This code isn't valid: check you copied all of it."
OTHER_CAFE = "This code is for a different cafe."
OLDER = "This code is older than the one installed."
ALREADY_INSTALLED = "This code is already installed."

_B64URL = re.compile(r"[A-Za-z0-9_-]+={0,2}")
# Invisible characters that copy-paste (chat apps, Notepad's UTF-8 BOM) can slip into a code. Never part of base64url.
_INVISIBLE = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad"))

# One line of visible text: no control characters, not blank.
_CTRL = r"\x00-\x1f\x7f"
_TEXT = rf"^[^{_CTRL}]*[^\s{_CTRL}][^{_CTRL}]*$"
Text = Annotated[str, StringConstraints(min_length=1, max_length=100, pattern=_TEXT)]
Name = Annotated[str, StringConstraints(min_length=1, max_length=40, pattern=_TEXT)]


class LicenceError(ValueError):
    """A code that can't be used; the message is shown to the owner as-is."""


class LicencePayload(BaseModel):
    """The signed JSON (spec 2.2). Unknown keys are ignored so a newer factory's v1 codes still load."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    v: int = Field(ge=1, le=1)         # a strict int, so `true` and `1.0` are refused
    licence_id: Text
    cafe_id: Text
    cafe_name: Text
    rigs: int = Field(ge=1, le=999)
    games: tuple[Name, ...] = Field(min_length=1)
    features: tuple[Name, ...]         # the features that are on; names not known to this hub are ignored later
    variant: Literal["9t7", "unbranded"]
    issued: dt.date
    seq: int = Field(ge=0, le=2**31 - 1)   # stays exact in JSON for the owner page's browser


class Parsed(NamedTuple):
    code: str           # normalised: whitespace removed
    payload: bytes
    signature: bytes


@dataclass(frozen=True)
class Licence:
    code: str           # normalised, as written to licence.txt
    payload: LicencePayload


@dataclass(frozen=True)
class Entitlements:
    rigs: int
    games: tuple[str, ...]
    features: tuple[str, ...]
    variant: Literal["9t7", "unbranded"]
    cafe_name: str | None
    licence_id: str | None
    cafe_id: str | None
    seq: int
    source: Literal["licence", "fallback"]

    def licensed(self, rig_number: int | None) -> bool:
        """Rig numbers are 1-based ("Rig N"); the first `rigs` numbers are licensed."""
        return isinstance(rig_number, int) and not isinstance(rig_number, bool) and 1 <= rig_number <= self.rigs

    @property
    def supplier(self) -> str:
        return brand.COMPANY if self.variant == "9t7" else "your supplier"

    @property
    def vendor_mark(self) -> bool:
        return self.variant == "9t7"


FALLBACK = Entitlements(rigs=4, games=("f1_25",), features=tuple(FeaturesConfig.model_fields), variant="9t7",
                        cafe_name=None, licence_id=None, cafe_id=None, seq=0, source="fallback")


# --- encoding (shared with the factory) -------------------------------------------------------

def encode_payload(payload: dict[str, Any] | LicencePayload) -> bytes:
    """Canonical payload bytes: sorted keys, compact separators, UTF-8. Dates are written as ISO dates.

    The factory should sign only bytes that `check_payload` accepts, so it can never issue a code the hub refuses.
    """
    if isinstance(payload, LicencePayload):
        payload = payload.model_dump(mode="json")
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      default=_json_default).encode("utf-8")


def _json_default(value: Any) -> Any:
    if isinstance(value, dt.date):
        return value.isoformat()
    raise TypeError(f"not JSON serialisable: {type(value).__name__}")


def check_payload(data: bytes) -> LicencePayload:
    """The payload model for signed bytes, or LicenceError(INVALID). The hub runs this after the signature check."""
    try:
        return LicencePayload.model_validate_json(data)
    except ValidationError:
        raise LicenceError(INVALID) from None


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    if not _B64URL.fullmatch(text):
        raise LicenceError(INVALID)
    text = text.rstrip("=")
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError):
        raise LicenceError(INVALID) from None


def make_code(payload: bytes, signature: bytes) -> str:
    """The code text for signed payload bytes (the factory signs, this only formats)."""
    return f"{PREFIX}{_b64e(payload)}.{_b64e(signature)}"


# --- parsing and verifying --------------------------------------------------------------------

def parse(code: str) -> Parsed:
    """Split a pasted code into payload and signature. Whitespace and line breaks anywhere are ignored."""
    if not isinstance(code, str) or len(code) > MAX_CODE_LEN:
        raise LicenceError(INVALID)
    text = "".join(code.translate(_INVISIBLE).split())
    if not text.startswith(PREFIX):
        raise LicenceError(INVALID)
    parts = text[len(PREFIX):].split(".")
    if len(parts) != 2 or not all(parts):
        raise LicenceError(INVALID)
    payload, signature = _b64d(parts[0]), _b64d(parts[1])
    if not payload or len(signature) != SIG_LEN:
        raise LicenceError(INVALID)
    return Parsed(code=text, payload=payload, signature=signature)


def _signed_by(parsed: Parsed, keys: tuple[bytes, ...]) -> bool:
    for raw in keys:
        try:
            Ed25519PublicKey.from_public_bytes(raw).verify(parsed.signature, parsed.payload)
            return True
        except (InvalidSignature, ValueError, TypeError):
            continue
    return False


def verify(code: str, keys: tuple[bytes, ...] | None = None) -> Licence:
    """A verified licence, or LicenceError(INVALID). `keys` defaults to licence_pubkey.TRUSTED_KEYS (read now)."""
    parsed = parse(code)
    if keys is None:
        keys = licence_pubkey.TRUSTED_KEYS
    elif isinstance(keys, (bytes, bytearray)):
        raise TypeError("keys must be a tuple of raw public keys, not one key")
    if not _signed_by(parsed, tuple(keys)):
        raise LicenceError(INVALID)
    return Licence(code=parsed.code, payload=check_payload(parsed.payload))


def entitlements_from(licence: Licence) -> Entitlements:
    p = licence.payload
    known = set(FeaturesConfig.model_fields)
    return Entitlements(rigs=p.rigs, games=tuple(dict.fromkeys(p.games)),
                        features=tuple(f for f in dict.fromkeys(p.features) if f in known),
                        variant=p.variant, cafe_name=p.cafe_name, licence_id=p.licence_id, cafe_id=p.cafe_id,
                        seq=p.seq, source="licence")


def accept_new(current: Entitlements | None, new: Licence) -> Entitlements:
    """Whether a verified new code may replace the current one: same cafe (or no real licence yet) and a higher seq."""
    ent = entitlements_from(new)
    if current is None or current.source == "fallback":
        return ent
    if ent.cafe_id != current.cafe_id:
        raise LicenceError(OTHER_CAFE)
    if ent.seq == current.seq and ent.licence_id == current.licence_id:
        raise LicenceError(ALREADY_INSTALLED)
    if ent.seq <= current.seq:
        raise LicenceError(OLDER)
    return ent
