import time

import pytest

from simtelemetry.tools.recorder import MAGIC, Recorder, read_recording


def test_round_trip_and_flush_on_close(tmp_path):
    rec = Recorder(tmp_path, flush_interval_s=60)  # long interval: close() must still flush
    rec.start()
    packets = [(1000.0 + i, f"192.168.1.{10 + i % 2}", bytes([i % 256]) * (29 + i)) for i in range(500)]
    for p in packets:
        rec.write(*p)
    rec.close()
    assert rec.records_written == 500
    assert list(read_recording(rec.current_path)) == packets


def test_close_twice_is_safe(tmp_path):
    rec = Recorder(tmp_path)
    rec.start()
    rec.close()
    rec.close()


def test_periodic_flush_without_close(tmp_path):
    rec = Recorder(tmp_path, flush_interval_s=0.05)
    rec.start()
    rec.write(1.0, "10.0.0.1", b"x" * 40)
    deadline = time.monotonic() + 2
    while rec.current_path.stat().st_size <= len(MAGIC) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert rec.current_path.stat().st_size > len(MAGIC)
    rec.close()


def test_rotation_and_pruning(tmp_path):
    rec = Recorder(tmp_path, max_file_bytes=2000, keep_files=3)
    rec.start()
    for i in range(100):  # ~1500 bytes of records per file at this size -> many files
        rec.write(float(i), "10.0.0.1", b"y" * 100)
    rec.close()
    files = sorted(tmp_path.glob("*.f1rec"))
    assert len(files) == 3
    assert all(f.stat().st_size <= 2000 for f in files)
    # The newest files are kept: the last record must be present.
    replayed = [r for f in files for r in read_recording(f)]
    assert replayed[-1][0] == 99.0


def test_truncated_tail_is_ignored(tmp_path):
    rec = Recorder(tmp_path)
    rec.start()
    rec.write(1.0, "10.0.0.1", b"a" * 50)
    rec.write(2.0, "10.0.0.1", b"b" * 50)
    rec.close()
    path = rec.current_path
    path.write_bytes(path.read_bytes()[:-10])  # simulate a crash mid-write
    assert [r[0] for r in read_recording(path)] == [1.0]


def test_bad_magic(tmp_path):
    p = tmp_path / "x.f1rec"
    p.write_bytes(b"notarecording")
    with pytest.raises(ValueError):
        list(read_recording(p))


# --- free disk space thresholds ------------------------------------------------------------

import logging  # noqa: E402

from simtelemetry.tools.recorder import GB, STOPPED_LOW_DISK, RecorderState  # noqa: E402


class FakeDisk:
    def __init__(self, free_gb: float):
        self.free = int(free_gb * GB)

    def __call__(self, path):
        return self.free


def wait_for(condition, timeout=3.0):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert condition()


def make(tmp_path, disk, **kw):
    return Recorder(tmp_path, flush_interval_s=0.02, disk_check_interval_s=0.02, warn_free_bytes=5 * GB,
                    stop_free_bytes=1 * GB, disk_free=disk, **kw)


def test_below_floor_at_start_never_records(tmp_path, caplog):
    rec = make(tmp_path, FakeDisk(0.5))
    with caplog.at_level(logging.ERROR):
        rec.start()
    assert rec.stopped and rec.state is RecorderState.STOPPED
    assert rec.status()["message"] == STOPPED_LOW_DISK
    assert not list(tmp_path.glob("*.f1rec"))
    rec.write(1.0, "10.0.0.1", b"x" * 40)  # no-op
    rec.close()
    assert "recording stopped: low disk" in caplog.text and "keeps running" in caplog.text


def test_warning_threshold_logs_once_and_keeps_recording(tmp_path, caplog):
    disk = FakeDisk(3.0)  # between floor (1 GB) and warning (5 GB)
    rec = make(tmp_path, disk)
    with caplog.at_level(logging.INFO):
        rec.start()
        assert rec.state is RecorderState.LOW_DISK
        for i in range(20):
            rec.write(float(i), "10.0.0.1", b"y" * 40)
            time.sleep(0.005)  # spans several disk checks
        assert rec.summary_line().startswith("WARNING: low disk space for recordings: 3.0 GB free")
        disk.free = 50 * GB
        wait_for(lambda: rec.state is RecorderState.RECORDING)
        rec.close()
    assert caplog.text.count("Low disk space for recordings") == 1
    assert "Disk space for recordings recovered" in caplog.text
    assert rec.summary_line() is None
    assert len(list(read_recording(rec.current_path))) == 20  # nothing lost while warning


def test_floor_during_recording_stops_cleanly(tmp_path):
    disk = FakeDisk(50.0)
    rec = make(tmp_path, disk)
    rec.start()
    first = [(float(i), "10.0.0.1", bytes([i]) * 40) for i in range(10)]
    for item in first:
        rec.write(*item)
    wait_for(lambda: rec.records_written == 10)
    path = rec.current_path

    disk.free = int(0.5 * GB)
    wait_for(lambda: rec.stopped)
    wait_for(lambda: rec._file is None)  # flushed and closed by the writer thread
    for i in range(10):
        rec.write(100.0 + i, "10.0.0.1", b"late" * 10)  # ignored after the stop
    rec.close()

    assert list(read_recording(path)) == first
    status = rec.status()
    assert status["state"] == "stopped" and status["message"] == STOPPED_LOW_DISK
    assert status["file"] is None and status["free_gb"] == 0.5
    assert rec.summary_line() == f"recording stopped: low disk (0.5 GB free in {tmp_path})"
    path.rename(path.with_suffix(".moved"))  # Windows refuses this if the file were still open


def test_write_error_stops_cleanly(tmp_path):
    rec = make(tmp_path, FakeDisk(50.0))
    rec.start()

    class FailingFile:
        def write(self, data):
            raise OSError(28, "No space left on device")

        def flush(self):
            pass

        def close(self):
            pass

    real = rec._file
    rec._file = FailingFile()
    real.close()
    rec.write(1.0, "10.0.0.1", b"z" * 40)
    wait_for(lambda: rec.stopped)
    rec.close()
    assert rec.status()["message"] == "recording stopped: write error"
