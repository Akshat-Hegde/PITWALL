from pathlib import Path

import pytest

from simtelemetry.__main__ import main
from simtelemetry.config import ConfigError, load_config

from f1_helpers import DOCS

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


def test_cli_exits_with_clear_message(tmp_path, capsys):
    path = write(tmp_path, "[recorder]\nenabled = true\n")
    code = main(["listen", "--config", str(path), "--data-dir", str(tmp_path), "--duration", "0.1"])
    assert code == 2
    err = capsys.readouterr().err
    assert f"{path} [recorder]: unknown key 'enabled' (did you mean enabled_in_run / enabled_in_listen?)" in err
    assert "Traceback" not in err
    assert not (tmp_path / "logs").exists()  # failed before anything started


@pytest.mark.parametrize("text,expected", [
    ("[recorder]\nenabled_in_run = tru\n", "line 2, column 18: TOML syntax error: Invalid value"),
    ("[network\nudp_port = 20777\n",
     "line 1, column 9: TOML syntax error: Expected ']' at the end of a table declaration"),
    ('[cafe]\nname = "Unclosed', "at end of file: TOML syntax error: Unterminated string"),
])
def test_toml_syntax_error_names_file_line_and_column(tmp_path, text, expected):
    path = write(tmp_path, text)
    assert error_for(path) == f"Invalid config file {path}:\n  {path} {expected}"


def test_cli_toml_syntax_error_exits_cleanly(tmp_path, capsys):
    path = write(tmp_path, "[recorder]\nenabled_in_run = tru\n")
    code = main(["run", "--config", str(path), "--data-dir", str(tmp_path), "--duration", "0.1"])
    assert code == 2
    err = capsys.readouterr().err
    assert f"{path} line 2, column 18: TOML syntax error: Invalid value" in err
    assert "Traceback" not in err


def test_recordings_directory_option(tmp_path):
    path = write(tmp_path, '[recorder]\ndirectory = "D:/telemetry/recordings"\nwarn_free_gb = 20\nstop_free_gb = 2\n')
    config = load_config(path)
    assert config.recordings_dir == Path("D:/telemetry/recordings")
    assert (config.recorder.warn_free_gb, config.recorder.stop_free_gb) == (20, 2)
    assert load_config(write(tmp_path, "")).recordings_dir == Path("data") / "recordings"


def test_floor_above_warning_rejected(tmp_path):
    path = write(tmp_path, "[recorder]\nwarn_free_gb = 2\nstop_free_gb = 3\n")
    assert f"{path} [recorder]: 'stop_free_gb' Value error, must not be above warn_free_gb (2)" in error_for(path)
