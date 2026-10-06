import pytest

from simtelemetry.adapters.f1.tyres import Compound, actual_compound, visual_compound


@pytest.mark.parametrize("code,expected", [
    (16, Compound.C5), (17, Compound.C4), (18, Compound.C3), (19, Compound.C2),
    (20, Compound.C1), (21, Compound.C0), (22, Compound.C6), (7, Compound.INTER), (8, Compound.WET),
    (9, Compound.DRY), (10, Compound.WET),
    (11, Compound.SUPER_SOFT), (12, Compound.SOFT), (13, Compound.MEDIUM), (14, Compound.HARD), (15, Compound.WET),
])
def test_actual(code, expected):
    t = actual_compound(code)
    assert t.compound is expected and t.raw == code and t.label == expected.value


@pytest.mark.parametrize("code,expected", [
    (16, Compound.SOFT), (17, Compound.MEDIUM), (18, Compound.HARD), (7, Compound.INTER), (8, Compound.WET),
    (15, Compound.WET), (19, Compound.SUPER_SOFT), (20, Compound.SOFT), (21, Compound.MEDIUM), (22, Compound.HARD),
])
def test_visual(code, expected):
    assert visual_compound(code).compound is expected


@pytest.mark.parametrize("code", [0, 1, 6, 23, 255])
def test_unknown_kept_not_raised(code):
    assert actual_compound(code).label == f"unknown({code})"
    assert visual_compound(code).label == f"unknown({code})"
