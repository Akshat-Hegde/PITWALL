import base64
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from simtelemetry import brand, licence, licence_pubkey
from simtelemetry.config import FeaturesConfig
from simtelemetry.licence import (ALREADY_INSTALLED, FALLBACK, INVALID, OLDER, OTHER_CAFE, LicenceError, accept_new,
                                  encode_payload, entitlements_from, make_code, parse, verify)


def raw_public(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


@pytest.fixture
def key():
    return Ed25519PrivateKey.generate()


@pytest.fixture
def trusted(monkeypatch, key):
    monkeypatch.setattr(licence_pubkey, "TRUSTED_KEYS", (raw_public(key),))
    return key


def payload(**over):
    p = {"v": 1, "licence_id": "lic-1", "cafe_id": "cafe-a", "cafe_name": "Apex Lounge", "rigs": 6,
         "games": ["f1_25"], "features": ["moments", "battles"], "variant": "9t7", "issued": "2026-11-03", "seq": 1}
    p.update(over)
    return p


def sign(key, p: dict) -> str:
    data = encode_payload(p)
    return make_code(data, key.sign(data))


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


# --- the public key file --------------------------------------------------------------------------

def test_every_trusted_key_is_a_valid_ed25519_public_key():
    for raw in licence_pubkey.TRUSTED_KEYS:
        assert isinstance(raw, bytes) and len(raw) == 32
        Ed25519PublicKey.from_public_bytes(raw)


# --- sign, verify, tamper -------------------------------------------------------------------------

def test_round_trip(trusted):
    code = sign(trusted, payload())
    assert code.startswith("PW1-") and "\n" not in code
    lic = verify(code)
    assert lic.code == code
    p = lic.payload
    assert (p.cafe_id, p.cafe_name, p.rigs, p.games, p.variant, p.seq) == ("cafe-a", "Apex Lounge", 6, ("f1_25",), "9t7", 1)
    assert p.issued.isoformat() == "2026-11-03"


def test_explicit_keys_argument(key):
    code = sign(key, payload())
    assert verify(code, keys=(raw_public(key),)).payload.cafe_id == "cafe-a"
    with pytest.raises(LicenceError):
        verify(code, keys=())


def test_any_trusted_key_may_sign(monkeypatch, key):
    other = Ed25519PrivateKey.generate()
    monkeypatch.setattr(licence_pubkey, "TRUSTED_KEYS", (raw_public(other), raw_public(key)))
    assert verify(sign(key, payload())).payload.seq == 1


def test_payload_byte_flip_is_refused(trusted):
    data = encode_payload(payload())
    sig = trusted.sign(data)
    flipped = data.replace(b'"rigs":6', b'"rigs":9')
    assert flipped != data
    with pytest.raises(LicenceError) as exc:
        verify(make_code(flipped, sig))
    assert str(exc.value) == INVALID
    for i in range(0, len(data), 7):          # any single byte changed
        bad = bytearray(data)
        bad[i] ^= 0x01
        with pytest.raises(LicenceError):
            verify(make_code(bytes(bad), sig))


def test_signature_byte_flip_is_refused(trusted):
    data = encode_payload(payload())
    sig = bytearray(trusted.sign(data))
    sig[10] ^= 0x80
    with pytest.raises(LicenceError):
        verify(make_code(data, bytes(sig)))


def test_wrong_key_is_refused(trusted):
    stranger = Ed25519PrivateKey.generate()
    with pytest.raises(LicenceError) as exc:
        verify(sign(stranger, payload()))
    assert str(exc.value) == INVALID


@pytest.mark.parametrize("cut", [1, 2, 5, 40, 90])
def test_truncated_code_is_refused(trusted, cut):
    code = sign(trusted, payload())
    with pytest.raises(LicenceError) as exc:
        verify(code[:-cut])
    assert str(exc.value) == INVALID


def test_truncated_from_the_front_is_refused(trusted):
    code = sign(trusted, payload())
    with pytest.raises(LicenceError):
        verify(code[6:])


@pytest.mark.parametrize("prefix", ["PW2-", "pw1-", "PW1", "XX1-", ""])
def test_wrong_prefix_is_refused(trusted, prefix):
    code = sign(trusted, payload())
    with pytest.raises(LicenceError) as exc:
        verify(prefix + code[len("PW1-"):])
    assert str(exc.value) == INVALID


@pytest.mark.parametrize("garbage", ["", "   ", "hello", "PW1-", "PW1-.", "PW1-abc", "PW1-abc.def", "PW1-a.b.c",
                                     "PW1-!!!!.????", "PW1-" + "A" * 50 + "." + "B" * 86 + "*", None, 123, b"PW1-x.y"])
def test_garbage_is_refused(trusted, garbage):
    with pytest.raises(LicenceError) as exc:
        verify(garbage)
    assert str(exc.value) == INVALID


def test_whitespace_and_line_breaks_anywhere_are_ignored(trusted):
    code = sign(trusted, payload())
    mid = len(code) // 2
    pasted = "\n  " + code[:10] + " \r\n" + code[10:mid] + "\t" + code[mid:-5] + "\n" + code[-5:] + "  \n"
    lic = verify(pasted)
    assert lic.code == code            # stored normalised
    assert parse(pasted).code == code


def test_padding_is_tolerated(trusted):
    data = encode_payload(payload())
    sig = trusted.sign(data)
    padded = "PW1-" + base64.urlsafe_b64encode(data).decode() + "." + base64.urlsafe_b64encode(sig).decode()
    assert verify(padded).payload.cafe_id == "cafe-a"


@pytest.mark.parametrize("over", [{"v": 2}, {"v": "1"}, {"rigs": 0}, {"rigs": "6"}, {"rigs": True},
                                  {"variant": "other"}, {"games": []}, {"cafe_id": ""}, {"issued": "soon"},
                                  {"seq": -1}, {"features": "moments"}])
def test_signed_but_bad_payload_is_refused(trusted, over):
    with pytest.raises(LicenceError) as exc:
        verify(sign(trusted, payload(**over)))
    assert str(exc.value) == INVALID


def test_signed_non_json_is_refused(trusted):
    data = b"not json"
    with pytest.raises(LicenceError):
        verify(make_code(data, trusted.sign(data)))


def test_unknown_payload_keys_are_ignored(trusted):
    assert verify(sign(trusted, payload(extra="later"))).payload.seq == 1


def test_encode_payload_is_canonical():
    a = encode_payload({"b": 1, "a": "Café"})
    assert a == '{"a":"Café","b":1}'.encode("utf-8")
    assert encode_payload(json.loads(a)) == a


# --- no keys: every code fails, the hub uses the fallback ------------------------------------------

def test_no_trusted_keys_means_every_code_fails(monkeypatch, key):
    monkeypatch.setattr(licence_pubkey, "TRUSTED_KEYS", ())
    with pytest.raises(LicenceError) as exc:
        verify(sign(key, payload()))
    assert str(exc.value) == INVALID


def test_fallback_entitlement():
    assert FALLBACK.source == "fallback"
    assert FALLBACK.rigs == 4 and FALLBACK.games == ("f1_25",) and FALLBACK.variant == "9t7"
    assert set(FALLBACK.features) == set(FeaturesConfig.model_fields)
    assert FALLBACK.vendor_mark is True
    assert FALLBACK.cafe_id is None and FALLBACK.licence_id is None


# --- entitlements ------------------------------------------------------------------------------------

def test_entitlements_from_licence(trusted):
    ent = entitlements_from(verify(sign(trusted, payload(features=["moments", "battles", "moments", "teleport"]))))
    assert ent.source == "licence"
    assert ent.rigs == 6 and ent.games == ("f1_25",)
    assert ent.features == ("moments", "battles")      # unknown names dropped, duplicates removed
    assert (ent.cafe_id, ent.cafe_name, ent.licence_id, ent.seq) == ("cafe-a", "Apex Lounge", "lic-1", 1)


def test_licensed_rigs_are_the_first_n_by_number():
    ent = FALLBACK
    assert [n for n in range(0, 8) if ent.licensed(n)] == [1, 2, 3, 4]
    assert ent.licensed(None) is False


def test_supplier_and_vendor_mark_follow_the_variant(trusted):
    ours = entitlements_from(verify(sign(trusted, payload(variant="9t7"))))
    plain = entitlements_from(verify(sign(trusted, payload(variant="unbranded"))))
    assert ours.supplier == brand.COMPANY and ours.vendor_mark is True
    assert plain.supplier == "your supplier" and plain.vendor_mark is False


# --- accepting a new code ----------------------------------------------------------------------------

def test_first_code_is_accepted_over_fallback_or_nothing(trusted):
    new = verify(sign(trusted, payload(seq=0)))
    assert accept_new(None, new).cafe_id == "cafe-a"
    assert accept_new(FALLBACK, new).source == "licence"


def test_higher_seq_same_cafe_is_accepted(trusted):
    current = entitlements_from(verify(sign(trusted, payload(seq=1))))
    upgraded = accept_new(current, verify(sign(trusted, payload(seq=2, licence_id="lic-2", rigs=8))))
    assert upgraded.rigs == 8 and upgraded.seq == 2


def test_other_cafe_is_refused(trusted):
    current = entitlements_from(verify(sign(trusted, payload(seq=1))))
    with pytest.raises(LicenceError) as exc:
        accept_new(current, verify(sign(trusted, payload(cafe_id="cafe-b", seq=5))))
    assert str(exc.value) == OTHER_CAFE


@pytest.mark.parametrize("seq", [0, 1, 2])
def test_older_or_equal_seq_is_refused(trusted, seq):
    current = entitlements_from(verify(sign(trusted, payload(seq=2, licence_id="lic-2"))))
    with pytest.raises(LicenceError) as exc:
        accept_new(current, verify(sign(trusted, payload(seq=seq, licence_id=f"other-{seq}"))))
    assert str(exc.value) == OLDER


def test_same_code_again_says_already_installed(trusted):
    code = sign(trusted, payload(seq=3))
    current = entitlements_from(verify(code))
    with pytest.raises(LicenceError) as exc:
        accept_new(current, verify(code))
    assert str(exc.value) == ALREADY_INSTALLED


def test_messages_are_plain_english():
    for msg in (INVALID, OTHER_CAFE, OLDER, ALREADY_INSTALLED):
        assert msg.endswith(".") and not any(w in msg.lower() for w in ("signature", "seq", "payload", "base64"))


# --- review hardening (C1 review) --------------------------------------------------------------------

@pytest.mark.parametrize("over", [{"v": True}, {"v": 1.0}, {"seq": True}, {"seq": 2**31}, {"rigs": 6.0},
                                  {"games": [""]}, {"features": ["  "]}, {"cafe_id": "   "},
                                  {"cafe_name": "Apex\u0000Lounge"}, {"cafe_name": "Apex\nLounge"},
                                  {"cafe_name": "A" * 101}, {"games": ["g" * 41]}])
def test_signed_payload_with_odd_values_is_refused(trusted, over):
    with pytest.raises(LicenceError) as exc:
        verify(sign(trusted, payload(**over)))
    assert str(exc.value) == INVALID


def test_non_ascii_cafe_name_survives(trusted):
    name = "कैफ़े Apex · Café"
    assert verify(sign(trusted, payload(cafe_name=name))).payload.cafe_name == name


@pytest.mark.parametrize("ch", [" ", " ", "　", "​", "﻿", "‍"])
def test_unicode_spaces_and_invisible_characters_are_ignored(trusted, ch):
    code = sign(trusted, payload())
    assert verify(ch + code[:12] + ch + code[12:] + ch).code == code


def test_non_ascii_digits_are_not_base64(trusted):
    with pytest.raises(LicenceError):
        parse("PW1-" + "١" * 12 + "." + "A" * 86)


def test_huge_input_is_refused_quickly(trusted):
    with pytest.raises(LicenceError) as exc:
        verify("PW1-" + "A" * (licence.MAX_CODE_LEN + 1) + ".B")
    assert str(exc.value) == INVALID


def test_a_single_key_passed_as_bytes_is_a_programming_error(key):
    with pytest.raises(TypeError):
        verify(sign(key, payload()), keys=raw_public(key))


def test_encode_payload_accepts_the_model_and_dates(trusted):
    import datetime as dt
    model = verify(sign(trusted, payload())).payload
    data = encode_payload(model)
    assert data == encode_payload(payload(games=["f1_25"], features=["moments", "battles"]))
    assert encode_payload(payload(issued=dt.date(2026, 11, 3))) == data
    assert licence.check_payload(data) == model
    with pytest.raises(LicenceError):
        licence.check_payload(encode_payload(payload(rigs=0)))


def test_licensed_refuses_non_numbers():
    assert FALLBACK.licensed(True) is False and FALLBACK.licensed("1") is False
