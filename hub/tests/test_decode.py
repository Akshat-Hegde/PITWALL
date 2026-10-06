"""Decoder tests. Packets are built with hand-written struct formats and offsets (not the
layout module), and every other car slot holds decoy values so a wrong index shows up."""

import struct

import pytest

from simtelemetry.adapters.f1.decode import decode_name
from simtelemetry.adapters.f1.packets import (
    CarStatus,
    CarTelemetry,
    Event,
    FastestLapDetails,
    FlashbackDetails,
    LapData,
    Motion,
    NoPlayerCar,
    Participant,
    Session,
    SessionHistory,
    TimeTrial,
)
from simtelemetry.adapters.f1.tyres import Compound

from f1_helpers import blank_packet, decode_packet

HDR = 29
CARS = {2025: 22, 2026: 24}
BOTH = pytest.mark.parametrize("fmt", [2025, 2026])


def fill_cars(pkt: bytearray, fmt_str: str, stride: int, n: int, player: int, player_vals, decoy_vals) -> None:
    assert struct.calcsize(fmt_str) == stride
    for i in range(n):
        struct.pack_into(fmt_str, pkt, HDR + i * stride, *(player_vals if i == player else decoy_vals))


# --- playerCarIndex guard ------------------------------------------------------

PER_CAR_IDS = [0, 2, 4, 6, 7, 11]


@BOTH
@pytest.mark.parametrize("pid", PER_CAR_IDS)
@pytest.mark.parametrize("bad_index", ["255", "max_cars", "max_cars+1"])
def test_bad_player_index_gives_no_player_car(fmt, pid, bad_index):
    idx = {"255": 255, "max_cars": CARS[fmt], "max_cars+1": CARS[fmt] + 1}[bad_index]
    result = decode_packet(blank_packet(fmt, pid, player=idx))
    assert isinstance(result, NoPlayerCar)
    assert result.packet_id == pid


def test_index_22_and_23_valid_only_in_2026():
    assert isinstance(decode_packet(blank_packet(2025, 0, player=23)), NoPlayerCar)
    assert isinstance(decode_packet(blank_packet(2026, 0, player=23)), Motion)


# --- Motion (0) ----------------------------------------------------------------

MOTION = {2025: ("<6f6h3f3f", 60), 2026: ("<6f6h3h3f", 54)}


@BOTH
@pytest.mark.parametrize("player", [0, 3, "last"])
def test_motion(fmt, player):
    player = CARS[fmt] - 1 if player == "last" else player
    f, stride = MOTION[fmt]
    g = (1.25, -2.5, 0.75) if fmt == 2025 else (1250, -2500, 750)
    vals = (100.5, 2.25, -300.75, 50.0, 0.5, -10.0,
            32767, 0, -16384, 0, 32767, -32767, *g, 0.1, -0.2, 0.3)
    decoy = (9999.0,) * 6 + (1,) * 6 + ((9.0,) * 3 if fmt == 2025 else (9000,) * 3) + (9.0,) * 3
    pkt = blank_packet(fmt, 0, player=player)
    fill_cars(pkt, f, stride, CARS[fmt], player, vals, decoy)

    m = decode_packet(pkt)
    assert isinstance(m, Motion)
    assert m.position == (100.5, 2.25, -300.75)
    assert m.velocity == (50.0, 0.5, -10.0)
    assert m.forward_dir == (1.0, 0.0, -16384 / 32767.0)
    assert m.right_dir == (0.0, 1.0, -1.0)
    assert m.g_force_lateral == pytest.approx(1.25)
    assert m.g_force_longitudinal == pytest.approx(-2.5)
    assert m.g_force_vertical == pytest.approx(0.75)
    assert (m.yaw, m.pitch, m.roll) == pytest.approx((0.1, -0.2, 0.3))


# --- Session (1) ---------------------------------------------------------------
# Offsets hand-computed from the struct; identical in both formats (2026 only appends).

