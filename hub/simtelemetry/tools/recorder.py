"""Raw packet recorder: every datagram as received, before any validation.

File format (.f1rec), little-endian:
    magic  b"SIMTREC1"
    repeated records:
        float64 wall-clock receive time (Unix seconds)
        uint8   source IP length, then that many ASCII bytes
        uint16  datagram length, then the datagram bytes

Writes go through a queue to a background thread, so the event loop never blocks on disk.
That thread also watches free disk space: below the warning threshold it logs a warning; below
the hard floor (or on any write error) it flushes, closes the file and stops recording, while the
hub keeps running.
"""

from __future__ import annotations

import logging
import queue
import shutil
import struct
import threading
import time
from collections.abc import Callable, Iterator
from enum import Enum
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

MAGIC = b"SIMTREC1"
EXTENSION = ".f1rec"
_TIME_IPLEN = struct.Struct("<dB")
_LEN = struct.Struct("<H")

_STOP = object()
GB = 1024 ** 3

STOPPED_LOW_DISK = "recording stopped: low disk"
STOPPED_WRITE_ERROR = "recording stopped: write error"


def disk_free_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


class RecorderState(str, Enum):
    RECORDING = "recording"
    LOW_DISK = "low_disk_warning"  # still recording, free space below the warning threshold
    STOPPED = "stopped"


class Recorder:
    def __init__(self, directory: Path, max_file_bytes: int = 256 * 1024 * 1024, keep_files: int = 24,
                 flush_interval_s: float = 1.0, warn_free_bytes: int = 5 * GB, stop_free_bytes: int = 1 * GB,
                 disk_check_interval_s: float = 30.0,
                 disk_free: Callable[[Path], int] = disk_free_bytes) -> None:
        self.directory = directory
        self.max_file_bytes = max_file_bytes
        self.keep_files = keep_files
        self.flush_interval_s = flush_interval_s
        self.warn_free_bytes = warn_free_bytes
        self.stop_free_bytes = stop_free_bytes
        self.disk_check_interval_s = disk_check_interval_s
        self._disk_free = disk_free
        self.current_path: Path | None = None
        self.records_written = 0
        self.state = RecorderState.RECORDING
        self.stop_message: str | None = None
        self.free_bytes: int | None = None
        self._stopped = False
        self._queue: queue.SimpleQueue = queue.SimpleQueue()
        self._thread: threading.Thread | None = None
        self._file = None
        self._file_bytes = 0
        self._seq = 0  # file number within this recorder session

    def start(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self._check_disk()
        if self._stopped:
            return  # already below the floor: no file is created
        try:
            self._open_new_file()
        except OSError as exc:
            self._stop(STOPPED_WRITE_ERROR, f"cannot create a recording in {self.directory}: {exc}")
            return
        self._thread = threading.Thread(target=self._run, name="recorder", daemon=True)
        self._thread.start()

    def write(self, wall_time: float, source_ip: str, data: bytes) -> None:
        """Called on the receive path: enqueue only (a no-op once recording has stopped)."""
        if not self._stopped:
            self._queue.put((wall_time, source_ip, data))

    def close(self) -> None:
        """Flush everything queued so far and close the file. Safe to call twice."""
        if self._thread is None:
            return
        self._queue.put(_STOP)
        self._thread.join()
        self._thread = None
        log.info("Recorder closed: %d packets written, last file %s", self.records_written, self.current_path)

    @property
    def stopped(self) -> bool:
        return self._stopped

    def status(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "message": self.stop_message,
            "directory": str(self.directory),
            "file": str(self.current_path) if self.current_path and not self._stopped else None,
            "free_gb": round(self.free_bytes / GB, 2) if self.free_bytes is not None else None,
            "warn_below_gb": round(self.warn_free_bytes / GB, 2),
            "stop_below_gb": round(self.stop_free_bytes / GB, 2),
            "packets_written": self.records_written,
        }

    def summary_line(self) -> str | None:
        """Console summary line, only when something needs attention."""
        free = f"{self.free_bytes / GB:.1f} GB free in {self.directory}" if self.free_bytes is not None else ""
        if self.state is RecorderState.STOPPED:
            return f"{self.stop_message} ({free})" if free else self.stop_message
        if self.state is RecorderState.LOW_DISK:
            return (f"WARNING: low disk space for recordings: {free} "
                    f"(recording stops below {self.stop_free_bytes / GB:g} GB)")
        return None

    # --- writer thread -----------------------------------------------------------

    def _run(self) -> None:
        last_flush = last_disk_check = time.monotonic()
        try:
            while not self._stopped:
                try:
                    item = self._queue.get(timeout=min(self.flush_interval_s, self.disk_check_interval_s))
                except queue.Empty:
                    item = None
                if item is _STOP:
                    break
                if item is not None:
                    self._write_record(*item)
                now = time.monotonic()
                if now - last_flush >= self.flush_interval_s:
                    self._file.flush()
                    last_flush = now
                if now - last_disk_check >= self.disk_check_interval_s:
                    self._check_disk()
                    last_disk_check = now
        except OSError as exc:
            self._stop(STOPPED_WRITE_ERROR, f"writing {self.current_path} failed: {exc}")
        finally:
            self._close_file()

    def _write_record(self, wall_time: float, source_ip: str, data: bytes) -> None:
        ip = source_ip.encode("ascii")
        record = _TIME_IPLEN.pack(wall_time, len(ip)) + ip + _LEN.pack(len(data)) + data
        if self._file_bytes + len(record) > self.max_file_bytes and self._file_bytes > len(MAGIC):
            self._file.close()
            self._check_disk()  # a new file is a natural point to re-check space
            if self._stopped:
                self._file = None
                return
            self._open_new_file()
        self._file.write(record)
        self._file_bytes += len(record)
        self.records_written += 1

    def _close_file(self) -> None:
        if self._file is None:
            return
        try:
            self._file.flush()
            self._file.close()
        except OSError as exc:
            log.error("Closing recording %s failed: %s", self.current_path, exc)
        self._file = None

    def _check_disk(self) -> None:
        try:
            free = self._disk_free(self.directory)
        except OSError as exc:
            log.warning("Cannot check free space for %s: %s", self.directory, exc)
            return
        self.free_bytes = free
        if free < self.stop_free_bytes:
            self._stop(STOPPED_LOW_DISK, f"only {free / GB:.2f} GB free in {self.directory} "
                                         f"(floor {self.stop_free_bytes / GB:g} GB)")
        elif free < self.warn_free_bytes:
            if self.state is not RecorderState.LOW_DISK:
                self.state = RecorderState.LOW_DISK
                log.warning("Low disk space for recordings: %.2f GB free in %s. Recording stops below %g GB.",
                            free / GB, self.directory, self.stop_free_bytes / GB)
        elif self.state is RecorderState.LOW_DISK:
            self.state = RecorderState.RECORDING
            log.info("Disk space for recordings recovered: %.2f GB free in %s", free / GB, self.directory)

    def _stop(self, message: str, detail: str) -> None:
        """Stop recording for good; the writer thread closes the file on its way out."""
        if self._stopped:
            return
        self._stopped = True
        self.state = RecorderState.STOPPED
        self.stop_message = message
        log.error("%s: %s. The hub keeps running without recording; last file %s (%d packets written).",
                  message, detail, self.current_path, self.records_written)

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
