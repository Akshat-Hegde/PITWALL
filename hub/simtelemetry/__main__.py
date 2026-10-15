"""Command line: python -m simtelemetry {run,listen,record,replay,setup-code} ..."""

from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
import io
import logging
import socket
import sqlite3
import subprocess
import sys
import time
import traceback
import zipfile
from pathlib import Path

import uvicorn

from .adapters.f1.adapter import F1Adapter
from . import __version__, brand, paths
from .api.app import create_app
from .config import AppConfig, ConfigProblem, load_config_safe
from .core.feed import lan_address
from .core.health import RigState
from .core.rigs import RigRegistry
from .core.settings import SettingsStore, apply_settings, recover_damaged_settings
from .core.setup_code import SetupCode
from .hub import Hub
from .logging_setup import setup_logging, teardown_logging
from .net.udp import PortInUseError, UdpListener, bind_socket, port_shadows
from .core.store import LapStore, open_lap_store
from .startup import allow_sleep, clear_start_error, keep_awake, write_start_error
from .tools.recorder import GB, Recorder
from .tools.replay import ReplayError, SourceSelection, replay, select_source

log = logging.getLogger("simtelemetry")

HUB_COMMANDS = ("run", "listen", "record", "replay")
UDP_RETRY_S = 30.0          # while another program holds the telemetry port, try again this often


def add_record_flags(p: argparse.ArgumentParser) -> None:
    group = p.add_mutually_exclusive_group()
    group.add_argument("--record", dest="record", action="store_true", default=None,
                       help="record raw packets (overrides config)")
    group.add_argument("--no-record", dest="record", action="store_false",
                       help="don't record raw packets (overrides config)")