@BOTH
def test_session(fmt):
    pkt = blank_packet(fmt, 1, player=255)  # session is not per-car: no player needed
    pkt[HDR + 0] = 1                                    # weather
    struct.pack_into("<bbB", pkt, 30, 35, 22, 3)        # track temp, air temp, total laps
    struct.pack_into("<HBbB", pkt, 33, 5793, 18, 7, 0)  # track length, session type, track id, formula
    struct.pack_into("<HH", pkt, 38, 1200, 3600)        # time left, duration
    pkt[43], pkt[44], pkt[45] = 0, 0, 255               # paused, spectating, spectator idx
    pkt[154] = 0                                        # network game
    pkt[694], pkt[695] = 5, 2                           # game mode (Time Trial), rule set (Time Trial)
    struct.pack_into("<ff", pkt, 745, 1820.5, 3995.25)  # sector 2/3 start distances

    s = decode_packet(pkt)
    assert isinstance(s, Session)
    assert (s.weather, s.track_temperature, s.air_temperature, s.total_laps) == (1, 35, 22, 3)
    assert (s.track_length, s.session_type, s.track_id, s.formula) == (5793, 18, 7, 0)
    assert (s.session_time_left, s.session_duration) == (1200, 3600)
    assert not s.game_paused and not s.is_spectating and s.spectator_car_index == 255
    assert (s.game_mode, s.rule_set) == (5, 2)
    assert (s.sector2_lap_distance_start, s.sector3_lap_distance_start) == (1820.5, 3995.25)


@BOTH
def test_session_unknown_track_is_minus_one(fmt):
    pkt = blank_packet(fmt, 1)
    struct.pack_into("<b", pkt, 36, -1)
    assert decode_packet(pkt).track_id == -1


# --- Lap Data (2) --------------------------------------------------------------

LAP_FMT, LAP_STRIDE = "<IIHBHBHBHBfffBBBBBBBBBBBBBBBHHBfB", 57


def lap_vals(**kw):
    v = dict(last=0, current=0, s1ms=0, s1min=0, s2ms=0, s2min=0, dfms=0, dfmin=0, dlms=0, dlmin=0,
             dist=0.0, total=0.0, sc=0.0, pos=1, lap=1, pit=0, pits=0, sector=0, invalid=0,
             pen=0, warn=0, ccw=0, dt=0, sg=0, grid=0, status=4, result=2, plt=0, pltime=0,
             pstime=0, serve=0, trap=0.0, traplap=255)
    v.update(kw)
    return tuple(v.values())


@BOTH
def test_lap_data(fmt):
    player = 5
    pkt = blank_packet(fmt, 2, player=player)
    vals = lap_vals(last=92345, current=41234, s1ms=23456, s1min=1, s2ms=30123, s2min=0,
                    dfms=500, dfmin=2, dist=1234.5, total=9876.25, pos=1, lap=4, sector=1,
                    invalid=1, status=1)
    decoy = lap_vals(last=1, current=1, s1ms=1, s1min=9, dist=1.0, lap=99, invalid=0)
    fill_cars(pkt, LAP_FMT, LAP_STRIDE, CARS[fmt], player, vals, decoy)
    trailer = HDR + CARS[fmt] * LAP_STRIDE
    pkt[trailer], pkt[trailer + 1] = 20, 255

    lap = decode_packet(pkt)
    assert isinstance(lap, LapData)
    assert lap.last_lap_time_ms == 92345
    assert lap.current_lap_time_ms == 41234
    assert lap.sector1_time_ms == 60000 + 23456
    assert lap.sector2_time_ms == 30123
    assert lap.delta_to_car_in_front_ms == 2 * 60000 + 500
    assert lap.lap_distance == 1234.5
    assert lap.total_distance == 9876.25
    assert (lap.current_lap_num, lap.sector, lap.driver_status) == (4, 1, 1)
    assert lap.current_lap_invalid is True
    assert (lap.time_trial_pb_car_idx, lap.time_trial_rival_car_idx) == (20, 255)


@BOTH
def test_lap_distance_negative_is_kept(fmt):
    pkt = blank_packet(fmt, 2, player=0)
    fill_cars(pkt, LAP_FMT, LAP_STRIDE, CARS[fmt], 0, lap_vals(dist=-152.75, total=-152.75), lap_vals())
    lap = decode_packet(pkt)
    assert lap.lap_distance == -152.75
    assert lap.total_distance == -152.75


