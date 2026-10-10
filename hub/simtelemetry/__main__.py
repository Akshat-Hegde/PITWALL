"""Command line: python -m simtelemetry {run,listen,record,replay} ..."""

from __future__ import annotations

import argparse
import asyncio
import logging
import socket
import sys
import time
from pathlib import Path

import uvicorn

from .adapters.f1.adapter import F1Adapter
from .api.app import create_app
from .config import AppConfig, ConfigError, load_config
from .core.health import RigState
from .core.rigs import RigRegistry
from .hub import Hub
from .logging_setup import setup_logging, teardown_logging
from .net.udp import PortInUseError, UdpListener, bind_socket, port_shadows
from .core.store import LapStore
from .tools.recorder import GB, Recorder
from .tools.replay import ReplayError, SourceSelection, replay, select_source

log = logging.getLogger("simtelemetry")


def add_record_flags(p: argparse.ArgumentParser) -> None:
    group = p.add_mutually_exclusive_group()
    group.add_argument("--record", dest="record", action="store_true", default=None,
                       help="record raw packets (overrides config)")
    group.add_argument("--no-record", dest="record", action="store_false",
                       help="don't record raw packets (overrides config)")


def should_record(args: argparse.Namespace, config: AppConfig) -> bool:
    if args.command == "record":
        return True
    if args.command == "replay":
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
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", parents=[common], help="hub + TV dashboard and API")
    add_record_flags(p)
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
    return parser


def apply_overrides(config: AppConfig, args: argparse.Namespace) -> AppConfig:
    if args.data_dir is not None:
        config.data_dir = args.data_dir
    if args.port is not None:
        config.network.udp_port = args.port
    if args.http_port is not None:
        config.network.http_port = args.http_port
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
    live = not is_replay or args.live
    serve_api = cmd == "run" or (is_replay and not args.no_api)
    print_lines = cmd == "listen" or (is_replay and not args.quiet)

    # Bind everything first so a taken port fails before anything starts.
    http_sock = bind_socket(socket.SOCK_STREAM, net.http_host, net.http_port) if serve_api else None
    listener = None
    if live:
        handler = live_handler(hub, selection.as_ip or selection.from_ip) if is_replay else hub.on_datagram
        listener = UdpListener(net.udp_host, net.udp_port, net.udp_receive_buffer_bytes, handler)
        try:
            await listener.start()
        except PortInUseError:
            if http_sock:
                http_sock.close()
            raise
        hub.port_shadows = port_shadows(listener.port)
        for shadow in hub.port_shadows:
            log.warning("%s", shadow)

    if hub.recorder is not None:
        hub.recorder.start()
    tasks = [asyncio.create_task(hub.consume()), asyncio.create_task(hub.tick_health())]
    if print_lines:
        tasks.append(asyncio.create_task(print_status_lines(hub)))
    server = server_task = None
    if http_sock is not None:
        # Open dashboard WebSockets would otherwise hold up shutdown.
        server = uvicorn.Server(uvicorn.Config(create_app(hub), log_level="warning", lifespan="off",
                                               timeout_graceful_shutdown=2))
        server_task = asyncio.create_task(server.serve(sockets=[http_sock]))
        host = "localhost" if net.http_host == "0.0.0.0" else net.http_host
        log.info("Dashboard on http://%s:%d/ (API: /api/health)", host, net.http_port)

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


def port_in_use_message(exc: PortInUseError) -> str:
    if exc.protocol == "UDP":
        return (f"UDP port {exc.port} is already in use by another program "
                f"(for example SimHub or another telemetry app).\n"
                f"Close that program, or start the hub on a different port, e.g. --port {exc.port + 1}, "
                f"and set the same UDP port on every rig.")
    return (f"HTTP port {exc.port} is already in use by another program.\n"
            f"Close that program, or start the hub with a different one, e.g. --http-port {exc.port + 1}.")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = apply_overrides(load_config(args.config), args)
    except ConfigError as exc:
        print(f"\nERROR: {exc}\n", file=sys.stderr)
        return 2
    lap_log = setup_logging(config.data_dir / "logs", args.verbose, args.lap_debug)
    if lap_log is not None:
        log.info("Lap debug log: %s", lap_log)
    try:
        return run_command(args, config)
    finally:
        teardown_logging()  # main() may be called again in-process (tests); don't leave handlers behind


def run_command(args: argparse.Namespace, config: AppConfig) -> int:
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
    store = LapStore(config.data_dir / "laps.db" if save_laps else None)
    hub = Hub(config, F1Adapter(config.track_names), registry, recorder, store)

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
    try:
        asyncio.run(run_hub(args, hub, selection))
    except PortInUseError as exc:
        print(f"\nERROR: {port_in_use_message(exc)}\n", file=sys.stderr)
        exit_code = 2
    except KeyboardInterrupt:
        log.info("Stopping")
    finally:
        if recorder is not None:
            recorder.close()
        store.close()
        registry.save()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