def should_record(args: argparse.Namespace, config: AppConfig) -> bool:
    if args.command == "record":
        return True
    if args.command == "replay" or getattr(args, "demo", False):
        return False
    if args.record is not None:
        return args.record
    return config.recorder.enabled_in_run if args.command == "run" else config.recorder.enabled_in_listen


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", type=Path, help="TOML config (default: config/hub.toml if present)")
    common.add_argument("--data-dir", type=Path, help="override data_dir from config")
    common.add_argument("--port", type=int, help="UDP telemetry port (default from config, 20777)")
    common.add_argument("--http-port", type=int, help="HTTP/API port (default from config, 8000)")
    common.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    common.add_argument("--lap-debug", action="store_true",
                        help="log every lap event (started, completed, invalidated, reset, flashback, "
                             "session history update) to the console and data/logs/lap-debug-*.log")

    parser = argparse.ArgumentParser(prog="simtelemetry", description="Sim racing cafe telemetry hub")
    parser.add_argument("--version", action="version", version=f"{brand.PRODUCT_NAME} {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", parents=[common], help="hub + TV dashboard and API")
    add_record_flags(p)
    p.add_argument("--owner-pin", help="PIN for the /owner page (overrides [owner] pin; handy for demos)")
    p.add_argument("--demo", action="store_true",
                   help="demo: fresh demo data in data-demo/ (or --data-dir), six simulated rigs, the Director "
                        "panel on /staff; owner PIN 0000 unless set. Doesn't listen for real rigs.")
    p.add_argument("--duration", type=float, help="stop after this many seconds")

    p = sub.add_parser("listen", parents=[common], help="debug: no API, one status line per rig per second")
    add_record_flags(p)
    p.add_argument("--duration", type=float, help="stop after this many seconds")

    p = sub.add_parser("record", parents=[common], help="capture raw packets to file (health summary only)")
    p.add_argument("--out", type=Path, help="recordings directory (default: [recorder] directory, "
                                            "else <data_dir>/recordings)")
    p.add_argument("--duration", type=float, help="stop after this many seconds")

    p = sub.add_parser("replay", parents=[common], help="replay recordings through the pipeline")
    p.add_argument("files", nargs="+", type=Path, help=".f1rec files, replayed in the order given")
    p.add_argument("--speed", type=float, default=1.0, help="1 = real time, 0 = as fast as possible")
    p.add_argument("--no-api", action="store_true", help="don't serve the HTTP API while replaying")
    p.add_argument("--hold", action="store_true", help="keep serving the API after the replay ends")
    p.add_argument("--quiet", action="store_true", help="don't print per-rig status lines")
    p.add_argument("--from-ip", help="only replay packets recorded from this source IP")
    p.add_argument("--as-ip", help="replay packets as if sent from this IP (needs --from-ip if the file has "
                                   "several source IPs)")
    p.add_argument("--live", action="store_true",
                   help="also listen for live UDP rigs, so the recording plays alongside them in one hub; "
                        "keeps running after the replay ends")
    p.add_argument("--save-laps", action="store_true",
                   help="store the replayed laps in the lap database (default: kept in memory only)")
    p.add_argument("--duration", type=float, help="stop after this many seconds")
    p.add_argument("--rigs", type=int, default=None,
                   help="play this many rigs at once from the recordings' sources (each source reused, staggered "
                        "round the track, as 10.30.0.<n>); loops. For screenshots and demos with real data")
    p.add_argument("--names", default=None, help="with --rigs: comma-separated driver names for the rigs")

    p = sub.add_parser("seed-demo", help="fill a separate demo data folder with a busy cafe's history "
                                         "(for demoing the staff and owner pages)")
    p.add_argument("--data-dir", type=Path, default=None,
                   help="demo data folder (default data-demo in the home folder); must be empty or made by seed-demo before")
    p.add_argument("--days", type=int, default=60, help="days of history (default 60)")

    p = sub.add_parser("setup-code", help="show the one-time first-run setup code (--new makes a fresh one)")
    p.add_argument("--new", action="store_true", help="make a fresh code and print it (the installer does this)")
    p.add_argument("--reset", action="store_true",
                   help="forgot the owner PIN: mark setup as not done and make a new code (run on the hub PC, as administrator)")
    p.add_argument("--config", type=Path, default=None, help="TOML config (default: config/hub.toml if present)")
    p.add_argument("--data-dir", type=Path, default=None, help="override data_dir from config")

    p = sub.add_parser("save-outline", help="save a track outline the hub learned as a bundled track file")
    p.add_argument("track", nargs="?", help="track key (e.g. F1:7) or name; omit to list the learned outlines")
    p.add_argument("--config", type=Path, default=None, help="TOML config (default: config/hub.toml if present)")
    p.add_argument("--data-dir", type=Path, default=None, help="override data_dir from config")
    p.add_argument("--out", type=Path, default=None, help="folder to write to (default: the hub's bundled tracks)")

    p = sub.add_parser("backup", help="make a backup now (laps, settings, branding, config) in the backup folder")
    p.add_argument("--config", type=Path, default=None, help="TOML config (default: config/hub.toml if present)")
    p.add_argument("--data-dir", type=Path, default=None, help="override data_dir from config")

    p = sub.add_parser("restore", help="put a backup zip back (stop the hub first)")
    p.add_argument("zip", type=Path, help="a backup zip made by the backup command or the nightly job")
    p.add_argument("--config", type=Path, default=None, help="TOML config (default: config/hub.toml if present)")
    p.add_argument("--data-dir", type=Path, default=None, help="override data_dir from config")
    p.add_argument("--http-port", type=int, default=None, help="HTTP port the hub uses, to check it is stopped")
    return parser


def apply_overrides(config: AppConfig, args: argparse.Namespace) -> AppConfig:
    if args.data_dir is not None:
        config.data_dir = args.data_dir
    if getattr(args, "port", None) is not None:
        config.network.udp_port = args.port
    if getattr(args, "http_port", None) is not None:
        config.network.http_port = args.http_port
    if getattr(args, "owner_pin", None):
        config.owner.pin = args.owner_pin
    return config


async def print_status_lines(hub: Hub) -> None:
    while True:
        await asyncio.sleep(1.0)
        now = time.monotonic()
        stamp = time.strftime("%H:%M:%S")
        for rig in hub.registry.all():
            if rig.first_seen is not None or hub.health.state(rig.ip, now) is not RigState.NO_DATA:
                print(f"{stamp} {hub.listen_line(rig, now)}", flush=True)


async def replay_and_report(args: argparse.Namespace, hub: Hub, selection: SourceSelection) -> None:
    if getattr(args, "rigs", None):
        from .tools.replay import CLONE_NET, load_streams, replay_rigs
        streams = load_streams(args.files, args.from_ip)
        names = [n.strip() for n in (args.names or "").split(",") if n.strip()]
        for n, name in enumerate(names[:args.rigs], start=1):
            hub.drivers.assign(f"{CLONE_NET}{n}", name)
        log.info("Replaying %d rigs from %d recorded sources", args.rigs, len(streams))
        await replay_rigs(streams, hub.on_datagram, args.rigs, args.speed)
        return
    try:
        await replay(args.files, hub.on_datagram, args.speed, selection)
    except Exception:  # with --live nothing awaits this task, so report here
        log.exception("Replay failed")
        return
    await hub.drain()
    hub.health.tick(time.monotonic())
    for line in hub.summary_lines(time.monotonic()):
        log.info("%s", line)