# --- Event (3) -----------------------------------------------------------------

def event_packet(fmt, code: bytes, details: bytes = b"") -> bytearray:
    pkt = blank_packet(fmt, 3)
    pkt[29:33] = code
    pkt[33:33 + len(details)] = details
    return pkt


@BOTH
@pytest.mark.parametrize("code", [b"SSTA", b"SEND"])
def test_event_session_start_end(fmt, code):
    e = decode_packet(event_packet(fmt, code, b"\xff" * 12))
    assert isinstance(e, Event)
    assert e.code == code.decode()
    assert e.details is None


@BOTH
def test_event_fastest_lap(fmt):
    e = decode_packet(event_packet(fmt, b"FTLP", struct.pack("<Bf", 3, 83.456)))
    assert e.details == FastestLapDetails(vehicle_idx=3, lap_time_s=pytest.approx(83.456))


@BOTH
def test_event_flashback(fmt):
    e = decode_packet(event_packet(fmt, b"FLBK", struct.pack("<If", 12345, 67.5)))
    assert e.details == FlashbackDetails(frame_identifier=12345, session_time=67.5)


@BOTH
@pytest.mark.parametrize("code", [b"COLL", b"SPTP", b"BUTN", b"PENA"])
def test_event_other_codes_details_ignored(fmt, code):
    e = decode_packet(event_packet(fmt, code, b"\x07" * 12))
    assert e.code == code.decode()
    assert e.details is None


# --- Participants (4) ----------------------------------------------------------

PART = {2025: ("<BBBBBBB32sBBHBB12B", 57), 2026: ("<BHHHBBB32sBBHBB12B", 60)}


def participant_packet(fmt, player, name: bytes, driver_id=9, network_id=0, team_id=2):
    f, stride = PART[fmt]
    pkt = blank_packet(fmt, 4, player=player)
    pkt[HDR] = 2  # m_numActiveCars
    vals = (0, driver_id, network_id, team_id, 0, 33, 10, name, 1, 1, 0, 1, 1, *range(12))
    decoy = (1, 1, 1, 1, 1, 1, 1, b"Decoy", 0, 0, 0, 0, 0, *([0] * 12))
    for i in range(CARS[fmt]):
        struct.pack_into(f, pkt, HDR + 1 + i * stride, *(vals if i == player else decoy))
    return pkt


@BOTH
def test_participant(fmt):
    p = decode_packet(participant_packet(fmt, 1, b"Akshat"))
    assert isinstance(p, Participant)
    assert p.name == "Akshat"
    assert p.num_active_cars == 2
    assert (p.driver_id, p.team_id, p.race_number, p.nationality) == (9, 2, 33, 10)
    assert p.ai_controlled is False
    assert p.your_telemetry_public is True
    assert p.platform == 1


def test_participant_2026_ids_are_uint16():
    p = decode_packet(participant_packet(2026, 0, b"Net Human", driver_id=65535, network_id=513, team_id=300))
    assert (p.driver_id, p.network_id, p.team_id) == (65535, 513, 300)


@BOTH
def test_participant_name_truncated_with_ellipsis(fmt):
    # 29 ASCII bytes + U+2026 (3 bytes) = 32 bytes, no null terminator.
    raw = b"A" * 29 + "…".encode()
    assert len(raw) == 32
    assert decode_packet(participant_packet(fmt, 0, raw)).name == "A" * 29 + "…"


def test_decode_name_rules():
    assert decode_name(b"Lando\x00garbage\x00") == "Lando"
    assert decode_name("Pérez".encode() + b"\x00" * 10) == "Pérez"
    assert decode_name(b"Max\xe2\x80") == "Max�"  # cut mid-character: replaced, not an error
    assert decode_name(b"\x00" * 32) == ""


# --- Car Telemetry (6) -----------------------------------------------------------

TEL = {2025: ("<HfffBbHBBH4H4B4BH4f4B", 60), 2026: ("<HfffBbHBBH4H4B4BB4f4B", 59)}


