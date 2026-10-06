"""Guard the transcription of documented sizes against the spec files themselves."""

import re

import pytest

from simtelemetry.adapters.f1.sizes import DOCUMENTED_SIZES, MAX_CARS, PacketId

from f1_helpers import DOCS

SPEC_FILES = {
    2025: DOCS / "F1_25_structures.txt",
    2026: DOCS / "F1_2026_SeasonPack_structures.txt",
}

# Section comment name in the spec files -> packet ID.
SECTION_NAMES = {
    "Motion": PacketId.MOTION,
    "Session": PacketId.SESSION,
    "Lap": PacketId.LAP_DATA,
    "Event": PacketId.EVENT,
    "Participants": PacketId.PARTICIPANTS,
    "Car Setups": PacketId.CAR_SETUPS,
    "Car Telemetry": PacketId.CAR_TELEMETRY,
    "Car Status": PacketId.CAR_STATUS,
    "Final Classification": PacketId.FINAL_CLASSIFICATION,
    "Lobby Info": PacketId.LOBBY_INFO,
    "Car Damage": PacketId.CAR_DAMAGE,
    "Session History": PacketId.SESSION_HISTORY,
    "Tyre Sets": PacketId.TYRE_SETS,
    "Motion Ex": PacketId.MOTION_EX,
    "Time Trial": PacketId.TIME_TRIAL,
    "Lap Positions": PacketId.LAP_POSITIONS,
    "Car Telemetry 2": PacketId.CAR_TELEMETRY_2,
}

SECTION_RE = re.compile(r"^//\s+(.+?)\s+-\s+(\d+)\s+bytes\s*$", re.MULTILINE)


def spec_sizes(fmt: int) -> tuple[int, dict[PacketId, int]]:
    text = SPEC_FILES[fmt].read_text(encoding="utf-8")
    header_size = None
    sizes: dict[PacketId, int] = {}
    for name, size in SECTION_RE.findall(text):
        if name == "Header":
            header_size = int(size)
        else:
            sizes[SECTION_NAMES[name]] = int(size)
    return header_size, sizes


@pytest.mark.parametrize("fmt", [2025, 2026])
def test_table_matches_spec_file(fmt):
    header_size, sizes = spec_sizes(fmt)
    assert header_size == 29
    assert DOCUMENTED_SIZES[fmt] == sizes


@pytest.mark.parametrize("fmt", [2025, 2026])
def test_max_cars_matches_spec_file(fmt):
    text = SPEC_FILES[fmt].read_text(encoding="utf-8")
    m = re.search(r"cs_maxNumCarsInUDPData\s*=\s*(\d+)", text)
    assert int(m.group(1)) == MAX_CARS[fmt]


def test_car_telemetry_2_only_in_2026():
    assert PacketId.CAR_TELEMETRY_2 not in DOCUMENTED_SIZES[2025]
    assert PacketId.CAR_TELEMETRY_2 in DOCUMENTED_SIZES[2026]