def live_handler(hub: Hub, replay_ip: str | None):
    """UDP handler for replay --live: warns once if a live rig uses the IP the recording plays as."""
    warned = False

    def handle(data: bytes, ip: str, wall_time: float) -> None:
        nonlocal warned
        if ip == replay_ip and not warned:
            warned = True
            log.warning("Live packets are arriving from %s, the same IP the recording is replayed as; "
                        "both will be mixed into one rig. Use a different --as-ip.", ip)
        hub.on_datagram(data, ip, wall_time)

    return handle


async def run_hub(args: argparse.Namespace, hub: Hub, selection: SourceSelection = SourceSelection()) -> None:
    cmd = args.command
    net = hub.config.network
    is_replay = cmd == "replay"
    demo = getattr(args, "demo", False)
    live = (not is_replay or args.live) and not demo  # the demo's rigs are simulated; leave the UDP port free
    serve_api = cmd == "run" or (is_replay and not args.no_api)
    print_lines = cmd == "listen" or (is_replay and not args.quiet)

    # Bind everything first so a taken port fails before anything starts.
    http_sock = bind_socket(socket.SOCK_STREAM, net.http_host, net.http_port) if serve_api else None
    listener = None
    udp_retry = None
    if live:
        handler = live_handler(hub, selection.as_ip or selection.from_ip) if is_replay else hub.on_datagram
        listener = UdpListener(net.udp_host, net.udp_port, net.udp_receive_buffer_bytes, handler)
        try:
            await listener.start()
        except PortInUseError as exc:
            if http_sock is None:       # nothing to show without the telemetry port (listen, record)
                raise
            # The pages still work (setup, staff, owner); keep trying the port in the background.
            hub.udp_busy = udp_busy_message(exc.port)
            log.warning("%s (%s)", port_in_use_message(exc).replace("\n", " "), exc.cause)
            udp_retry = retry_udp(hub, listener)
        else:
            note_port_shadows(hub, listener.port)

    if hub.recorder is not None:
        hub.recorder.start()
    tasks = [asyncio.create_task(hub.consume()), asyncio.create_task(hub.tick_health()),
             asyncio.create_task(hub.tick_podium()), asyncio.create_task(hub.tick_competitions()),
             asyncio.create_task(hub.tick_races())]
    if udp_retry is not None:
        tasks.append(asyncio.create_task(udp_retry))
    if cmd == "run" and not demo and hub.config.backup.enabled and hub.drivers.store.path is not None:
        tasks.append(asyncio.create_task(hub.backup_loop()))
    if print_lines:
        tasks.append(asyncio.create_task(print_status_lines(hub)))
    if demo:
        from .tools.demo_director import DemoDirector
        from .tools.demo_sim import DemoSimulator
        sim = DemoSimulator(hub)
        hub.demo = DemoDirector(hub, sim)
        hub.demo.start_sessions()
        tasks.append(asyncio.create_task(sim.run()))
    server = server_task = None
    if http_sock is not None:
        # Open dashboard WebSockets would otherwise hold up shutdown.
        server = uvicorn.Server(uvicorn.Config(create_app(hub), log_level="warning", lifespan="off",
                                               timeout_graceful_shutdown=2))
        server_task = asyncio.create_task(server.serve(sockets=[http_sock]))
        host = "localhost" if net.http_host == "0.0.0.0" else net.http_host
        log.info("Dashboard on http://%s:%d/ (API: /api/health)", host, net.http_port)
        if cmd == "run":
            clear_start_error(hub.config.data_dir)      # a clean start: the pages are being served

    replay_task = None
    if is_replay:
        replay_task = asyncio.create_task(replay_and_report(args, hub, selection))
        tasks.append(replay_task)

    try:
        if is_replay and not args.live and not args.hold:
            await replay_task
        elif args.duration is not None:
            await asyncio.sleep(args.duration)
        elif server_task is not None:
            await server_task
        else:
            await asyncio.Event().wait()
    finally:
        if server is not None:
            server.should_exit = True
            await asyncio.gather(server_task, return_exceptions=True)
        if listener is not None:
            listener.close()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def note_port_shadows(hub: Hub, port: int) -> None:
    hub.port_shadows = port_shadows(port)
    for shadow in hub.port_shadows:
        log.warning("%s", shadow)


