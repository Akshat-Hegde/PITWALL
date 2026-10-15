from pathlib import Path

import pytest

from simtelemetry.__main__ import main
from simtelemetry.config import ConfigError, load_config

from f1_helpers import DOCS
from test_cli import free_port

EXAMPLE = DOCS.parent / "config" / "hub.example.toml"


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "hub.toml"
    path.write_text(text, encoding="utf-8")
    return path


def error_for(path: Path) -> str:
    with pytest.raises(ConfigError) as exc:
        load_config(path)
    return str(exc.value)


def test_example_config_loads():
    config = load_config(EXAMPLE)
    assert config.network.udp_port == 20777
    assert config.recorder.enabled_in_run is False


def test_unknown_key_names_file_section_and_suggestions(tmp_path):
    path = write(tmp_path, "[recorder]\nenabled = true\n")
    assert error_for(path) == (
        f"Invalid config file {path}:\n"
        f"  {path} [recorder]: unknown key 'enabled' (did you mean enabled_in_run / enabled_in_listen?)"
    )


def test_misspelt_key_suggests_close_match(tmp_path):
    path = write(tmp_path, "[network]\nupd_port = 20778\n")
    assert f"{path} [network]: unknown key 'upd_port' (did you mean udp_port?)" in error_for(path)


def test_unknown_top_level_key_and_section(tmp_path):
    path = write(tmp_path, 'data_dirr = "x"\n[recordr]\nenabled_in_run = true\n')
    message = error_for(path)
    assert f"{path}: unknown key 'data_dirr' (did you mean data_dir?)" in message
    assert f"{path}: unknown key 'recordr' (did you mean recorder?)" in message


def test_unknown_key_in_rig_entry(tmp_path):
    path = write(tmp_path, '[[rigs]]\nip = "10.0.0.1"\n\n[[rigs]]\nip = "10.0.0.2"\nnmae = "Rig B"\n')
    assert f"{path} [[rigs]] #2: unknown key 'nmae' (did you mean name?)" in error_for(path)


def test_unknown_key_without_suggestion(tmp_path):
    path = write(tmp_path, "[health]\nbanana = 1\n")
    assert error_for(path).endswith(f"{path} [health]: unknown key 'banana'")


def test_wrong_type_is_reported_too(tmp_path):
    path = write(tmp_path, '[network]\nudp_port = "twenty"\n')
    assert f"{path} [network]: 'udp_port'" in error_for(path)


def test_free_form_tables_still_accept_any_key(tmp_path):
    path = write(tmp_path, '[cafe.branding]\n"--brand-accent" = "#e10600"\n[track_names]\n"7" = "Silverstone GP"\n')
    config = load_config(path)
    assert config.cafe.branding == {"--brand-accent": "#e10600"}
    assert config.track_names == {7: "Silverstone GP"}


def test_cli_unknown_key_is_a_warning_not_a_refusal(tmp_path, capsys):
    """K1: unknown keys never stop the hub; they are logged (console and hub.log) and ignored."""
    path = write(tmp_path, "[recorder]\nenabled = true\n")
    code = main(["listen", "--config", str(path), "--data-dir", str(tmp_path), "--port", str(free_port()),
                 "--duration", "0.1"])
    assert code == 0
    err = capsys.readouterr().err
    expected = f"{path} [recorder]: unknown key 'enabled' (did you mean enabled_in_run / enabled_in_listen?) (line 2)"
    assert expected in err and "Traceback" not in err
    assert expected in (tmp_path / "logs" / "hub.log").read_text(encoding="utf-8")


@pytest.mark.parametrize("text,expected", [
    ("[recorder]\nenabled_in_run = tru\n", "line 2, column 18: TOML syntax error: Invalid value"),
    ("[network\nudp_port = 20777\n",
     "line 1, column 9: TOML syntax error: Expected ']' at the end of a table declaration"),
    ('[cafe]\nname = "Unclosed', "at end of file: TOML syntax error: Unterminated string"),
])
def test_toml_syntax_error_names_file_line_and_column(tmp_path, text, expected):
    path = write(tmp_path, text)
    assert error_for(path) == f"Invalid config file {path}:\n  {path} {expected}"


def test_cli_toml_syntax_error_starts_with_defaults(tmp_path, capsys):
    path = write(tmp_path, "[recorder]\nenabled_in_run = tru\n")
    code = main(["listen", "--config", str(path), "--data-dir", str(tmp_path), "--port", str(free_port()),
                 "--duration", "0.1"])
    assert code == 0
    err = capsys.readouterr().err
    assert f"{path} line 2, column 18: TOML syntax error: Invalid value" in err
    assert "Traceback" not in err


def test_recordings_directory_option(tmp_path, monkeypatch):
    monkeypatch.setenv("PITWALL_HOME", str(tmp_path))
    path = write(tmp_path, '[recorder]\ndirectory = "D:/telemetry/recordings"\nwarn_free_gb = 20\nstop_free_gb = 2\n')
    config = load_config(path)
    assert config.recordings_dir == Path("D:/telemetry/recordings")
    assert (config.recorder.warn_free_gb, config.recorder.stop_free_gb) == (20, 2)
    assert load_config(write(tmp_path, "")).recordings_dir == tmp_path / "data" / "recordings"


def test_floor_above_warning_rejected(tmp_path):
    path = write(tmp_path, "[recorder]\nwarn_free_gb = 2\nstop_free_gb = 3\n")
    assert f"{path} [recorder]: 'stop_free_gb' Value error, must not be above warn_free_gb (2)" in error_for(path)


