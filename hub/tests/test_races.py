"""Race podium: grouping rig results into races, ranking, settle timing, race cards and the race_podium moment."""

from __future__ import annotations

from fastapi.testclient import TestClient

from simtelemetry.api.app import create_app
from simtelemetry.core.adapter import RaceFinished
from simtelemetry.core.races import RACE_GROUP_WINDOW_S, RACE_SETTLE_S, RaceBook

from test_drivers import make_hub

TRACK = "F1:7"


def fin(pos, track=TRACK, status="finished", laps=5, uid=None, grid=3):
    return RaceFinished(track_key=track, session_type="Race", session_uid=uid, position=pos, grid_position=grid,
                        laps=laps, best_lap_ms=88_123, total_time_s=400.5, penalties_s=0, status=status, num_cars=20)


def moments(hub, kind):
    return [b["moment"] for _, t, b in hub.laps.messages if t == "moment" and b["moment"]["kind"] == kind]


def test_three_rigs_become_one_race_ranked():
    book = RaceBook()
    for i, (rig, pos) in enumerate([("a", 4), ("b", 1), ("c", 7)]):
        book.add(rig, fin(pos), 10.0 * i)
    (race,) = book.due(100.0)
    assert [(rig, r.position) for rig, r in race.results] == [("b", 1), ("a", 4), ("c", 7)]
    assert race.finished_at == 20.0 and race.track_key == TRACK


def test_a_late_report_is_a_new_race_and_duplicates_are_ignored():
    book = RaceBook()
    book.add("a", fin(2), 0.0)
    book.add("a", fin(2), 5.0)                       # resend
    book.add("b", fin(1), 10.0)
    book.add("d", fin(3), 180.0)                     # 3 minutes later
    first, second = book.due(300.0)
    assert len(first.results) == 2 and [rig for rig, _ in second.results] == ["d"]
    book.add("a", fin(2, uid="u1"), 400.0)
    book.due(500.0)
    book.add("a", fin(2, uid="u1"), 510.0)           # resend after it settled
    assert book.due(600.0) == []


def test_resend_after_the_window_while_open_is_ignored():
    book = RaceBook()
    book.add("a", fin(2, uid="u1"), 0.0)
    book.add("a", fin(2, uid="u1"), 100.0)
    assert len(book.due(200.0)) == 1


def test_dnf_is_ranked_last_by_laps_then_position():
    book = RaceBook()
    book.add("a", fin(2, status="dnf", laps=3), 0.0)
    book.add("b", fin(9), 1.0)
    book.add("c", fin(5, status="dsq", laps=4), 2.0)
    (race,) = book.due(50.0)
    assert [rig for rig, _ in race.results] == ["b", "c", "a"]


def test_no_participants_known_settles_8s_after_the_last_report():
    book = RaceBook()
    book.add("a", fin(1), 0.0)
    book.add("b", fin(2), 3.0)
    assert book.due(3.0 + RACE_SETTLE_S - 0.1) == []
    assert len(book.due(3.0 + RACE_SETTLE_S)) == 1


def test_a_slow_finisher_joins_the_same_race():
    book = RaceBook()
    for rig in "ab":
        book.note_racing(rig, TRACK, 0.0)
    book.add("a", fin(1), 0.0)
    book.note_racing("b", TRACK, 8.5)
    assert book.due(8.5) == []                       # b is still racing: no solo publish
    book.note_racing("b", TRACK, 20.0)
    book.add("b", fin(2), 20.0)
    (race,) = book.due(20.0)                         # everyone reported: at once
    assert [rig for rig, _ in race.results] == ["a", "b"]


def test_everyone_reporting_within_seconds_publishes_at_once():
    book = RaceBook()
    for rig in "ab":
        book.note_racing(rig, TRACK, 0.0)
    book.add("a", fin(1), 10.0)
    assert book.due(10.0) == []                      # the reporter alone never fires
    book.add("b", fin(2), 11.5)
    assert len(book.due(11.5)) == 1


def test_a_participant_who_never_reports_holds_the_race_for_the_group_window():
    book = RaceBook()
    for rig in "ab":
        book.note_racing(rig, TRACK, 0.0)
    book.add("a", fin(1), 0.0)
    assert book.due(RACE_SETTLE_S + 1) == [] and book.due(RACE_GROUP_WINDOW_S - 1) == []
    (race,) = book.due(RACE_GROUP_WINDOW_S)
    assert [rig for rig, _ in race.results] == ["a"]


def test_a_reporter_missing_from_the_participants_does_not_delay_the_podium():
    book = RaceBook()
    book.note_racing("b", TRACK, 0.0)                # a's "racing" note was never seen (or expired)
    book.add("a", fin(1), 1.0)
    book.add("b", fin(2), 2.0)
    (race,) = book.due(2.0)                          # every participant has reported: at once
    assert [rig for rig, _ in race.results] == ["a", "b"]