def udp_busy_message(port: int) -> str:
    """Staff and setup pages (never the TV)."""
    return (f"Another program is using port {port} (often SimHub). Close it or change its port. "
            f"Until then no rig data reaches the hub; it tries again every {UDP_RETRY_S:g} seconds.")


async def retry_udp(hub: Hub, listener: UdpListener, every: float | None = None) -> None:
    """Try to bind the telemetry port every `every` seconds until it works; then clear the warning."""
    while True:
        await asyncio.sleep(UDP_RETRY_S if every is None else every)
        try:
            await listener.start()
        except PortInUseError:
            continue
        except OSError:
            log.exception("Could not open the telemetry port")
            continue
        hub.udp_busy = None
        log.info("The telemetry port %d is free now: listening for rigs", listener.port)
        note_port_shadows(hub, listener.port)
        return


def port_in_use_message(exc: PortInUseError) -> str:
    if exc.protocol == "UDP":
        return (f"UDP port {exc.port} is already in use by another program "
                f"(for example SimHub or another telemetry app).\n"
                f"Close that program, or start the hub on a different port, e.g. --port {exc.port + 1}, "
                f"and set the same UDP port on every rig.")
    return (f"HTTP port {exc.port} is already in use by another program.\n"
            f"Close that program, or start the hub with a different one, e.g. --http-port {exc.port + 1}.")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        argv = ["run"]  # double-clicking the exe starts the hub
    args = build_parser().parse_args(argv)
    if args.command == "seed-demo":
        from .tools.seed_demo import DemoTargetError, seed
        if args.data_dir is None:
            args.data_dir = paths.home() / "data-demo"
        try:
            counts = seed(args.data_dir, args.days)
        except DemoTargetError as exc:
            print(f"\nERROR: {exc}\n", file=sys.stderr)
            return 2
        print(f"Demo data in {args.data_dir}: {counts['sessions']} sessions, {counts['laps']} laps, "
              f"{counts['drivers']} drivers ({counts['profiles']} with profiles).\n"
              f"Run it with:  python -m simtelemetry run --data-dir {args.data_dir} --owner-pin 0000")
        return 0
    if args.command in HUB_COMMANDS:
        return hub_main(args)
    config, problems = load_config_safe(args.config)
    for problem in problems:
        print(f"WARNING: {problem.detail}", file=sys.stderr)
    config = apply_overrides(config, args)
    if args.command == "save-outline":
        return save_outline(args, config)
    if args.command == "setup-code":
        return setup_code_command(args, config)
    if args.command == "backup":
        return backup_command(args, config)
    if args.command == "restore":
        return restore_command(args, config)
    raise AssertionError(args.command)


def hub_main(args: argparse.Namespace) -> int:
    """run / listen / record / replay. Never refuses to start over configuration (see load_config_safe), and every
    start-up failure ends up in hub.log and, for `run`, in <data>/last-start-error.txt."""
    data_dir = args.data_dir if args.data_dir is not None else paths.home() / "data"
    log_dir = data_dir / "logs"
    lap_log = setup_logging(log_dir, args.verbose, args.lap_debug)   # before the config, so its problems are logged
    try:
        config, problems = load_config_safe(args.config)
        config = apply_overrides(config, args)
        data_dir = config.data_dir
        if config.data_dir / "logs" != log_dir:
            lap_log = setup_logging(config.data_dir / "logs", args.verbose, args.lap_debug)
        if lap_log is not None:
            log.info("Lap debug log: %s", lap_log)
        for problem in problems:
            log.warning("%s", problem.detail)
        return run_command(args, config, problems)
    except Exception:
        log.exception("The hub could not start")
        if args.command == "run":
            write_start_error(data_dir, f"{brand.PRODUCT_NAME} stopped because of an unexpected error. Restart the "
                                        "PC; if this happens again, send this file and the logs folder to support.",
                              traceback.format_exc())
        return 1
    finally:
        teardown_logging()  # main() may be called again in-process (tests); don't leave handlers behind


