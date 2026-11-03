"""Licence codes signed in tests: a fresh Ed25519 key the hub is made to trust (monkeypatched TRUSTED_KEYS).

    signer = trust(monkeypatch)
    code = signer.code(rigs=6, seq=2)          # payload() defaults, with these fields changed
"""

from __future__ import annotations

from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from simtelemetry import licence_pubkey
from simtelemetry.licence import encode_payload, make_code

CAFE_ID = "cafe-apex"


def payload(**over: Any) -> dict[str, Any]:
    p = {"v": 1, "licence_id": "lic-0001", "cafe_id": CAFE_ID, "cafe_name": "Apex Lounge", "rigs": 6,
         "games": ["f1_25"], "features": ["moments", "battles", "owner"], "variant": "9t7",
         "issued": "2026-11-03", "seq": 1}
    p.update(over)
    return p


class Signer:
    def __init__(self, key: Ed25519PrivateKey | None = None) -> None:
        self.key = key or Ed25519PrivateKey.generate()

    @property
    def public(self) -> bytes:
        return self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

    def sign(self, p: dict[str, Any]) -> str:
        data = encode_payload(p)
        return make_code(data, self.key.sign(data))

    def code(self, **over: Any) -> str:
        return self.sign(payload(**over))


def trust(monkeypatch, signer: Signer | None = None) -> Signer:
    """A signer whose public key is the only one the hub trusts for the rest of the test."""
    signer = signer or Signer()
    monkeypatch.setattr(licence_pubkey, "TRUSTED_KEYS", (signer.public,))
    return signer
