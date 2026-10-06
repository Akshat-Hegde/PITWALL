"""Replay recordings into the pipeline in-process, keeping each packet's original source IP
(a UDP re-send could not preserve it, so rig identity would be lost)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable
from pathlib import Path

from .recorder import read_recording

log = logging.getLogger(__name__)


async def replay(paths: Iterable[Path], sink: Callable[[bytes, str, float], None], speed: float = 1.0) -> int:
    """Feed every recorded datagram to sink(data, ip, wall_time).

    speed 1.0 = real time, 2.0 = twice as fast, 0 = as fast as possible.
    """
    loop = asyncio.get_running_loop()
    count = 0
    first_ts: float | None = None
    start = loop.time()
    for path in paths:
        log.info("Replaying %s", path)
        for wall_time, ip, data in read_recording(path):
            if first_ts is None:
                first_ts = wall_time
            if speed > 0:
                delay = (wall_time - first_ts) / speed - (loop.time() - start)
                if delay > 0:
                    await asyncio.sleep(delay)
            elif count % 2000 == 0:
                await asyncio.sleep(0)  # let the consumer run
            sink(data, ip, wall_time)
            count += 1
    log.info("Replay finished: %d packets", count)
    return count
