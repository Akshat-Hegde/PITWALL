"""`simtelemetry seed-demo`: fill a separate demo data folder with a busy cafe's history.

60 days of staff sessions on four rigs (busier in the evenings and at weekends), laps on four tracks, driver
profiles (fictional names, UK drama phone numbers 07700 900xxx that are never assigned), a running weekly
challenge and a short queue. Use it to demo the staff and owner pages:

    python -m simtelemetry run --demo                      # seeds data-demo/ and runs the hub on it

It never touches the real data folder: the target must be empty or a folder it created before.
"""

from __future__ import annotations

import datetime as dt
import random
import time
from pathlib import Path

from ..core.drivers import Assignment
from ..core.laps import LapRecord
from ..core.store import LapStore
from .demo_sim import DEMO_TRACK_NAME, TRACK_ID, Circuit, rig_ip

MARKER = ".simtelemetry-demo"
RIGS = [rig_ip(n) for n in range(1, 5)]   # the same rigs the demo simulator drives
TRACKS = [(f"F1:{TRACK_ID}", DEMO_TRACK_NAME, 88_000), ("F1:10", "Spa-Francorchamps", 104_000), ("F1:11", "Monza", 81_500),
          ("F1:13", "Suzuka", 90_500)]
FIRST = ["Maya", "Kofi", "Rosa", "Diego", "Hana", "Ollie", "Priya", "Sam", "Leni", "Arjun", "Tom", "Nico", "Zara",
         "Jonas", "Aiko", "Ben", "Chloe", "Dev", "Elif", "Finn", "Gita", "Hugo", "Isla", "Jay", "Kim", "Luca",
         "Mira", "Noah", "Omar", "Pia", "Quinn", "Ravi", "Sofia", "Theo", "Uma", "Vik", "Wren", "Yusuf", "Zoe", "Alex"]


SURNAMES = ["Rao", "Mensah", "Vega", "Kato", "Okafor", "Novak", "Silva", "Haddad", "Berg", "Iyer", "Costa", "Ward",
            "Moreau", "Tan", "Quinn", "Adeyemi", "Lund", "Sato", "Price", "Khan", "Rossi", "Byrne", "Diaz", "Ahmed"]


class DemoTargetError(Exception):
    pass