@BOTH
def test_car_telemetry(fmt):
    f, stride = TEL[fmt]
    player = 2
    engine_temp = 300 if fmt == 2025 else 110  # 2025 is uint16, 2026 uint8
    vals = (312, 1.0, -0.25, 0.5, 0, -1, 11800, 1, 87, 0x7FFF,
            500, 510, 520, 530, 90, 91, 92, 93, 100, 101, 102, 103, engine_temp,
            22.5, 22.75, 23.0, 23.25, 0, 0, 1, 7)
    decoy = (5, 0.0, 0.0, 0.0, 0, 3, 1, 0, 0, 0) + (0,) * 12 + (1,) + (0.0,) * 4 + (0,) * 4
    pkt = blank_packet(fmt, 6, player=player)
    fill_cars(pkt, f, stride, CARS[fmt], player, vals, decoy)
    struct.pack_into("<BBb", pkt, HDR + CARS[fmt] * stride, 255, 255, 7)

    t = decode_packet(pkt)
    assert isinstance(t, CarTelemetry)
    assert (t.speed_kph, t.throttle, t.steer, t.brake) == (312, 1.0, -0.25, 0.5)
    assert (t.gear, t.engine_rpm, t.drs, t.rev_lights_percent) == (-1, 11800, True, 87)
    assert t.brakes_temperature == (500, 510, 520, 530)
    assert t.tyres_surface_temperature == (90, 91, 92, 93)
    assert t.tyres_inner_temperature == (100, 101, 102, 103)
    assert t.engine_temperature == engine_temp
    assert t.tyres_pressure == (22.5, 22.75, 23.0, 23.25)
    assert t.surface_type == (0, 0, 1, 7)
    assert t.suggested_gear == 7


# --- Car Status (7) --------------------------------------------------------------

STATUS = {2025: ("<BBBBBfffHHBBHBBBbfffBfffB", 55), 2026: ("<BBBBBfffHHBBHBBBbfffBffffB", 59)}


def status_packet(fmt, player, actual, visual, age):
    f, stride = STATUS[fmt]
    ers_tail = (1.0, 2.0, 3.0) if fmt == 2025 else (1.0, 2.0, 2.5, 3.0)
    vals = (0, 0, 1, 55, 1, 12.5, 110.0, 3.25, 13000, 4000, 8, 1, 0, actual, visual, age, 1,
            1.0, 2.0, 3.5e6, 2, *ers_tail, 0)
    decoy = (0,) * 5 + (0.0,) * 3 + (0, 0, 0, 0, 0, 99, 99, 99, 0) + (0.0,) * 3 + (0,) + (0.0,) * len(ers_tail) + (0,)
    pkt = blank_packet(fmt, 7, player=player)
    fill_cars(pkt, f, stride, CARS[fmt], player, vals, decoy)
    return pkt


@BOTH
def test_car_status(fmt):
    s = decode_packet(status_packet(fmt, 4, actual=18, visual=17, age=5))
    assert isinstance(s, CarStatus)
    assert s.actual_compound.compound is Compound.C3
    assert s.visual_compound.compound is Compound.MEDIUM
    assert s.tyres_age_laps == 5
    assert s.pit_limiter is True
    assert (s.fuel_in_tank, s.fuel_remaining_laps, s.max_rpm) == (12.5, 3.25, 13000)
    assert s.ers_store_energy == 3.5e6 and s.ers_deploy_mode == 2


@BOTH
def test_car_status_unknown_compound_kept(fmt):
    s = decode_packet(status_packet(fmt, 0, actual=99, visual=0, age=0))
    assert s.actual_compound.compound is Compound.UNKNOWN
    assert s.actual_compound.label == "unknown(99)"
    assert str(s.visual_compound) == "unknown(0)"


# --- Session History (11) ----------------------------------------------------------
# carIdx@29 numLaps@30 numStints@31 best lap/S1/S2/S3@32..35, laps@36 (14 bytes each), stints@1436

HIST_LAP = "<IHBHBHBB"


