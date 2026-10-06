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
