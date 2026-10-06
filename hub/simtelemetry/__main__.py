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
from .config import AppConfig, load_config
from .core.health import RigState
from .core.rigs import RigRegistry
from .hub import Hub
from .logging_setup import setup_logging
from .net.udp import PortInUseError, UdpListener, bind_socket
from .tools.recorder import Recorder
from .tools.replay import replay

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

    parser = argparse.ArgumentParser(prog="simtelemetry", description="Sim racing cafe telemetry hub")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", parents=[common], help="hub + API (dashboard added in a later step)")
    add_record_flags(p)
    p.add_argument("--duration", type=float, help="stop after this many seconds")

    p = sub.add_parser("listen", parents=[common], help="debug: no API, one status line per rig per second")
    add_record_flags(p)
    p.add_argument("--duration", type=float, help="stop after this many seconds")

    p = sub.add_parser("record", parents=[common], help="capture raw packets to file (health summary only)")
    p.add_argument("--out", type=Path, help="recordings directory (default: <data_dir>/recordings)")
    p.add_argument("--duration", type=float, help="stop after this many seconds")

    p = sub.add_parser("replay", parents=[common], help="replay recordings through the pipeline")
    p.add_argument("files", nargs="+", type=Path, help=".f1rec files, replayed in the order given")
    p.add_argument("--speed", type=float, default=1.0, help="1 = real time, 0 = as fast as possible")
    p.add_argument("--no-api", action="store_true", help="don't serve the HTTP API while replaying")
    p.add_argument("--hold", action="store_true", help="keep serving the API after the replay ends")
    p.add_argument("--quiet", action="store_true", help="don't print per-rig status lines")
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


async def run_hub(args: argparse.Namespace, hub: Hub) -> None:
    cmd = args.command
    net = hub.config.network
    serve_api = cmd == "run" or (cmd == "replay" and not args.no_api)
    print_lines = cmd == "listen" or (cmd == "replay" and not args.quiet)

    # Bind everything first so a taken port fails before anything starts.
    http_sock = bind_socket(socket.SOCK_STREAM, net.http_host, net.http_port) if serve_api else None
    listener = None
    if cmd != "replay":
        listener = UdpListener(net.udp_host, net.udp_port, net.udp_receive_buffer_bytes, hub.on_datagram)
        try:
            await listener.start()
        except PortInUseError:
            if http_sock:
                http_sock.close()
            raise

    if hub.recorder is not None:
        hub.recorder.start()
    tasks = [asyncio.create_task(hub.consume()), asyncio.create_task(hub.tick_health())]
    if print_lines:
        tasks.append(asyncio.create_task(print_status_lines(hub)))
    server = server_task = None
    if http_sock is not None:
        server = uvicorn.Server(uvicorn.Config(create_app(hub), log_level="warning", lifespan="off"))
        server_task = asyncio.create_task(server.serve(sockets=[http_sock]))
        log.info("API on http://%s:%d/api/health", "localhost" if net.http_host == "0.0.0.0" else net.http_host,
                 net.http_port)

    try:
        if cmd == "replay":
            await replay(args.files, hub.on_datagram, args.speed)
            await hub.drain()
            hub.health.tick(time.monotonic())
            for line in hub.summary_lines(time.monotonic()):
                log.info("%s", line)
            if args.hold and server_task is not None:
                await server_task
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
    config = apply_overrides(load_config(args.config), args)
    setup_logging(config.data_dir / "logs", args.verbose)

    registry = RigRegistry(config, config.data_dir / "rigs.json")
    recorder = None
    if should_record(args, config):
        out = getattr(args, "out", None) or config.data_dir / "recordings"
        recorder = Recorder(out, config.recorder.max_file_mb * 1024 * 1024, config.recorder.keep_files)
    hub = Hub(config, F1Adapter(config.track_names), registry, recorder)

    exit_code = 0
    try:
        asyncio.run(run_hub(args, hub))
    except PortInUseError as exc:
        print(f"\nERROR: {port_in_use_message(exc)}\n", file=sys.stderr)
        exit_code = 2
    except KeyboardInterrupt:
        log.info("Stopping")
    finally:
        if recorder is not None:
            recorder.close()
        registry.save()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
