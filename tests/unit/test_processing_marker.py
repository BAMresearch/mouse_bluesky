import json
from datetime import datetime, timedelta

import pytest

from mouse_bluesky import processing_marker as pm


@pytest.fixture
def day(tmp_path):
    path = pm.ymd_dir(tmp_path, "20261118")
    path.mkdir(parents=True)
    return path


def test_scan_nested_files_excludes_hidden_marker_and_symlinks(day, tmp_path):
    sequence = day / "20261118_3_0"
    sequence.mkdir()
    nested = sequence / "nested"
    nested.mkdir()
    (nested / "image.h5").write_bytes(b"data")
    (sequence / "COMPLETE").write_text("ok\n")
    (day / ".keep").touch()
    (nested / ".partial").write_bytes(b"partial")
    (day / ".sync").mkdir()
    (day / ".sync" / "hidden.h5").touch()
    (day / pm.MARKER_NAME).write_text("old marker")
    (day / ".READY_FOR_PROCESSING.test.tmp").touch()
    (day / "file-link").symlink_to(nested / "image.h5")
    (day / "dir-link").symlink_to(sequence, target_is_directory=True)
    (day / "broken-link").symlink_to(tmp_path / "absent")
    (day / "loop").symlink_to(day, target_is_directory=True)

    files = pm.scan_ymd_dir(day)

    expected = {"20261118_3_0/COMPLETE": 3, "20261118_3_0/nested/image.h5": 4}
    assert {name: info[0] for name, info in files.items()} == expected
    for name, (_, mtime_ns) in files.items():
        assert mtime_ns == (day / name).stat().st_mtime_ns


def test_manifest_sorted_sizes_and_sequence_completion(day):
    for name in ("20261118_3_1", "20261118_3_0", ".hidden"):
        (day / name).mkdir()
    (day / "20261118_3_0" / "COMPLETE").write_text("ok\n")
    (day / "20261118_3_1" / "COMPLETE").symlink_to(day / "20261118_3_0" / "COMPLETE")
    (day / "alias").symlink_to(day / "20261118_3_0", target_is_directory=True)
    manifest = pm.build_manifest(day, day.name, "a" * 32, {"z.h5": (7, 100), "a.h5": (3, 200)})

    assert manifest["format"] == pm.MARKER_FORMAT
    assert manifest["marker_id"] == "a" * 32
    assert manifest["ymd"] == day.name
    assert datetime.fromisoformat(manifest["created"]).utcoffset() == timedelta(0)
    assert manifest["files"] == [{"path": "a.h5", "size": 3}, {"path": "z.h5", "size": 7}]
    assert manifest["sequences"] == [
        {"name": "20261118_3_0", "complete": True},
        {"name": "20261118_3_1", "complete": False},
    ]


def test_atomic_write_flushes_and_replaces_marker(day, monkeypatch):
    fsynced = []
    original_fsync = pm.os.fsync

    def fsync(fd):
        fsynced.append(fd)
        original_fsync(fd)

    monkeypatch.setattr(pm.os, "fsync", fsync)
    first = pm.build_manifest(day, day.name, "a" * 32, {})
    second = pm.build_manifest(day, day.name, "b" * 32, {})
    assert pm.write_marker_atomically(day, first) == day / pm.MARKER_NAME
    assert json.loads((day / pm.MARKER_NAME).read_text()) == first
    pm.write_marker_atomically(day, second)
    assert json.loads((day / pm.MARKER_NAME).read_text()) == second
    assert len(fsynced) == 2
    assert list(day.iterdir()) == [day / pm.MARKER_NAME]


@pytest.mark.parametrize("failure", ["replace", "fsync"])
def test_atomic_write_failure_cleans_temp_and_preserves_previous_marker(day, monkeypatch, failure):
    marker = day / pm.MARKER_NAME
    marker.write_text("previous marker")

    def fail(*args):
        raise OSError("disk failure")

    monkeypatch.setattr(pm.os, failure, fail)
    with pytest.raises(OSError, match="disk failure"):
        pm.write_marker_atomically(day, pm.build_manifest(day, day.name, "a" * 32, {}))
    assert marker.read_text() == "previous marker"
    assert list(day.iterdir()) == [marker]


@pytest.fixture
def published(day):
    (day / "sequence").mkdir()
    (day / "sequence" / "data.h5").write_bytes(b"12345")
    manifest = pm.build_manifest(day, day.name, "a" * 32, pm.scan_ymd_dir(day))
    pm.write_marker_atomically(day, manifest)
    return day, manifest


def test_readiness_ignores_extra_files_and_mtimes(published):
    day, manifest = published
    (day / "unlisted").write_bytes(b"extra")
    pm.os.utime(day / "sequence" / "data.h5", ns=(1, 1))
    assert pm.check_marker(day) == pm.MarkerCheck(True, manifest["marker_id"], [], [], None)


def test_absent_marker_is_not_ready(day):
    result = pm.check_marker(day)
    assert not result.ready
    assert result.marker_id is None
    assert result.problem


@pytest.mark.parametrize("content", ['{"format":', "[]", "null", '{"format": "unknown"}'])
def test_invalid_marker_is_not_ready(day, content):
    (day / pm.MARKER_NAME).write_text(content)
    result = pm.check_marker(day)
    assert not result.ready
    assert result.problem


@pytest.mark.parametrize(
    "update",
    [
        {"format": "unknown"},
        {"ymd": "20261119"},
        {"files": None},
        {"marker_id": None},
        {"files": [{"path": "../outside", "size": 1}]},
        {"files": [{"path": "/outside", "size": 1}]},
        {"files": [{"path": "data", "size": "1"}]},
    ],
)
def test_invalid_manifest_is_not_ready(published, update):
    day, manifest = published
    manifest.update(update)
    pm.write_marker_atomically(day, manifest)
    result = pm.check_marker(day)
    assert not result.ready
    assert result.problem


@pytest.mark.parametrize("state", ["missing", "smaller", "larger"])
def test_listed_files_must_exist_at_exact_size(published, state):
    day, manifest = published
    file = day / "sequence" / "data.h5"
    if state == "missing":
        file.unlink()
    else:
        file.write_bytes(b"1" if state == "smaller" else b"123456")
    result = pm.check_marker(day)
    assert not result.ready
    assert result.marker_id == manifest["marker_id"]
    assert result.missing == (["sequence/data.h5"] if state == "missing" else [])
    assert result.size_mismatch == ([] if state == "missing" else ["sequence/data.h5"])


def test_validate_ymd_accepts_real_date():
    assert pm.validate_ymd("20261118") is None


@pytest.mark.parametrize("ymd", ["20261232", "2026111", "2026-11-18", "20260230", "２０２６１１１８", None])
def test_validate_ymd_refuses_invalid_date(ymd):
    with pytest.raises(ValueError, match=str(ymd)):
        pm.validate_ymd(ymd)
