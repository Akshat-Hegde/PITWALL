"""The one-time setup code: only the person who ran the installer can claim first-run setup."""

from __future__ import annotations

import pytest

from simtelemetry.core.setup_code import LOCK_S, MAX_TRIES, SetupCode, SetupLocked


def test_new_code_shape_and_persistence(tmp_path):
    code = SetupCode(tmp_path).new()
    assert len(code) == 9 and code[4] == "-" and code.replace("-", "").isalnum()
    assert SetupCode(tmp_path).current() == code
    assert SetupCode(tmp_path).ensure() == code                  # ensure keeps an existing code


def test_check_is_forgiving_about_format(tmp_path):
    sc = SetupCode(tmp_path)
    code = sc.new()
    assert sc.check(code.lower().replace("-", " "))
    assert not sc.check("AAAA-AAAA") and not sc.check(None) and not sc.check("")


def test_lockout_after_too_many_wrong_codes(tmp_path):
    now = [1000.0]
    sc = SetupCode(tmp_path, clock=lambda: now[0])
    code = sc.new()
    for _ in range(MAX_TRIES):
        assert not sc.check("WRONG-CODE")
    with pytest.raises(SetupLocked):
        sc.check(code)                                            # even the right code waits out the lock
    now[0] += LOCK_S + 1
    assert sc.check(code)


def test_clear(tmp_path):
    sc = SetupCode(tmp_path)
    sc.new()
    sc.clear()
    assert sc.current() is None and not (tmp_path / "setup-code.txt").exists()
