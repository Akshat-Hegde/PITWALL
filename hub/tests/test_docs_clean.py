"""Tracked text docs/scripts must not contain stray control characters
(e.g. a backspace from a mangled ``\b`` in a Windows path)."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXTS = (".md", ".toml", ".txt", ".ps1", ".iss")
ALLOWED = {9, 10, 13}


def test_no_control_characters():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True)
    if out.returncode != 0:
        import pytest
        pytest.skip("not a git checkout")
    bad = []
    for rel in out.stdout.splitlines():
        if not rel.endswith(EXTS) or not (ROOT / rel).is_file():
            continue
        data = (ROOT / rel).read_bytes()
        for n, line in enumerate(data.split(b"\n"), 1):
            # A CR is only allowed as the CRLF line ending; a lone CR is a mangled "\r" (e.g. data\recordings).
            body = line[:-1] if line.endswith(b"\r") else line
            if any(c < 32 and c not in ALLOWED for c in line) or b"\r" in body:
                bad.append(f"{rel}:{n}")
    assert not bad, "control characters in: " + ", ".join(bad)
