"""Replay recordings into the pipeline in-process, keeping each packet's original source IP
(a UDP re-send could not preserve it, so rig identity would be lost).

Packets can be filtered to one source (--from-ip) and remapped to another IP (--as-ip), e.g. to
play a recorded rig as "Rig 2" next to a live rig in the same hub.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from .recorder import read_recording

log = logging.getLogger(__name__)


class ReplayError(Exception):
    """Bad replay arguments or unreadable recording; the message is shown to the user as-is."""


@dataclass(frozen=True)
class SourceSelection:
    from_ip: str | None = None  # only replay packets from this source IP
    as_ip: str | None = None    # deliver them as if sent from this IP


def source_counts(paths: Iterable[Path]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for path in paths:
        try:
            for _, ip, _ in read_recording(path):
                counts[ip] += 1
        except (OSError, ValueError) as exc:
            raise ReplayError(f"Cannot read recording {path}: {exc}") from None
    return counts


def _check_ip(option: str, value: str) -> None:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        raise ReplayError(f"{option} '{value}' is not a valid IP address") from None


def select_source(paths: list[Path], from_ip: str | None, as_ip: str | None) -> SourceSelection:
    """Validate --from-ip / --as-ip against the recording's source IPs."""
    if as_ip is not None:
        _check_ip("--as-ip", as_ip)
    if from_ip is not None:
        _check_ip("--from-ip", from_ip)
    if as_ip is None and from_ip is None:
        return SourceSelection()

    counts = source_counts(paths)
    listing = ", ".join(f"{ip} ({n} packets)" for ip, n in counts.most_common()) or "none"
    if from_ip is not None and from_ip not in counts:
        raise ReplayError(f"The recording has no packets from {from_ip}. Source IPs in the recording: {listing}")
    if as_ip is not None and from_ip is None and len(counts) > 1:
        raise ReplayError(f"The recording contains {len(counts)} source IPs: {listing}. "
                          f"Choose which one to replay as {as_ip} with --from-ip.")
    return SourceSelection(from_ip, as_ip)


async def replay(paths: Iterable[Path], sink: Callable[[bytes, str, float], None], speed: float = 1.0,
                 selection: SourceSelection = SourceSelection()) -> int:
    """Feed recorded datagrams to sink(data, ip, wall_time).

    speed 1.0 = real time, 2.0 = twice as fast, 0 = as fast as possible.
    """
    loop = asyncio.get_running_loop()
    count = 0
    first_ts: float | None = None
    start = loop.time()
    for path in paths:
        log.info("Replaying %s", path)
        for wall_time, ip, data in read_recording(path):
            if selection.from_ip is not None and ip != selection.from_ip:
                continue
            if first_ts is None:
                first_ts = wall_time
            if speed > 0:
                delay = (wall_time - first_ts) / speed - (loop.time() - start)
                if delay > 0:
                    await asyncio.sleep(delay)
            elif count % 2000 == 0:
                await asyncio.sleep(0)  # let the consumer run
            sink(data, selection.as_ip or ip, wall_time)
            count += 1
    log.info("Replay finished: %d packets", count)
    return count


CLONE_NET = "10.30.0."  # --rigs: each copy plays as its own rig at 10.30.0.<n>
MIN_STREAM_PACKETS = 2000  # ignore sources that only sent a handful of packets


def load_streams(paths: Iterable[Path], from_ip: str | None = None) -> list[list[tuple[float, bytes]]]:
    """Each source IP of each recording (or only from_ip) as one stream of (wall_time, packet), in order."""
    streams: list[list[tuple[float, bytes]]] = []
    for path in paths:
        by_ip: dict[str, list[tuple[float, bytes]]] = {}
        try:
            for wall_time, ip, data in read_recording(path):
                if from_ip is None or ip == from_ip:
                    by_ip.setdefault(ip, []).append((wall_time, data))
        except (OSError, ValueError) as exc:
            raise ReplayError(f"Cannot read recording {path}: {exc}") from None
        streams += [s for s in by_ip.values() if len(s) >= MIN_STREAM_PACKETS]
    if not streams:
        raise ReplayError("The recordings have no source with enough packets to replay.")
    return streams


async def replay_rigs(streams: list[list[tuple[float, bytes]]], sink: Callable[[bytes, str, float], None], rigs: int,
                      speed: float = 1.0, stagger_s: float = 23.0) -> None:
    """Play `rigs` copies of the recorded streams at once, each as its own rig (10.30.0.1, .2, ...), every copy
    starting stagger_s later into its stream so the cars spread round the track. Loops until cancelled."""
    speed = speed if speed > 0 else 1.0

    async def one(n: int) -> None:
        stream = streams[(n - 1) % len(streams)]
        ip = f"{CLONE_NET}{n}"
        span = stream[-1][0] - stream[0][0]
        skip = ((n - 1) // len(streams) * stagger_s + (n - 1) * 3.0) % max(span, 1.0)
        loop = asyncio.get_running_loop()
        while True:
            start = loop.time()
            first = stream[0][0] + skip
            for wall_time, data in stream:
                if wall_time < first:
                    continue
                delay = (wall_time - first) / speed - (loop.time() - start)
                if delay > 0.002:
                    await asyncio.sleep(delay)
                sink(data, ip, wall_time)
            skip = 0.0

    await asyncio.gather(*(one(n) for n in range(1, rigs + 1)))
