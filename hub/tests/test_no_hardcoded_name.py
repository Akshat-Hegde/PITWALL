"""The product name is defined once, in hub/simtelemetry/brand.py. Shipped source must not type it out.

Hub pages use {{PRODUCT_NAME}}, the dashboard gets __PRODUCT_NAME__ / %PRODUCT_NAME% at build time, and the
Windows scripts ask the exe or brand.py. Comments, import lines (module paths) and brand.py itself are exempt.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCAN = ["hub/simtelemetry", "dashboard/src", "dashboard/index.html", "dashboard/public", "packaging", "tools/windows"]
EXTS = {".py", ".ts", ".tsx", ".html", ".css", ".ps1", ".cmd", ".iss", ".xml", ".svg", ".json", ".js"}
SKIP_DIRS = {"node_modules", "dist", "build", "__pycache__"}
NAME = re.compile(r"(?<![A-Za-z0-9_])(Pitwall|PITWALL)(?![A-Za-z0-9_])")
COMMENT_STARTS = ("#", "//", ";", "*", "/*", "<!--", "REM ", "REM\t", "::")
IMPORT_STARTS = ("import ", "} from ", "from ")
BRAND = ROOT / "hub" / "simtelemetry" / "brand.py"


def _files():
    for entry in SCAN:
        base = ROOT / entry
        paths = [base] if base.is_file() else base.rglob("*") if base.is_dir() else []
        for p in paths:
            if p.is_file() and p.suffix.lower() in EXTS and not SKIP_DIRS & set(p.relative_to(ROOT).parts) and p != BRAND:
                yield p


def find_hits(files=None) -> list[str]:
    hits = []
    for p in files if files is not None else _files():
        for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            s = line.strip()
            if NAME.search(line) and not s.startswith(COMMENT_STARTS) and not s.startswith(IMPORT_STARTS):
                hits.append(f"{(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p).as_posix()}:{n}: {s[:100]}")
    return hits


def test_no_hardcoded_product_name():
    hits = find_hits()
    assert not hits, "Product name typed out; use brand.py (or its placeholders):\n" + "\n".join(hits)


def test_guard_bites(tmp_path):
    bad = tmp_path / "x.ts"
    bad.write_text('const a = "Pitwall";\n// Pitwall in a comment\nimport x from "./Pitwall";\nconst b = PitwallLogo;\n',
                   encoding="utf-8")
    hits = find_hits([bad])
    assert len(hits) == 1 and "x.ts:1:" in hits[0]
