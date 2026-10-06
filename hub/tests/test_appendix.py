from simtelemetry.adapters.f1.appendix import session_type_name, track_name


def test_known_tracks():
    assert track_name(7) == "Silverstone"
    assert track_name(0) == "Melbourne"
    assert track_name(41) == "Zandvoort (Reverse)"


def test_unknown_and_missing():
    assert track_name(1) == "Track 1"     # gap in the appendix table
    assert track_name(55) == "Track 55"   # e.g. a 2026-only track
    assert track_name(-1) is None


def test_overrides():
    overrides = {7: "Silverstone GP", 55: "Madrid"}
    assert track_name(7, overrides) == "Silverstone GP"
    assert track_name(55, overrides) == "Madrid"
    assert track_name(10, overrides) == "Spa"


def test_session_types():
    assert session_type_name(18) == "Time Trial"
    assert session_type_name(99) == "Session 99"
