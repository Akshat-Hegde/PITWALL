"""Every layout must match the C structs in the spec files, and every decoded packet's
computed size must equal its documented size."""

import re
from math import prod
from pathlib import Path

import pytest

from simtelemetry.adapters.f1.formats import FORMATS
from simtelemetry.adapters.f1.layout import Layout, Union
from simtelemetry.adapters.f1.sizes import DOCUMENTED_SIZES

from f1_helpers import DOCS

SPEC_FILES = {
    2025: DOCS / "F1_25_structures.txt",
    2026: DOCS / "F1_2026_SeasonPack_structures.txt",
}


class Spec:
    """Minimal parser for the struct/union definitions in the spec .txt files."""

    def __init__(self, path: Path) -> None:
        text = re.sub(r"//[^\n]*", "", path.read_text(encoding="utf-8"))
        self.consts: dict[str, int] = {}
        for name, expr in re.findall(r"static\s+const\s+\w+\s+(cs_\w+)\s*=\s*([^;]+);", text):
            self.consts[name] = sum(self._term(t) for t in expr.split("+"))
        self.structs: dict[str, list[tuple[str, str, int]]] = {}
        for name, body in re.findall(r"\bstruct\s+(\w+)\s*\{([^{}]*)\}\s*;", text):
            self.structs[name] = self._fields(body)
        for body, name in re.findall(r"\bstruct\s*\{([^{}]*)\}\s*(\w+)\s*;", text):
            self.structs[name] = self._fields(body)
        self.unions: dict[str, set[str]] = {
            name: set(re.findall(r"\}\s*(\w+)\s*;", body))
            for name, body in re.findall(r"\bunion\s+(\w+)\s*\{(.*?)\n\};", text, re.S)
        }

    def _term(self, token: str) -> int:
        token = token.strip()
        return int(token) if token.isdigit() else self.consts[token]

    def _fields(self, body: str) -> list[tuple[str, str, int]]:
        out = []
        for stmt in body.split(";"):
            stmt = " ".join(stmt.split())
            if not stmt or stmt.startswith("static"):
                continue
            m = re.fullmatch(r"(\w+) (\w+) ?((?:\[[^\]]+\] ?)*)", stmt)
            assert m, f"unparsed statement: {stmt!r}"
            type_name = m[1][2:] if m[1].startswith("NE") else m[1]  # NEuint8 -> uint8
            count = prod(self._term(d) for d in re.findall(r"\[([^\]]+)\]", m[3]))
            out.append((type_name, m[2], count))
        return out


def assert_matches_spec(layout: Layout, spec: Spec, path: str = "") -> None:
    where = f"{path}{layout.name}"
    assert layout.name in spec.structs, f"{where}: no such struct in spec"
    mine = [(f.type_name, f.name, f.count) for f in layout.fields]
    assert mine == spec.structs[layout.name], f"{where} differs from spec"
    for f in layout.fields:
        if isinstance(f.type, Layout):
            assert_matches_spec(f.type, spec, f"{where}.")
        elif isinstance(f.type, Union):
            assert set(f.type.members) == spec.unions[f.type.name], f"{where}.{f.name} union members differ"
            for member in f.type.members.values():
                assert_matches_spec(member, spec, f"{where}.{f.type.name}.")


@pytest.mark.parametrize("fmt", [2025, 2026])
def test_layouts_match_spec_file(fmt):
    spec = Spec(SPEC_FILES[fmt])
    for layout in FORMATS[fmt].packets.values():
        assert_matches_spec(layout, spec)


@pytest.mark.parametrize("fmt,pid", [(fmt, pid) for fmt, f in FORMATS.items() for pid in f.packets])
def test_computed_size_equals_documented(fmt, pid):
    assert FORMATS[fmt].packets[pid].size == DOCUMENTED_SIZES[fmt][pid]


@pytest.mark.parametrize("fmt", [2025, 2026])
def test_max_cars_matches_layouts(fmt):
    layouts = FORMATS[fmt]
    motion = layouts.packets[0]
    assert motion.size == 29 + layouts.max_cars * layouts.car_motion.size


def test_spec_parser_sees_known_differences():
    # Sanity check that the parser reads real content, using differences listed in the plan.
    s25, s26 = Spec(SPEC_FILES[2025]), Spec(SPEC_FILES[2026])
    assert ("float", "m_gForceLateral", 1) in s25.structs["CarMotionData"]
    assert ("int16", "m_gForceLateral", 1) in s26.structs["CarMotionData"]
    assert ("uint16", "m_engineTemperature", 1) in s25.structs["CarTelemetryData"]
    assert ("uint8", "m_engineTemperature", 1) in s26.structs["CarTelemetryData"]
    assert ("uint8", "severity", 1) in s26.structs["Collision"]
    assert s25.consts["cs_maxNumTyreSets"] == 20
