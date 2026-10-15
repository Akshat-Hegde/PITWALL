"""Owner-editable settings: kept in data/settings.json, layered over hub.toml."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from simtelemetry.config import AppConfig
from simtelemetry.core.settings import CafeSettings, SettingsStore, apply_settings
from simtelemetry.core.pins import verify_pin


def test_round_trip_and_apply(tmp_path):
    store = SettingsStore(tmp_path)
    assert store.load() is None
    s = CafeSettings(name="Lap Lab", tagline="Beat the board", accent="#FF2A6D", owner_pin="2468",
                     staff_pin="1357", open_hour=11, close_hour=23, setup_done=True)
    store.save(s)
    again = SettingsStore(tmp_path).load()
    assert again == s
    config = AppConfig(data_dir=tmp_path)
    apply_settings(config, again)
    assert (config.cafe.name, config.cafe.tagline, config.cafe.branding["--brand-accent"]) == \
        ("Lap Lab", "Beat the board", "#FF2A6D")
    assert verify_pin("2468", config.owner.pin) and verify_pin("1357", config.staff.pin)
    assert (config.owner.open_hour, config.owner.close_hour) == (11, 23)


@pytest.mark.parametrize("bad", [{"accent": "red"}, {"owner_pin": "12"}, {"name": ""},
                                 {"open_hour": 20, "close_hour": 10}, {"name": "x" * 41}])
def test_rejects_bad_values(bad):
    with pytest.raises(ValidationError):
        CafeSettings(**{"name": "Lap Lab", "owner_pin": "2468", **bad})


def test_corrupt_file_is_ignored_not_fatal(tmp_path):
    (tmp_path / "settings.json").write_text("{nope", encoding="utf-8")
    assert SettingsStore(tmp_path).load() is None


# --- stored PINs are hashed -----------------------------------------------------------------------------

def test_pins_are_stored_hashed_never_in_plain_text(tmp_path):
    store = SettingsStore(tmp_path)
    store.save(CafeSettings(name="Lap Lab", owner_pin="2468", staff_pin="1357"))
    text = (tmp_path / "settings.json").read_text(encoding="utf-8")
    assert "2468" not in text and "1357" not in text and "scrypt$" in text
    s = store.load()
    assert verify_pin("2468", s.owner_pin) and not verify_pin("2469", s.owner_pin)
    assert verify_pin("1357", s.staff_pin) and not verify_pin("2468", s.staff_pin)


def test_same_pin_gets_a_different_salt():
    a = CafeSettings(name="A", owner_pin="2468")
    b = CafeSettings(name="A", owner_pin="2468")
    assert a.owner_pin != b.owner_pin and verify_pin("2468", a.owner_pin) and verify_pin("2468", b.owner_pin)


def test_plain_text_pins_from_an_old_install_are_migrated_on_load(tmp_path):
    import json
    (tmp_path / "settings.json").write_text(json.dumps(
        {"name": "Lap Lab", "owner_pin": "2468", "staff_pin": "1357", "setup_done": True}), encoding="utf-8")
    s = SettingsStore(tmp_path).load()
    assert verify_pin("2468", s.owner_pin) and verify_pin("1357", s.staff_pin)
    text = (tmp_path / "settings.json").read_text(encoding="utf-8")
    assert "2468" not in text and "1357" not in text            # rewritten at once
    assert verify_pin("2468", SettingsStore(tmp_path).load().owner_pin)


def test_empty_staff_pin_stays_empty_and_matches_nothing(tmp_path):
    s = CafeSettings(name="Lap Lab", owner_pin="2468")
    assert s.staff_pin == "" and not verify_pin("", s.staff_pin) and not verify_pin("1234", s.staff_pin)


def test_plain_pins_from_hub_toml_still_verify():
    assert verify_pin("0000", "0000") and not verify_pin("0001", "0000") and not verify_pin("", "0000")


def test_damaged_hash_never_matches():
    assert not verify_pin("2468", "scrypt$nonsense") and not verify_pin("2468", "scrypt$1$2$3$zz$zz")


def test_read_raises_on_a_damaged_file(tmp_path):
    from simtelemetry.core.settings import SettingsDamaged
    (tmp_path / "settings.json").write_text("{nope", encoding="utf-8")
    with pytest.raises(SettingsDamaged):
        SettingsStore(tmp_path).read()
    assert SettingsStore(tmp_path / "missing").read() is None