# --- K1: load_config_safe never refuses -------------------------------------------------------------------

from simtelemetry.config import load_config_safe  # noqa: E402


def test_safe_unknown_key_is_ignored_and_the_rest_applies(tmp_path):
    path = write(tmp_path, "[network]\nhttp_port = 8123\nupd_port = 20778\n")
    config, problems = load_config_safe(path)
    assert config.network.http_port == 8123 and config.network.udp_port == 20777
    (p,) = problems
    assert p.message == ("Your settings file (hub.toml) has a setting the hub doesn't know on line 3: 'upd_port' "
                         "(did you mean udp_port?). It was ignored.")
    assert f"{path} [network]: unknown key 'upd_port' (did you mean udp_port?) (line 3)" == p.detail


def test_safe_bad_value_uses_that_default_and_keeps_the_rest(tmp_path):
    path = write(tmp_path, 'data_dir = "D:/cafe"\n[network]\nudp_port = "twenty"\nhttp_port = 8123\n')
    config, problems = load_config_safe(path)
    assert config.data_dir == Path("D:/cafe")                 # a custom data folder is never lost to a typo
    assert config.network.http_port == 8123 and config.network.udp_port == 20777
    (p,) = problems
    assert p.message.startswith("Your settings file (hub.toml) has a mistake on line 3: 'udp_port' ")
    assert p.message.endswith("The hub started with the default for that setting.")


def test_safe_syntax_error_starts_with_defaults_and_names_the_line(tmp_path):
    path = write(tmp_path, "[network]\nhttp_port = 8123\n[recorder]\nenabled_in_run = tru\n")
    config, problems = load_config_safe(path)
    assert config.network.http_port == 8000
    (p,) = problems
    assert p.message == ("Your settings file (hub.toml) has a mistake on line 4: Invalid value. "
                         "The hub started with default settings.")
    assert "line 4, column 18: TOML syntax error" in p.detail


def test_safe_several_problems_and_rig_entries(tmp_path):
    path = write(tmp_path, '[[rigs]]\nip = "10.0.0.1"\n\n[[rigs]]\nip = "10.0.0.2"\nnmae = "Rig B"\n'
                           '[[rigs]]\nname = "no address"\n[owner]\nopen_hour = 20\nclose_hour = 10\n'
                           '[track_names]\nabc = "x"\n7 = "Silverstone GP"\n')
    config, problems = load_config_safe(path)
    assert [r.ip for r in config.rigs] == ["10.0.0.1", "10.0.0.2"]
    assert config.owner.close_hour == 22 and config.track_names == {7: "Silverstone GP"}
    text = "\n".join(p.message for p in problems)
    assert "line 6: 'nmae' (did you mean name?)" in text
    assert "'ip' in [[rigs]] #3 is missing" in text
    assert "line 11: 'close_hour' must be after open_hour (20)" in text
    assert "line 13: 'abc' should be a whole number" in text


def test_safe_missing_or_unreadable_file(tmp_path, monkeypatch):
    monkeypatch.setenv("PITWALL_HOME", str(tmp_path))
    config, problems = load_config_safe(None)
    assert problems == [] and config.data_dir == tmp_path / "data"
    bad = tmp_path / "hub.toml"
    bad.write_bytes(b"\xff\xfe\x00garbage")
    config, problems = load_config_safe(bad)
    assert config.network.http_port == 8000 and "could not be read" in problems[0].message


def test_example_config_has_no_problems():
    assert load_config_safe(EXAMPLE)[1] == []


@pytest.mark.parametrize("line, phrase", [
    ("[network]\nudp_port = \"twenty\"\n", "'udp_port' should be a whole number"),
    ("[network]\nudp_port = 70000\n", "'udp_port' should be 65535 or less"),
    ("[leaderboard]\nday_start_hour = -1\n", "'day_start_hour' should be 0 or more"),
    ("[dashboard]\nframe_hz = 50\n", "'frame_hz' should be 20 or less"),
    ("[recorder]\nenabled_in_run = \"maybe\"\n", "'enabled_in_run' should be true or false"),
    ("[cafe]\nname = 12\n", "'name' should be text in quotes"),
])
def test_safe_mistakes_are_described_in_plain_words(tmp_path, line, phrase):
    _, problems = load_config_safe(write(tmp_path, line))
    (p,) = problems
    assert f"on line 2: {phrase}. The hub started with the default" in p.message
    assert "Input should" not in p.message and "valid integer" not in p.message


def test_pins_written_as_numbers_are_read_as_text(tmp_path):
    config, problems = load_config_safe(write(tmp_path, "[owner]\npin = 2468\n[staff]\npin = 1357\n"))
    assert problems == [] and config.owner.pin == "2468" and config.staff.pin == "1357"
    _, problems = load_config_safe(write(tmp_path, "[owner]\npin = true\n"))
    assert "'pin' should be text in quotes" in problems[0].message


def test_problems_say_which_key_they_touch(tmp_path):
    _, problems = load_config_safe(write(tmp_path, "data_dir = 5\n[backup]\nkeep = 0\n"))
    assert [p.loc for p in problems] == [("data_dir",), ("backup", "keep")]
    assert problems[0].touches(("data_dir",)) and not problems[1].touches(("data_dir",))
    _, problems = load_config_safe(write(tmp_path, "[network\n"))
    assert problems[0].whole_file and problems[0].touches(("data_dir",))