def test_a_rig_racing_on_another_track_does_not_hold_the_race():
    book = RaceBook()
    book.note_racing("a", TRACK, 0.0)
    book.note_racing("c", "F1:9", 0.0)
    book.add("a", fin(1), 1.0)
    assert len(book.due(1.0)) == 1


def finish_race(hub, positions, now=0.0):
    for i, pos in enumerate(positions):
        hub.races.add(f"192.168.1.{21 + i}", fin(pos, uid="u"), now + i)
    return hub.settle_races(now + len(positions) + RACE_SETTLE_S)


def test_race_makes_cards_and_a_podium_moment(tmp_path):
    hub = make_hub(tmp_path)
    hub.drivers.assign("192.168.1.21", "Maya")
    finish_race(hub, [4, 1, 7])
    (m,) = moments(hub, "race_podium")
    assert [(d["rank"], d["position"]) for d in m["drivers"]] == [(1, 1), (2, 4), (3, 7)]
    assert m["wifi"] is None and m["track_key"] == TRACK and m["session_type"] == "Race"
    maya = next(d for d in m["drivers"] if d["rig_id"] == "192.168.1.21")
    assert maya["driver"] == "Maya" and maya["card_url"].endswith("/card/" + maya["card_token"])
    assert not moments(hub, "card")                                  # the podium carries the URLs instead
    client = TestClient(create_app(hub, dashboard_dir=tmp_path / "none"))
    card = client.get(f"/api/cards/{maya['card_token']}").json()
    assert card["kind"] == "race" and card["position"] == 4 and card["grid_position"] == 3
    assert card["positions_gained"] == -1 and card["cafe_rank"] == 2 and card["cafe_drivers"] == 3
    assert card["laps"] == 5 and card["best_ms"] == 88_123 and card["status"] == "finished"


def test_solo_race_makes_a_card_but_no_podium(tmp_path):
    hub = make_hub(tmp_path)
    (done,) = finish_race(hub, [6])
    assert not moments(hub, "race_podium")
    (card,) = moments(hub, "card")
    assert card["card_kind"] == "race" and card["position"] == 6 and card["url"].endswith("/card/" + card["token"])
    assert hub.drivers.card(card["token"])["kind"] == "race"


def test_flags_suppress_cards_and_moments(tmp_path):
    hub = make_hub(tmp_path, features={"race_podium": False})
    finish_race(hub, [1, 2])
    assert not moments(hub, "race_podium") and not moments(hub, "card")
    hub = make_hub(tmp_path / "c", features={"race_podium": False})
    finish_race(hub, [3])
    assert not moments(hub, "race_podium") and not moments(hub, "card")
    hub = make_hub(tmp_path / "b", features={"sharing": False})
    finish_race(hub, [1, 2])
    assert not moments(hub, "race_podium") and not moments(hub, "card")


def test_demo_race_action_shows_four_drivers(tmp_path):
    from simtelemetry.tools.demo_director import DemoDirector
    from simtelemetry.tools.demo_sim import DemoSimulator
    hub = make_hub(tmp_path)
    director = DemoDirector(hub, DemoSimulator(hub, rigs=4))
    assert director.run("race", {})["shown"] == "race_podium"
    (m,) = moments(hub, "race_podium")
    assert len(m["drivers"]) == 4
    assert all(300 < d["total_time_s"] < 600 for d in m["drivers"])
    assert len({d["grid_position"] for d in m["drivers"]}) == 4


async def test_hub_consume_groups_two_lan_finishers_into_one_race(tmp_path):
    """Participant tracking (from session packets), RaceBook and finish_race together, through Hub.consume."""
    import asyncio
    import time
    from f1_helpers import final_classification_packet, session_packet
    hub = make_hub(tmp_path)
    a, b = "192.168.1.21", "192.168.1.22"

    async def feed(*items):
        consumer = asyncio.create_task(hub.consume())
        for ip, data in items:
            hub.on_datagram(bytes(data), ip, 0.0)
        await hub.drain()
        consumer.cancel()

    race_session = lambda: session_packet(2025, 15)                       # noqa: E731
    final = lambda pos: final_classification_packet(2025, cars={3: dict(position=pos, laps=5, grid=2, best_ms=88_000, total_s=400.0)})  # noqa: E731
    await feed((a, race_session()), (b, race_session()), (a, final(1)))
    assert hub.races._open and len(hub.races._open[0].results) == 1
    assert hub.settle_races(time.monotonic() + RACE_SETTLE_S + 0.5) == []   # b is still racing
    await feed((b, final(2)))
    assert not hub.races._open                                               # settled at once, as one race
    (m,) = moments(hub, "race_podium")
    assert sorted(d["rig_id"] for d in m["drivers"]) == [a, b]