def setup_code_command(args: argparse.Namespace, config: AppConfig) -> int:
    """`setup-code`: --new makes and prints a fresh code; otherwise print the current one."""
    code = SetupCode(config.data_dir)
    if args.reset:
        store = SettingsStore(config.data_dir)
        s = store.load()
        if s is not None:
            store.save(s.model_copy(update={"setup_done": False}))    # everything else is kept
        print(code.new())
        print(f"Setup is open again. Open http://localhost:{config.network.http_port}/setup, enter the code above "
              "and choose a new owner PIN. The hub picks this up without a restart.")
        return 0
    if args.new:
        print(code.new())
        return 0
    s = SettingsStore(config.data_dir).load()
    if s is not None and s.setup_done:
        print("Setup is done; use the owner PIN.")
        return 0
    print(code.ensure())
    return 0


def backup_command(args: argparse.Namespace, config: AppConfig) -> int:
    """`backup`: one backup now; prints the zip path."""
    from .core.backup import make_backup, prune
    try:
        out = make_backup(config.data_dir, args.config or paths.config_path(), config.backups_dir, dt.datetime.now())
        prune(config.backups_dir, config.backup.keep)
    except (OSError, sqlite3.Error) as exc:
        print(f"ERROR: backup failed: {exc}", file=sys.stderr)
        return 2
    print(out)
    return 0