def history_packet(fmt, player, car_idx, laps, num_laps=None, stints=()):
    pkt = blank_packet(fmt, 11, player=player)
    struct.pack_into("<7B", pkt, 29, car_idx, len(laps) if num_laps is None else num_laps, len(stints), 2, 2, 1, 3)
    for i in range(100):
        lap = laps[i] if i < len(laps) else (999999, 1, 9, 1, 9, 1, 9, 0x0F)  # junk past numLaps
        struct.pack_into(HIST_LAP, pkt, 36 + i * 14, *lap)
    for i, stint in enumerate(stints):
        struct.pack_into("<BBB", pkt, 1436 + i * 3, *stint)
    return pkt


@BOTH
def test_session_history_other_car_ignored(fmt):
    assert decode_packet(history_packet(fmt, player=0, car_idx=20, laps=[])) is None


@BOTH
def test_session_history_player(fmt):
    laps = [
        (91234, 30123, 0, 31000, 0, 30111, 0, 0x0F),   # all valid
        (95000, 1500, 1, 32000, 0, 1500, 0, 0x0D),     # sector 1 invalid -> lap still flagged valid
        (0, 29000, 0, 0, 0, 0, 0, 0x0E),               # current partial lap: lap flag not set
    ]
    h = decode_packet(history_packet(fmt, player=7, car_idx=7, laps=laps,
                                     stints=[(255, 18, 17), (3, 17, 16)]))
    assert isinstance(h, SessionHistory)
    assert h.car_idx == 7 and h.num_laps == 3
    assert len(h.slots) == 100 and len(h.laps) == 3
    first, second, current = h.laps
    assert (first.lap_time_ms, first.sector1_time_ms, first.sector2_time_ms, first.sector3_time_ms) == \
        (91234, 30123, 31000, 30111)
    assert (first.lap_valid, first.sector1_valid, first.sector2_valid, first.sector3_valid) == (True,) * 4
    assert second.sector1_time_ms == 60000 + 1500
    assert (second.lap_valid, second.sector1_valid, second.sector2_valid, second.sector3_valid) == \
        (True, False, True, True)
    assert current.lap_valid is False
    assert (h.best_lap_time_lap_num, h.best_sector1_lap_num) == (2, 2)
    assert [s.end_lap for s in h.tyre_stints] == [255, 3]
    assert h.tyre_stints[0].actual_compound.compound is Compound.C3


@BOTH
def test_session_history_num_laps_clamped(fmt):
    h = decode_packet(history_packet(fmt, player=0, car_idx=0, laps=[], num_laps=250))
    assert h.num_laps == 100 and len(h.laps) == 100


# --- Time Trial (14) ---------------------------------------------------------------

TT = {2025: ("<BBIIIIBBBBBB", 24), 2026: ("<BHIIIIBBBBBB", 25)}


@BOTH
def test_time_trial(fmt):
    f, size = TT[fmt]
    assert struct.calcsize(f) == size
    team = 300 if fmt == 2026 else 3
    pkt = blank_packet(fmt, 14, player=0)
    struct.pack_into(f, pkt, HDR, 0, team, 91234, 30123, 31000, 30111, 0, 1, 0, 1, 0, 1)
    struct.pack_into(f, pkt, HDR + size, 20, team, 90500, 30000, 30500, 30000, 0, 0, 0, 1, 0, 1)
    struct.pack_into(f, pkt, HDR + 2 * size, 21, team, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

    t = decode_packet(pkt)
    assert isinstance(t, TimeTrial)
    sb = t.player_session_best
    assert (sb.car_idx, sb.team_id, sb.lap_time_ms) == (0, team, 91234)
    assert (sb.sector1_time_ms, sb.sector2_time_ms, sb.sector3_time_ms) == (30123, 31000, 30111)
    assert sb.gearbox_assist is True and sb.traction_control is False and sb.valid is True
    assert (t.personal_best.car_idx, t.personal_best.lap_time_ms) == (20, 90500)
    assert t.rival.valid is False


# --- Ignored packets ---------------------------------------------------------------

@pytest.mark.parametrize("fmt,pid", [(2025, 5), (2025, 10), (2025, 15), (2026, 13), (2026, 16)])
def test_ignored_packets_decode_to_none(fmt, pid):
    assert decode_packet(blank_packet(fmt, pid)) is None
