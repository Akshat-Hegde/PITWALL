import base64
import datetime as dt
import logging

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from factory import keys as K
from factory.licence_issue import IssueError, issue
from factory.profile import CafeProfile, Contact, HistoryEntry
from simtelemetry import licence, licence_pubkey

DAY = dt.date(2026, 11, 3)


@pytest.fixture
def keys(tmp_path):
    return K.create_keys(tmp_path / "keys")


def cafe(**over) -> CafeProfile:
    p = CafeProfile.new("Apex Lounge", rigs=6)
    for k, v in over.items():
        setattr(p, k, v)
    return p


def history(seq: int) -> HistoryEntry:
    return HistoryEntry(pitwall_version="0.6.0", licence_id=f"l-{seq}", seq=seq, date=DAY)


def test_issue_then_verify_with_trusted_keys(keys, monkeypatch):
    monkeypatch.setattr(licence_pubkey, "TRUSTED_KEYS", (keys.public,))
    p = cafe()
    code, payload = issue(p, keys, issued=DAY)
    lic = licence.verify(code)                                # the hub's default: licence_pubkey.TRUSTED_KEYS
    assert lic.payload == payload and lic.code == code
    assert payload.cafe_id == p.cafe_id and payload.rigs == 6 and payload.seq == 1 and payload.issued == DAY
    assert list(payload.features) == p.features_on() and payload.variant == "9t7"
    ent = licence.entitlements_from(lic)
    assert ent.rigs == 6 and ent.cafe_name == "Apex Lounge"


def test_issue_verifies_with_keys_param_and_not_with_another_key(keys):
    code, _ = issue(cafe(), keys)
    licence.verify(code, keys=(keys.public,))
    with pytest.raises(licence.LicenceError):
        licence.verify(code, keys=(K.create_keys(keys.folder.parent / "other").public,))


def test_a_raw_private_key_works_too():
    key = Ed25519PrivateKey.generate()
    code, _ = issue(cafe(), key)
    licence.verify(code, keys=(key.public_key().public_bytes(K.Encoding.Raw, K.PublicFormat.Raw),))
    with pytest.raises(TypeError):
        issue(cafe(), b"not a key")


def test_seq_follows_history(keys):
    p = cafe()
    assert issue(p, keys).payload.seq == 1
    p.history = [history(1), history(3)]
    _, payload = issue(p, keys)
    assert payload.seq == 4
    assert issue(p, keys, seq=9).payload.seq == 9
    for bad in (3, 1, 0, True):
        with pytest.raises(IssueError, match="next licence number is 4"):
            issue(p, keys, seq=bad)


def test_a_new_code_is_accepted_as_an_add_on(keys):
    p = cafe(rigs=4)
    first = licence.verify(issue(p, keys).code, keys=(keys.public,))
    p.history = [history(first.payload.seq)]
    p.rigs = 6
    second = licence.verify(issue(p, keys).code, keys=(keys.public,))
    ent = licence.accept_new(licence.entitlements_from(first), second)
    assert ent.rigs == 6 and ent.seq == 2


def test_licence_ids_are_random_and_can_be_given(keys):
    a, b = issue(cafe(), keys).payload.licence_id, issue(cafe(), keys).payload.licence_id
    assert a != b and a.startswith("l-")
    assert issue(cafe(), keys, licence_id="l-fixed").payload.licence_id == "l-fixed"


def test_refuses_a_profile_with_problems(keys):
    p = cafe(name="", rigs=0)
    with pytest.raises(IssueError) as e:
        issue(p, keys)
    msg = str(e.value)
    assert msg.startswith("This cafe can't have a licence yet") and "Enter the cafe's name." in msg
    assert len(msg.splitlines()) >= 3


def test_refuses_with_a_missing_logo_when_checked(keys, tmp_path):
    p = cafe(logo="missing.png")
    with pytest.raises(IssueError):
        issue(p, keys, logo_dir=tmp_path)


def test_checks_the_payload_before_signing(keys, monkeypatch):
    calls = []
    real_check, real_make = licence.check_payload, licence.make_code
    monkeypatch.setattr(licence, "check_payload", lambda d: calls.append("check") or real_check(d))
    monkeypatch.setattr(licence, "make_code", lambda d, s: calls.append("sign") or real_make(d, s))
    issue(cafe(), keys)
    assert calls.index("check") < calls.index("sign")         # (problems() and verify() check too)
    calls.clear()
    monkeypatch.setattr(CafeProfile, "licence_payload", lambda self, **kw: {"v": 2})
    monkeypatch.setattr(CafeProfile, "problems", lambda self, logo_dir=None: [])   # past problems()' own net
    with pytest.raises(IssueError, match="aren't valid"):
        issue(cafe(), keys)
    assert "check" in calls and "sign" not in calls


def test_no_contact_or_key_material_in_code_or_logs(keys, caplog):
    caplog.set_level(logging.DEBUG)
    p = cafe()
    p.contact = Contact(name="Ravi Kumar", phone="+91 98765 43210")
    code, payload = issue(p, keys)
    raw = keys.private.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    parsed = licence.parse(code)
    decoded = parsed.payload + parsed.signature
    for text in (code, payload.model_dump_json(), caplog.text):
        assert raw.hex() not in text and base64.b64encode(raw).decode() not in text
        assert base64.urlsafe_b64encode(raw).decode().rstrip("=") not in text
        assert "98765" not in text
    assert raw not in decoded
    assert payload.licence_id in caplog.text
