"""Issuing licence codes (spec 2.2): sign a cafe profile's payload with the factory's private key.

`issue(profile, keys)` checks the profile, builds the payload (`CafeProfile.licence_payload`), validates it with the
hub's own `licence.check_payload` before signing, signs the canonical bytes with Ed25519 and proves the code
round-trips through `simtelemetry.licence.verify` with the key's public half. Nothing secret is in the result:
a code holds only the payload and the signature.

The caller (C10) appends the history entry after the package or upgrade is written; `seq` defaults to
`profile.next_seq()`, so each new code for a cafe is higher than the last and the hub accepts it as an add-on.
"""

from __future__ import annotations

import datetime as dt
import logging
import secrets
from pathlib import Path
from typing import NamedTuple

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from simtelemetry import licence

from .keys import Keys
from .profile import CafeProfile

log = logging.getLogger(__name__)


class IssueError(ValueError):
    """The licence couldn't be made; the message is plain English for the factory window."""


class Issued(NamedTuple):
    code: str
    payload: licence.LicencePayload


def new_licence_id() -> str:
    return "l-" + secrets.token_hex(8)


def issue(profile: CafeProfile, keys: Keys | Ed25519PrivateKey, seq: int | None = None,
          issued: dt.date | None = None, licence_id: str | None = None,
          logo_dir: Path | None = None) -> Issued:
    """The signed code and its payload. Refuses while the profile has problems, and a `seq` this cafe has used."""
    problems = profile.problems(logo_dir)
    if problems:
        raise IssueError("This cafe can't have a licence yet. Fix these first:\n"
                         + "\n".join(f"- {message}" for _, message in problems))
    next_seq = profile.next_seq()
    if seq is None:
        seq = next_seq
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < next_seq:
        raise IssueError(f"This cafe's next licence number is {next_seq}; an older number would be refused "
                         "by the cafe's hub.")
    private = keys.private if isinstance(keys, Keys) else keys
    if not isinstance(private, Ed25519PrivateKey):
        raise TypeError("keys must be factory.keys.Keys or an Ed25519 private key")
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

    data = licence.encode_payload(profile.licence_payload(seq=seq, licence_id=licence_id or new_licence_id(),
                                                          issued=issued or dt.date.today()))
    try:
        payload = licence.check_payload(data)                      # before signing: never sign what the hub refuses
    except licence.LicenceError:
        raise IssueError("The licence details aren't valid, so no code was made. Check the cafe's details.") from None
    code = licence.make_code(data, private.sign(data))
    try:
        checked = licence.verify(code, keys=(public,))
    except licence.LicenceError:
        raise IssueError("The new code didn't pass its own check, so it wasn't used. Try again.") from None
    if checked.payload != payload:
        raise IssueError("The new code didn't pass its own check, so it wasn't used. Try again.")
    log.info("Licence %s (number %d) issued for cafe %s", payload.licence_id, payload.seq, payload.cafe_id)
    return Issued(code=code, payload=payload)
