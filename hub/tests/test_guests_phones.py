"""Guests and phones: the phone test (/hello, U4), names (K10) and the sticker-sheet address warning (K4)."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from simtelemetry import brand
from simtelemetry.api.app import create_app
from simtelemetry.core.drivers import NAME_MAX, DriverError, clean_name
from simtelemetry.core.names import is_blocked
from simtelemetry.core.phone_test import (FAIL_ADVICE, NO_NETWORK, NOT_YET, WIFI_ADVICE, PhoneTest, is_this_pc,
                                          usable_address)

from f1_helpers import STAFF, staff_ready
from test_checkin import checkin_client, post
from test_drivers import RIG, make_hub

PHONE = ("192.168.1.77", 50000)
API = Path(__file__).parents[1] / "simtelemetry" / "api"


def _app(hub, tmp_path, client=PHONE, **kw):
    return TestClient(create_app(hub, dashboard_dir=tmp_path / "none"), client=client, **kw)


# --- /hello and the phone test ----------------------------------------------------------------------

def test_hello_from_a_phone_says_it_works_and_is_recorded(tmp_path, monkeypatch):
    hub = make_hub(tmp_path)
    monkeypatch.setattr(hub, "own_addresses", lambda: {"192.168.1.10"})
    status = _app(hub, tmp_path, client=("192.168.1.10", 1)).get("/api/phone-test").json()
    assert status == {"reached": False, "reached_at": None, "text": NOT_YET}
    r = _app(hub, tmp_path).get("/hello")                                     # no PIN needed
    assert r.status_code == 200 and "no-store" in r.headers["cache-control"]
    assert f"Your phone can reach {brand.PRODUCT_NAME}. Check-in and cards will work." in r.text
    assert "{{" not in r.text and "192.168." not in r.text and "<script" not in r.text and "http" not in r.text
    status = _app(hub, tmp_path).get("/api/phone-test").json()
    assert status["reached"] is True and status["text"].startswith("A phone reached the hub at ")
    assert "192.168" not in str(status)
    assert (tmp_path / "phone-test.json").is_file()                          # survives a restart
    hub.drivers.store.close()
    assert make_hub(tmp_path).phone_test.reached_at is not None


@pytest.mark.parametrize("client", [("127.0.0.1", 1), ("192.168.1.10", 1), ("testclient", 1)])
def test_hello_from_the_hub_pc_itself_is_not_a_phone(tmp_path, monkeypatch, client):
    hub = make_hub(tmp_path)
    monkeypatch.setattr(hub, "own_addresses", lambda: {"192.168.1.10"})
    r = _app(hub, tmp_path, client=client).get("/hello")
    assert r.status_code == 200 and "This is the hub PC" in r.text
    assert hub.phone_test.reached_at is None


def test_status_text_has_the_time_and_the_day_when_not_today():
    t = PhoneTest(None, clock=lambda: dt.datetime(2026, 10, 15, 14, 2).timestamp())
    assert t.status_text() == NOT_YET
    assert t.record("192.168.1.77", {"192.168.1.10"})
    assert t.status_text(today=lambda: dt.date(2026, 10, 15)) == "A phone reached the hub at 14:02"
    assert t.status_text(today=lambda: dt.date(2026, 10, 16)) == "A phone reached the hub at 14:02 on Thu 15 Oct"


def test_setup_and_staff_health_show_the_qr_for_the_hub_address(tmp_path, monkeypatch):
    hub = staff_ready(make_hub(tmp_path))
    monkeypatch.setattr(hub, "hub_address", lambda: "192.168.1.10")
    setup = _app(hub, tmp_path).get("/api/setup").json()["phone_test"]
    port = hub.config.network.http_port
    assert setup["url"] == f"http://192.168.1.10:{port}/hello" and setup["svg"].lstrip().startswith("<svg")
    assert setup["text"] == NOT_YET and setup["problem"] is None
    assert setup["advice"] == WIFI_ADVICE and setup["fail_advice"] == FAIL_ADVICE
    health = _app(hub, tmp_path, headers=STAFF).get("/api/staff/health").json()["phone_test"]
    assert health["url"] == setup["url"] and health["svg"]


def test_no_qr_without_a_network_address(tmp_path, monkeypatch):
    hub = staff_ready(make_hub(tmp_path))
    monkeypatch.setattr(hub, "hub_address", lambda: None)
    p = _app(hub, tmp_path, headers=STAFF).get("/api/staff/health").json()["phone_test"]
    assert p["url"] is None and p["svg"] is None and p["problem"] == NO_NETWORK


def test_usable_address():
    assert usable_address("192.168.1.10") and usable_address("hub-pc")
    assert not usable_address(None) and not usable_address("") and not usable_address("localhost")
    assert not usable_address("127.0.0.1")


def test_pages_have_the_phone_test_and_the_wifi_advice():
    for page in ("setup.html", "staff.html"):
        text = (API / page).read_text(encoding="utf-8")
        assert "Test from your phone" in text and 'id="phone-qr"' in text and "p.advice" in text, page


# --- names (K10) --------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["Niki Lauda", "Lauda", "Dick", "Dick Smith", "Philip K Dick", "d i c k"])
def test_real_names_on_the_allow_list_pass(name):
    assert not is_blocked(name)


def test_allow_list_does_not_open_other_words_and_a_cafe_can_still_block():
    assert is_blocked("dickhead") and is_blocked("lawda") and is_blocked("Niki fuck")
    assert is_blocked("Niki Lauda", ["lauda"])                     # the cafe's own list wins


def test_clean_name_strips_invisible_format_characters():
    assert clean_name("Al​ex") == "Alex"                       # zero-width space
    assert clean_name("‮Alex‬") == "Alex"                 # right-to-left override
    assert clean_name("Ma‍ya﻿") == "Maya"                 # joiner, byte-order mark
    assert clean_name("A⁦l⁩") == "Al"                     # bidi isolates
    with pytest.raises(DriverError):
        clean_name("​​")                                  # nothing visible left
    assert is_blocked(clean_name("f​uck"))                     # can't hide a word with them


def test_names_are_capped_at_16_characters():
    assert NAME_MAX == 16
    assert clean_name("A" * 16) == "A" * 16
    with pytest.raises(DriverError, match="at most 16"):
        clean_name("A" * 17)


async def test_staff_start_and_check_in_refuse_a_name_over_16(tmp_path):
    hub, client, code = await checkin_client(tmp_path)
    assert post(client, code, "Maximilian Verstappen").status_code == 400
    assert post(client, code, "Niki Lauda").status_code == 200
    hub.drivers.end(RIG)
    r = client.put(f"/api/staff/rigs/{RIG}/driver", json={"name": "Maximilian Verstappen"})
    assert r.status_code == 400 and "16" in r.json()["detail"]


def test_name_inputs_have_maxlength_16():
    assert 'id="name" maxlength="16"' in (API / "checkin.html").read_text(encoding="utf-8")
    staff = (API / "staff.html").read_text(encoding="utf-8")
    assert 'class="rig__name-input" maxlength="16"' in staff and 'id="queue-name" maxlength="16"' in staff


# --- sticker sheet (K4) -------------------------------------------------------------------------------

async def test_sticker_sheet_warns_without_a_real_address(tmp_path, monkeypatch):
    hub, client, code = await checkin_client(tmp_path)
    monkeypatch.setattr(hub, "hub_address", lambda: None)
    sheet = client.get("/api/staff/checkin/sheet").json()
    assert sheet["address_warning"] == ("Phones can't reach 'localhost'. Connect this PC to the cafe network, "
                                        "then reprint.")
    monkeypatch.setattr(hub, "hub_address", lambda: "127.0.0.1")
    assert "Phones can't reach '127.0.0.1'" in client.get("/api/staff/checkin/sheet").json()["address_warning"]
    monkeypatch.setattr(hub, "hub_address", lambda: "192.168.1.10")
    assert client.get("/api/staff/checkin/sheet").json()["address_warning"] is None
    page = client.get("/staff/checkin-print").text
    assert 'id="addr-warn"' in page and "data.address_warning" in page


# --- Task 4 review fixes ------------------------------------------------------------------------------

@pytest.mark.parametrize("name", [
    "\u0938\u0942\u0930\u094d\u200d\u092f\u093e",            # Surya with the Marathi eyelash ra (ZWJ after virama)
    "\u0930\u093e\u091c\u094d\u200d\u092f",                  # Rajya, eyelash ra
    "\u0915\u094d\u200c\u0937\u093f\u0924\u093f\u091c",      # Kshitij with ZWNJ (half form kept apart)
    "\u091c\u094d\u091e\u093e\u0928\u0947\u0936\u094d\u0935\u0930",   # Dnyaneshwar (Marathi, no joiner)
    "\u0d38\u0d02\u0d17\u0d40\u0d24\u0d4d\u200c",            # Malayalam: ZWNJ at the end is dropped (no next letter)
])
def test_indic_names_keep_their_joiners(name):
    expected = name.rstrip("\u200c")
    assert clean_name(name) == expected
    assert clean_name(f"  {name} ") == expected


def test_joiners_outside_a_script_or_emoji_are_dropped():
    assert clean_name("Ma\u200dya") == "Maya"                                    # between Latin letters
    assert clean_name("A\u200d\u0915") == "A\u0915"                              # Latin then Devanagari
    assert clean_name("\u0915\u200d\u0b95") == "\u0915\u0b95"                    # Devanagari then Tamil
    assert clean_name("\u200d\u0915") == "\u0915"                                # nothing before it
    assert clean_name("\U0001F468\u200d\U0001F469") == "\U0001F468\u200d\U0001F469"     # emoji family kept
    assert clean_name("\U0001F3F3\ufe0f\u200d\U0001F308") == "\U0001F3F3\ufe0f\u200d\U0001F308"
    assert clean_name("\U0001F468\u200c\U0001F469") == "\U0001F468\U0001F469"     # ZWNJ never in emoji


def test_other_invisible_characters_are_still_stripped():
    for junk in ("\u200b", "\u202e", "\u2066", "\ufeff", "\u2060", "\u00ad", "\u3164", "\u115f", "\u1160",
                 "\u2800", "\u034f"):
        assert clean_name(f"Al{junk}ex") == "Alex", ascii(junk)


@pytest.mark.parametrize("blank", ["\u3164", "\u3164\u3164", "\u2800", "\u115f\u1160", "\u034f", "\u200b\u200d",
                                   "\u0301", "\u200c"])
def test_a_name_with_nothing_visible_is_refused(blank):
    with pytest.raises(DriverError, match="Please type a name"):
        clean_name(blank)


def test_names_are_nfc_and_capped_at_16_code_points_after_it():
    assert clean_name("Jose\u0301") == "Jos\u00e9"
    assert clean_name("e\u0301" * 16) == "\u00e9" * 16                             # 32 typed, 16 after NFC
    with pytest.raises(DriverError, match="at most 16"):
        clean_name("\u00e9" * 17)


def test_ipv4_mapped_visits_are_matched_as_ipv4():
    own = {"192.168.1.10"}
    assert is_this_pc("::ffff:127.0.0.1", own)
    assert is_this_pc("::ffff:192.168.1.10", own)
    assert not is_this_pc("::ffff:192.168.1.77", own)
    t = PhoneTest(None)
    assert not t.record("::ffff:192.168.1.10", own) and t.reached_at is None


def test_own_addresses_are_looked_up_once_a_minute(tmp_path, monkeypatch):
    from simtelemetry import hub as hub_mod
    from simtelemetry.core import feed
    hub = make_hub(tmp_path)
    calls = []
    monkeypatch.setattr(hub, "hub_address", lambda: "192.168.1.10")
    monkeypatch.setattr(feed, "_private_addresses", lambda: calls.append(1) or ["10.0.0.5"])
    now = [1000.0]
    monkeypatch.setattr(hub_mod.time, "monotonic", lambda: now[0])
    assert hub.own_addresses() == {"192.168.1.10", "10.0.0.5"}
    now[0] += 30
    assert hub.own_addresses() == {"192.168.1.10", "10.0.0.5"} and calls == [1]
    now[0] += 31
    hub.own_addresses()
    assert calls == [1, 1]


def test_phone_test_saves_the_latest_visit(tmp_path):
    path = tmp_path / "phone-test.json"
    now = [1000.0]
    t = PhoneTest(path, clock=lambda: now[0])
    assert t.record("192.168.1.77", {"192.168.1.10"})               # first visit: written at once

    def saved():
        return json.loads(path.read_text(encoding="utf-8"))["at"]
    assert saved() == 1_000_000
    now[0] = 1005.0
    t.record("192.168.1.77", {"192.168.1.10"})                       # within 10 s: not written yet...
    assert saved() == 1_000_000
    t.flush()                                                        # ...but the hub stopping writes it
    assert saved() == 1_005_000 and PhoneTest(path).reached_at == 1005.0
    now[0] = 1008.0
    t.record("192.168.1.77", {"192.168.1.10"})
    now[0] = 1020.0
    t.status("192.168.1.10", 8000)                                   # a later status view writes it too
    assert saved() == 1_008_000


def test_drivers_end_leaves_a_newer_session_alone(tmp_path):
    hub = make_hub(tmp_path)
    old = hub.drivers.assign(RIG, "Alex")
    new = hub.drivers.assign(RIG, "Sam")
    assert not hub.drivers.end(RIG, expected_session=old)
    assert hub.drivers.get(RIG) is new
    assert hub.drivers.end(RIG, expected_session=new) and hub.drivers.get(RIG) is None


def test_staff_start_holds_the_end_lock(tmp_path, monkeypatch):
    import threading
    hub = staff_ready(make_hub(tmp_path))
    hub.registry.see(RIG, 0.0, None, None)
    client = _app(hub, tmp_path, headers=STAFF)
    real = hub.drivers.assign
    seen = {}

    def assign(*a, **k):
        free = []
        probe = threading.Thread(target=lambda: free.append(hub._end_lock.acquire(blocking=False)))
        probe.start()
        probe.join()
        seen["auto_end_could_run"] = free[0]
        if free[0]:
            hub._end_lock.release()
        return real(*a, **k)
    monkeypatch.setattr(hub.drivers, "assign", assign)
    r = client.put(f"/api/staff/rigs/{RIG}/driver", json={"name": "Alex"})
    assert r.status_code == 200, r.text
    assert seen == {"auto_end_could_run": False}
