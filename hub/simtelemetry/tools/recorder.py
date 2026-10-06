"""Raw packet recorder: every datagram as received, before any validation.

File format (.f1rec), little-endian:
    magic  b"SIMTREC1"
    repeated records:
        float64 wall-clock receive time (Unix seconds)
        uint8   source IP length, then that many ASCII bytes
        uint16  datagram length, then the datagram bytes

Writes go through a queue to a background thread, so the event loop never blocks on disk.
"""

from __future__ import annotations

import logging
import queue
import struct
import threading
import time
from collections.abc import Iterator
from pathlib import Path

log = logging.getLogger(__name__)

MAGIC = b"SIMTREC1"
EXTENSION = ".f1rec"
_TIME_IPLEN = struct.Struct("<dB")
_LEN = struct.Struct("<H")

_STOP = object()


class Recorder:
    def __init__(self, directory: Path, max_file_bytes: int = 256 * 1024 * 1024, keep_files: int = 24,
                 flush_interval_s: float = 1.0) -> None:
        self.directory = directory
        self.max_file_bytes = max_file_bytes
        self.keep_files = keep_files
        self.flush_interval_s = flush_interval_s
        self.current_path: Path | None = None
        self.records_written = 0
        self._queue: queue.SimpleQueue = queue.SimpleQueue()
        self._thread: threading.Thread | None = None
        self._file = None
        self._file_bytes = 0
        self._seq = 0  # file number within this recorder session

    def start(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self._open_new_file()
        self._thread = threading.Thread(target=self._run, name="recorder", daemon=True)
        self._thread.start()

    def write(self, wall_time: float, source_ip: str, data: bytes) -> None:
        """Called on the receive path: enqueue only."""
        self._queue.put((wall_time, source_ip, data))

    def close(self) -> None:
        """Flush everything queued so far and close the file. Safe to call twice."""
        if self._thread is None:
            return
        self._queue.put(_STOP)
        self._thread.join()
        self._thread = None
        log.info("Recorder closed: %d packets written, last file %s", self.records_written, self.current_path)

    # --- writer thread -----------------------------------------------------------

    def _run(self) -> None:
        last_flush = time.monotonic()
        while True:
            try:
                item = self._queue.get(timeout=self.flush_interval_s)
            except queue.Empty:
                item = None
            if item is _STOP:
                break
            if item is not None:
                self._write_record(*item)
            if time.monotonic() - last_flush >= self.flush_interval_s:
                self._file.flush()
                last_flush = time.monotonic()
        self._file.flush()
        self._file.close()

    def _write_record(self, wall_time: float, source_ip: str, data: bytes) -> None:
        ip = source_ip.encode("ascii")
        record = _TIME_IPLEN.pack(wall_time, len(ip)) + ip + _LEN.pack(len(data)) + data
        if self._file_bytes + len(record) > self.max_file_bytes and self._file_bytes > len(MAGIC):
            self._file.close()
            self._open_new_file()
        self._file.write(record)
        self._file_bytes += len(record)
        self.records_written += 1

    def _open_new_file(self) -> None:
        # <date>-<time>-<NNN>: names sort chronologically, even several rotations per second.
        stamp = time.strftime("%Y%m%d-%H%M%S")
        while True:
            self._seq += 1
            path = self.directory / f"{stamp}-{self._seq:03d}{EXTENSION}"
            if not path.exists():
                break
        self._file = path.open("wb", buffering=1024 * 1024)
        self._file.write(MAGIC)
        self._file_bytes = len(MAGIC)
        self.current_path = path
        log.info("Recording raw packets to %s", path)
        self._prune()

    def _prune(self) -> None:
        if self.keep_files <= 0:
            return
        files = sorted(self.directory.glob(f"*{EXTENSION}"))
        for old in files[: max(0, len(files) - self.keep_files)]:
            if old != self.current_path:
                old.unlink(missing_ok=True)
                log.info("Deleted old recording %s (keep_files=%d)", old.name, self.keep_files)


def read_recording(path: Path) -> Iterator[tuple[float, str, bytes]]:
    """Yield (wall_time, source_ip, datagram). A record truncated by a crash ends the file."""
    with path.open("rb") as f:
        if f.read(len(MAGIC)) != MAGIC:
            raise ValueError(f"{path} is not a recording (bad magic)")
        while True:
            head = f.read(_TIME_IPLEN.size)
            if len(head) < _TIME_IPLEN.size:
                return
            wall_time, ip_len = _TIME_IPLEN.unpack(head)
            ip = f.read(ip_len)
            raw_len = f.read(_LEN.size)
            if len(ip) < ip_len or len(raw_len) < _LEN.size:
                return
            (length,) = _LEN.unpack(raw_len)
            data = f.read(length)
            if len(data) < length:
                return
            yield wall_time, ip.decode("ascii"), data
