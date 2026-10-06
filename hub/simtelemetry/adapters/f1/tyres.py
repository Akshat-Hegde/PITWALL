"""Tyre compound codes from the CarStatusData comments (identical in 2025 and 2026).

m_actualTyreCompound:
    F1 Modern - 16 = C5, 17 = C4, 18 = C3, 19 = C2, 20 = C1, 21 = C0, 22 = C6, 7 = inter, 8 = wet
    F1 Classic - 9 = dry, 10 = wet
    F2 - 11 = super soft, 12 = soft, 13 = medium, 14 = hard, 15 = wet
m_visualTyreCompound:
    16 = soft, 17 = medium, 18 = hard, 7 = inter, 8 = wet
    F1 Classic - same as above
    F2 '20, 15 = wet, 19 - super soft, 20 = soft, 21 = medium, 22 = hard
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Compound(str, Enum):
    C0 = "C0"
    C1 = "C1"
    C2 = "C2"
    C3 = "C3"
    C4 = "C4"
    C5 = "C5"
    C6 = "C6"
    SUPER_SOFT = "super_soft"
    SOFT = "soft"
    MEDIUM = "medium"
    HARD = "hard"
    DRY = "dry"
    INTER = "inter"
    WET = "wet"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class TyreCompound:
    compound: Compound
    raw: int

    @property
    def label(self) -> str:
        if self.compound is Compound.UNKNOWN:
            return f"unknown({self.raw})"
        return self.compound.value

    def __str__(self) -> str:
        return self.label


_ACTUAL: dict[int, Compound] = {
    16: Compound.C5, 17: Compound.C4, 18: Compound.C3, 19: Compound.C2,
    20: Compound.C1, 21: Compound.C0, 22: Compound.C6,
    7: Compound.INTER, 8: Compound.WET,
    9: Compound.DRY, 10: Compound.WET,
    11: Compound.SUPER_SOFT, 12: Compound.SOFT, 13: Compound.MEDIUM, 14: Compound.HARD, 15: Compound.WET,
}

_VISUAL: dict[int, Compound] = {
    16: Compound.SOFT, 17: Compound.MEDIUM, 18: Compound.HARD, 7: Compound.INTER, 8: Compound.WET,
    15: Compound.WET, 19: Compound.SUPER_SOFT, 20: Compound.SOFT, 21: Compound.MEDIUM, 22: Compound.HARD,
}


def actual_compound(code: int) -> TyreCompound:
    return TyreCompound(_ACTUAL.get(code, Compound.UNKNOWN), code)


def visual_compound(code: int) -> TyreCompound:
    return TyreCompound(_VISUAL.get(code, Compound.UNKNOWN), code)