def hub_is_running(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def task_enabled(name: str) -> bool | None:
    """Is the scheduled task `name` enabled? None when it can't be told (not Windows, no task, any error)."""
    try:
        out = subprocess.run(["schtasks", "/Query", "/TN", name, "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=10, check=False)
        if out.returncode != 0:
            return None
        row = next(csv.reader(io.StringIO(out.stdout.strip().splitlines()[0])))
        status = row[2].strip().lower()
    except Exception:
        return None
    return status != "disabled"


def restore_task_warning() -> str | None:
    """Frozen on Windows: the start-up task restarts a stopped hub within a minute, so tell the user to disable it."""
    if not (paths.is_frozen() and sys.platform == "win32"):
        return None
    if task_enabled(brand.TASK_NAME):
        return (f'WARNING: the scheduled task "{brand.TASK_NAME}" is enabled and restarts the hub within a minute. '
                "Disable it first (Task Scheduler, right-click, Disable), then End it, restore, "
                "and Enable and Run it afterwards.")
    return None


def restore_command(args: argparse.Namespace, config: AppConfig) -> int:
    """`restore <zip>`: refuses while the hub answers on its HTTP port."""
    from .core.backup import restore
    port = config.network.http_port
    if hub_is_running(port):
        print(f"ERROR: the hub is running (port {port} answers). Stop it, then restore.", file=sys.stderr)
        return 2
    if not args.zip.is_file():
        print(f"ERROR: no such backup file: {args.zip}", file=sys.stderr)
        return 2
    warning = restore_task_warning()
    if warning:
        print(warning, file=sys.stderr)
    try:
        restore(args.zip, config.data_dir, args.config or paths.config_path())
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"ERROR: restore failed: {exc}", file=sys.stderr)
        return 2
    print(f"Restored {args.zip} into {config.data_dir}. Start the hub again.")
    return 0


def apply_saved_settings(config: AppConfig, args: argparse.Namespace) -> bool:
    """Layer the owner's /setup choices over hub.toml. Command-line flags still win. True if setup is done."""
    s = SettingsStore(config.data_dir).load()
    if s is None:
        return False
    apply_settings(config, s)
    if getattr(args, "owner_pin", None):
        config.owner.pin = args.owner_pin
    return s.setup_done


def save_outline(args: argparse.Namespace, config: AppConfig) -> int:
    """`save-outline`: copy a learned outline from the lap database into a bundled track file."""
    from .core.tracks import BUNDLED_DIR, save_bundled
    db = config.data_dir / "laps.db"
    if not db.exists():
        print(f"ERROR: no lap database at {db}", file=sys.stderr)
        return 2
    store = LapStore(db)
    try:
        outlines = store.outlines()
    finally:
        store.close()
    if not args.track:
        if not outlines:
            print("No learned outlines yet: drive a full lap first.")
        for key, o in sorted(outlines.items()):
            print(f"{key:10} {o.get('track_name') or '':24} {len(o['points']):5} points, "
                  f"{o.get('laps', 1)} lap(s), source {o.get('source')}")
        return 0
    want = args.track.casefold()
    match = [o for k, o in outlines.items() if k.casefold() == want or (o.get("track_name") or "").casefold() == want]
    if not match:
        print(f"ERROR: no learned outline for '{args.track}'. Known: {', '.join(sorted(outlines)) or 'none'}",
              file=sys.stderr)
        return 2
    path = save_bundled(match[0], args.out or BUNDLED_DIR)
    print(f"Saved {match[0]['track_key']} ({match[0].get('track_name')}) to {path}")
    return 0


def prepare_demo(args: argparse.Namespace, config: AppConfig) -> None:
    """`run --demo`: re-seed the demo folder (dates move with today) and set demo-friendly settings."""
    from .tools.demo_sim import DEMO_TRACK_NAME, TRACK_ID
    from .tools.seed_demo import seed
    if args.data_dir is None:
        config.data_dir = paths.home() / "data-demo"
    if config.backup.directory is None:        # "Back up now" on /owner must never prune the real backups
        config.backup.directory = paths.home() / "backups-demo"
    counts = seed(config.data_dir)
    config.track_names[TRACK_ID] = DEMO_TRACK_NAME
    if not config.owner.pin:
        config.owner.pin = "0000"
    log.info("Demo: %d sessions and %d laps of history in %s; six simulated rigs; owner PIN %s; "
             "Director panel on /staff", counts["sessions"], counts["laps"], config.data_dir, config.owner.pin)


def run_command(args: argparse.Namespace, config: AppConfig, problems: list[ConfigProblem] = ()) -> int:
    warnings: list[tuple[str, str]] = [("config", p.message) for p in problems]
    if getattr(args, "demo", False):
        from .tools.seed_demo import DemoTargetError
        try:
            prepare_demo(args, config)
        except DemoTargetError as exc:
            print(f"\nERROR: {exc}\n", file=sys.stderr)
            return 2
    if not getattr(args, "demo", False):
        damaged = recover_damaged_settings(SettingsStore(config.data_dir), config.backups_dir, dt.datetime.now())
        if damaged:
            warnings.append(("settings_damaged", damaged))
        setup_done = apply_saved_settings(config, args)
        if args.command == "run" and not setup_done:
            # Console and logs/hub.log only; never the TV or the API.
            log.warning("First-run setup: open http://%s:%d/setup and enter setup code %s",
                        lan_address(), config.network.http_port, SetupCode(config.data_dir).ensure())
    registry = RigRegistry(config, config.data_dir / "rigs.json")
    recorder = None
    if should_record(args, config):
        rc = config.recorder
        recorder = Recorder(getattr(args, "out", None) or config.recordings_dir,
                            max_file_bytes=rc.max_file_mb * 1024 * 1024, keep_files=rc.keep_files,
                            warn_free_bytes=int(rc.warn_free_gb * GB), stop_free_bytes=int(rc.stop_free_gb * GB),
                            disk_check_interval_s=rc.disk_check_interval_s)
    # Replays keep their laps in memory unless asked, so old captures don't change the real boards.
    save_laps = args.command != "replay" or args.save_laps
    if save_laps:
        store, damaged = open_lap_store(config.data_dir / "laps.db", dt.datetime.now())
        if damaged:
            warnings.append(("laps_damaged", damaged))
    else:
        store = LapStore(None)
    from .core.tracks import load_bundled
    bundled = None if getattr(args, "demo", False) else load_bundled()  # the demo circuit is made up
    hub = Hub(config, F1Adapter(config.track_names), registry, recorder, store, bundled,
              config_path=args.config or paths.config_path())
    for code, message in warnings:
        hub.add_startup_warning(code, message)

    selection = SourceSelection()
    if args.command == "replay":
        try:
            if args.as_ip or args.from_ip:
                log.info("Scanning recording for source IPs")
            selection = select_source(args.files, args.from_ip, args.as_ip)
        except ReplayError as exc:
            print(f"\nERROR: {exc}\n", file=sys.stderr)
            return 2

    exit_code = 0
    awake = args.command == "run" and not getattr(args, "demo", False) and keep_awake()
    try:
        asyncio.run(run_hub(args, hub, selection))
    except PortInUseError as exc:
        message = port_in_use_message(exc)
        log.error("%s (%s)", message.replace("\n", " "), exc.cause)
        print(f"\nERROR: {message}\n", file=sys.stderr)
        if args.command == "run" and exc.protocol == "TCP":
            write_start_error(config.data_dir,
                              f"{brand.PRODUCT_NAME} could not start: another program is already using port "
                              f"{exc.port}, often a second copy of {brand.PRODUCT_NAME}. Restart the PC; if this "
                              "happens again, contact support.", message)
        exit_code = 2
    except KeyboardInterrupt:
        log.info("Stopping")
    finally:
        if awake:
            allow_sleep()
        if recorder is not None:
            recorder.close()
        store.close()
        registry.save()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
