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
