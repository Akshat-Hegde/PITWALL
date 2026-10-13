"""Owner-editable settings: kept in data/settings.json, layered over hub.toml."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from simtelemetry.config import AppConfig
from simtelemetry.core.settings import CafeSettings, SettingsStore, apply_settings


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
    assert (config.owner.pin, config.staff.pin, config.owner.open_hour, config.owner.close_hour) == \
        ("2468", "1357", 11, 23)


@pytest.mark.parametrize("bad", [{"accent": "red"}, {"owner_pin": "12"}, {"name": ""},
                                 {"open_hour": 20, "close_hour": 10}, {"name": "x" * 41}])
def test_rejects_bad_values(bad):
    with pytest.raises(ValidationError):
        CafeSettings(**{"name": "Lap Lab", "owner_pin": "2468", **bad})


def test_corrupt_file_is_ignored_not_fatal(tmp_path):
    (tmp_path / "settings.json").write_text("{nope", encoding="utf-8")
    assert SettingsStore(tmp_path).load() is None
