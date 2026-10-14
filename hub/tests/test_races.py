"""Race podium: grouping rig results into races, ranking, settle timing, race cards and the race_podium moment."""

from __future__ import annotations

from fastapi.testclient import TestClient

from simtelemetry.api.app import create_app
from simtelemetry.core.adapter import RaceFinished
from simtelemetry.core.races import RACE_SETTLE_S, RaceBook

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
    (race,) = book.due(100.0, set())
    assert [(rig, r.position) for rig, r in race.results] == [("b", 1), ("a", 4), ("c", 7)]
    assert race.finished_at == 20.0 and race.track_key == TRACK


def test_a_late_report_is_a_new_race_and_duplicates_are_ignored():
    book = RaceBook()
    book.add("a", fin(2), 0.0)
    book.add("a", fin(2), 5.0)                       # resend
    book.add("b", fin(1), 10.0)
    book.add("d", fin(3), 180.0)                     # 3 minutes later
    first, second = book.due(300.0, set())
    assert len(first.results) == 2 and [rig for rig, _ in second.results] == ["d"]
    book.add("a", fin(2, uid="u1"), 400.0)
    book.due(500.0, set())
    book.add("a", fin(2, uid="u1"), 510.0)           # resend after it settled
    assert book.due(600.0, set()) == []


def test_resend_after_the_window_while_open_is_ignored():
    book = RaceBook()
    book.add("a", fin(2, uid="u1"), 0.0)
    book.add("a", fin(2, uid="u1"), 100.0)
    assert len(book.due(200.0, set())) == 1


def test_dnf_is_ranked_last_by_laps_then_position():
    book = RaceBook()
    book.add("a", fin(2, status="dnf", laps=3), 0.0)
    book.add("b", fin(9), 1.0)
    book.add("c", fin(5, status="dsq", laps=4), 2.0)
    (race,) = book.due(50.0, set())
    assert [rig for rig, _ in race.results] == ["b", "c", "a"]


def test_settle_after_8s_or_when_all_driving_rigs_reported():
    book = RaceBook()
    book.add("a", fin(1), 0.0)
    book.add("b", fin(2), 3.0)
    assert book.due(3.0 + RACE_SETTLE_S - 0.1, set()) == []
    assert book.due(3.0 + RACE_SETTLE_S - 0.1, {"a", "b", "c"}) == []        # c is still racing
    assert len(book.due(3.5, {"a", "b"})) == 1                                 # everyone driving has reported
    book.add("a", fin(1, track="F1:9"), 100.0)
    assert len(book.due(100.0 + RACE_SETTLE_S, set())) == 1


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
