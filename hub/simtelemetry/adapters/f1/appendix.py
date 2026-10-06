"""Lookup tables from the appendices of docs/F1_25_UDP_Spec.pdf.

There is no 2026 appendix, so format 2026 uses the 2025 tables; IDs not listed show as
"Track N" / "Session N". Config can override or add track names.
"""

from __future__ import annotations

from collections.abc import Mapping

TRACKS: dict[int, str] = {
    0: "Melbourne",
    2: "Shanghai",
    3: "Sakhir (Bahrain)",
    4: "Catalunya",
    5: "Monaco",
    6: "Montreal",
    7: "Silverstone",
    9: "Hungaroring",
    10: "Spa",
    11: "Monza",
    12: "Singapore",
    13: "Suzuka",
    14: "Abu Dhabi",
    15: "Texas",
    16: "Brazil",
    17: "Austria",
    19: "Mexico",
    20: "Baku (Azerbaijan)",
    26: "Zandvoort",
    27: "Imola",
    29: "Jeddah",
    30: "Miami",
    31: "Las Vegas",
    32: "Losail",
    39: "Silverstone (Reverse)",
    40: "Austria (Reverse)",
    41: "Zandvoort (Reverse)",
}

SESSION_TYPES: dict[int, str] = {
    0: "Unknown",
    1: "Practice 1",
    2: "Practice 2",
    3: "Practice 3",
    4: "Short Practice",
    5: "Qualifying 1",
    6: "Qualifying 2",
    7: "Qualifying 3",
    8: "Short Qualifying",
    9: "One-Shot Qualifying",
    10: "Sprint Shootout 1",
    11: "Sprint Shootout 2",
    12: "Sprint Shootout 3",
    13: "Short Sprint Shootout",
    14: "One-Shot Sprint Shootout",
    15: "Race",
    16: "Race 2",
    17: "Race 3",
    18: "Time Trial",
}

UNKNOWN_TRACK_ID = -1


def track_name(track_id: int, overrides: Mapping[int, str] | None = None) -> str | None:
    """Display name for a track ID; None when the game reports -1 (unknown)."""
    if overrides and track_id in overrides:
        return overrides[track_id]
    if track_id == UNKNOWN_TRACK_ID:
        return None
    return TRACKS.get(track_id, f"Track {track_id}")


def session_type_name(session_type: int) -> str:
    return SESSION_TYPES.get(session_type, f"Session {session_type}")
