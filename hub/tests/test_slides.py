"""Slide meter and SAVE! detection."""

from simtelemetry.core.slides import SlideDetector


def run(samples, speed=180.0, dt=0.05):
    """samples: slide angles in degrees, one per dt seconds. Returns the saves detected."""
    d, t, saves = SlideDetector(), 100.0, []
    for angle in samples:
        t += dt
        save = d.update(t, angle, speed)
        if save:
            saves.append(save)
    return saves


def test_caught_slide_is_a_save():
    slide = [2, 5, 10, 18, 26, 22, 14, 6, 2, 1, 1, 1, 1, 1, 1, 1]
    (save,) = run(slide)
    assert save.peak_deg == 26 and 0.2 < save.duration_s < 1.0


def test_small_wiggle_is_not_a_save():
    assert run([2, 6, 9, 12, 8, 3, 1, 1, 1, 1, 1, 1, 1]) == []   # peak under 15 degrees


def test_spin_is_not_a_save():
    assert run([5, 20, 45, 80, 120, 160, 90, 40, 10, 2, 1, 1, 1, 1, 1, 1]) == []


def test_slow_speed_is_ignored():
    assert run([2, 10, 25, 30, 10, 1, 1, 1, 1, 1, 1], speed=30) == []


def test_flashback_drops_a_slide_in_progress():
    d = SlideDetector()
    d.update(100.0, 20, 180)
    d.update(100.1, 25, 180)
    assert d.update(90.0, 1, 180) is None and not d.sliding   # game time went back


async def test_save_reaches_the_feed(tmp_path):
    import math
    import struct
    from simtelemetry.core.feed import FeedBuilder
    from f1_helpers import blank_packet
    from test_feed import driving_rig, feed, last_seen, make_hub

    hub = make_hub(tmp_path)
    packets = driving_rig("192.168.1.21")
    t = 50.0
    for angle in [2, 10, 20, 28, 20, 10, 2, 1, 1, 1, 1, 1, 1, 1, 1]:
        t += 0.05
        pkt = blank_packet(2025, 13, player=0, session_uid=0x11)
        struct.pack_into("<f", pkt, 15, t)                                   # header session time
        struct.pack_into("<f", pkt, 29 + 128 + 44 + 32, math.radians(angle))  # chassis yaw
        packets.append(("192.168.1.21", bytes(pkt)))
    await feed(hub, packets)
    car = FeedBuilder(hub).frame_body(last_seen(hub))["rigs"][0]["car"]
    assert car["saves"] == 1 and car["last_save_peak_deg"] == 28.0 and car["last_save_at"] > 0
    assert car["slide_deg"] == 1.0