def seed(data_dir: Path, days: int = 60, seed_value: int = 7, now: float | None = None) -> dict[str, int]:
    data_dir = Path(data_dir)
    # The hub's own logs/ and rigs.json may already be there (`run --demo` starts logging first).
    others = [p for p in data_dir.iterdir() if p.name not in ("logs", "rigs.json")] if data_dir.exists() else []
    if others and not (data_dir / MARKER).exists():
        raise DemoTargetError(f"{data_dir} has other files in it. seed-demo only writes to an empty folder "
                              f"(or one it made before), so your real data is never touched.")
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / MARKER).write_text("Demo data made by `simtelemetry seed-demo`. Safe to delete.\n", encoding="utf-8")
    db = data_dir / "laps.db"
    for leftover in (db, db.with_suffix(".db-wal"), db.with_suffix(".db-shm")):
        leftover.unlink(missing_ok=True)
    store = LapStore(db)
    store._db.execute("PRAGMA synchronous=OFF")  # demo data: speed over crash safety
    rng = random.Random(seed_value)
    now_ts = now if now is not None else time.time()
    today = dt.datetime.fromtimestamp(now_ts).replace(hour=0, minute=0, second=0, microsecond=0)

    # Drivers: a third have profiles (they come back), the rest are walk-ins.
    drivers = []
    for i, name in enumerate(FIRST):
        full = f"{name} {chr(65 + (i * 7) % 26)}"
        skill = rng.uniform(0.985, 1.06)  # lap time factor
        profile = None
        if i % 3 == 0:
            profile = store.create_driver(full, f"+447700900{100 + i:03d}", consent_at=0, created_at=0)["id"]
        drivers.append({"name": full, "skill": skill, "profile": profile, "loyal": profile is not None})

    sessions = laps = 0
    walk_ins: dict[str, dict] = {}
    for back in range(days, -1, -1):
        day = today - dt.timedelta(days=back)
        weekend = day.weekday() >= 4  # Fri-Sun
        for rig in RIGS:
            hour = 10.0
            while hour < 22:
                busy = 0.25 + (0.45 if hour >= 17 else 0.15 if hour >= 13 else 0) + (0.2 if weekend else 0)
                if rng.random() > busy:
                    hour += 0.5
                    continue
                minutes = rng.choice([15, 20, 20, 30, 30, 45, 60])
                start = day + dt.timedelta(hours=hour, minutes=rng.randint(0, 10))
                end = start + dt.timedelta(minutes=minutes)
                if end.timestamp() > now_ts:
                    break
                if rng.random() < 0.45:
                    d = rng.choice([x for x in drivers if x["loyal"]])      # regulars with a profile
                else:                                                         # walk-ins, mostly first-timers
                    name = f"{rng.choice(FIRST)} {rng.choice(SURNAMES)}"
                    d = walk_ins.setdefault(name, {"name": name, "skill": rng.uniform(1.0, 1.08), "profile": None})
                started = round(start.timestamp() * 1000)
                store.start_driver_session(rig, Assignment(d["name"], started, d["profile"], None))
                store.end_driver_session(rig, round(end.timestamp() * 1000))
                sessions += 1
                track_key, track_name, base = rng.choice(TRACKS[:2] if rng.random() < 0.6 else TRACKS)
                t = start + dt.timedelta(minutes=2)
                lap_no = 1
                while t < end - dt.timedelta(minutes=1):
                    t += dt.timedelta(milliseconds=base * 1.1)
                    lap_ms = round(base * d["skill"] * rng.uniform(1.0, 1.035))
                    valid = rng.random() > 0.18
                    s1 = round(lap_ms * 0.32)
                    s2 = round(lap_ms * 0.36)
                    store.add(LapRecord(
                        rig_id=rig, rig_name=f"Rig {RIGS.index(rig) + 1}", driver=d["name"], track_key=track_key, track_name=track_name,
                        session_id=f"demo-{sessions}", lap_number=lap_no, lap_ms=lap_ms,
                        sectors_ms=(s1, s2, lap_ms - s1 - s2), valid=valid, out_lap=lap_no == 1, tyre=None,
                        personal_best=False, session_best=False, completed_at=round(t.timestamp() * 1000),
                        lap_class="pro" if d["skill"] < 1.01 else "open", driver_id=d["profile"]))
                    lap_no += 1
                    laps += 1
                hour += minutes / 60 + 0.25
    week_start = today - dt.timedelta(days=today.weekday())
    circuit = Circuit.build()
    n = len(circuit.points)
    store.save_outline({"track_key": f"F1:{TRACK_ID}", "track_name": DEMO_TRACK_NAME,
                        "points": [[round(x, 1), round(z, 1)] for x, z in circuit.points], "source": "bundled",
                        "sector_starts": [0, n // 3, 2 * n // 3],
                        "display": {"flip_x": False, "flip_z": False, "rotate_deg": 0}}, round(now_ts * 1000))
    store.create_challenge(title=f"{DEMO_TRACK_NAME} Pro week", track_key=f"F1:{TRACK_ID}", track_name=DEMO_TRACK_NAME,
                           lap_class="pro",
                           starts_at=round(week_start.timestamp() * 1000),
                           ends_at=round((week_start + dt.timedelta(days=7)).timestamp() * 1000),
                           prize="Free hour for the fastest Pro lap", created_at=round(now_ts * 1000))
    for name in ("Jordan P", "Office party (4)"):
        store.queue_add(name, None, round(now_ts * 1000))
    store.close()
    return {"sessions": sessions, "laps": laps, "drivers": len(drivers) + len(walk_ins),
            "profiles": sum(1 for d in drivers if d["profile"] is not None)}
