import json
import runpy
from threading import Event, Thread

import pytest
from bluesky.utils import RunEngineInterrupted

from mouse_bluesky.plans import processing
from mouse_bluesky.processing_marker import MARKER_NAME, check_marker, ymd_dir

YMD = "20261118"


@pytest.fixture
def engine():
    re = runpy.run_path("qserver_profile/profile_mouse/startup/01_re.py")["RE"]
    docs = []
    re.subscribe(lambda name, doc: docs.append((name, doc)))
    return re, docs


@pytest.fixture
def data(tmp_path):
    day = ymd_dir(tmp_path, YMD)
    sequence = day / f"{YMD}_3_0"
    sequence.mkdir(parents=True)
    (sequence / "data.h5").write_bytes(b"data")
    (sequence / "COMPLETE").write_text("ok\n")
    return day


def plan(tmp_path, **kwargs):
    options = dict(ymd=YMD, root_path=str(tmp_path), settle_s=0.02, poll_interval_s=0.005, timeout_s=0.2)
    options.update(kwargs)
    return processing.mark_ymd_complete(**options)


def stop_document(docs):
    stops = [doc for name, doc in docs if name == "stop"]
    assert len(stops) == 1
    return stops[0]


def assert_no_marker(day):
    assert not (day / MARKER_NAME).exists()
    assert list(day.glob(".READY_FOR_PROCESSING.*.tmp")) == []


def test_success_has_manifest_audit_metadata_and_run_identity(engine, data, tmp_path, capsys):
    re, docs = engine
    re(plan(tmp_path))
    manifest = json.loads((data / MARKER_NAME).read_text())
    start = next(doc for name, doc in docs if name == "start")
    assert start["activity"] == "ymd_complete"
    assert start["ymd"] == YMD
    assert start["marker_id"] == manifest["marker_id"]
    assert len(start["marker_id"]) == 32
    assert start["marker_path"] == (data / MARKER_NAME).absolute().as_posix()
    assert start["facility"] == "BAM"
    assert start["instrument"] == "MOUSE"
    assert manifest["files"] == [{"path": f"{YMD}_3_0/COMPLETE", "size": 3}, {"path": f"{YMD}_3_0/data.h5", "size": 4}]
    assert manifest["sequences"] == [{"name": f"{YMD}_3_0", "complete": True}]
    assert check_marker(data).ready
    assert stop_document(docs)["exit_status"] == "success"
    assert f"Wrote {data / MARKER_NAME}: 2 files, 1 sequences" in capsys.readouterr().out
    assert list(data.glob(".*.tmp")) == []


def test_default_root_comes_from_settings(engine, data, tmp_path, monkeypatch):
    monkeypatch.setenv("MOUSE_DATA_ROOT", str(tmp_path))
    re, docs = engine
    re(plan(tmp_path, root_path=None))
    assert stop_document(docs)["exit_status"] == "success"
    assert check_marker(data).ready


@pytest.mark.parametrize("exists", [False, True])
def test_missing_or_empty_ymd_fails_without_creating_anything(engine, tmp_path, exists, capsys):
    day = ymd_dir(tmp_path, YMD)
    if exists:
        day.mkdir(parents=True)
        (day / ".keep").touch()
    re, docs = engine
    re(plan(tmp_path))
    stop = stop_document(docs)
    assert stop["exit_status"] == "fail"
    assert str(day) in stop["reason"]
    assert day.exists() is exists
    assert_no_marker(day)
    assert "Warning:" in capsys.readouterr().out


def test_continuously_changing_files_time_out_and_return(engine, data, tmp_path, monkeypatch):
    count = 0

    def changing(path):
        nonlocal count
        count += 1
        return {"data.h5": (count, count)}

    monkeypatch.setattr(processing, "scan_ymd_dir", changing)
    re, docs = engine
    re(plan(tmp_path, settle_s=0.04, timeout_s=0.06))
    stop = stop_document(docs)
    assert stop["exit_status"] == "fail"
    assert "Files kept changing" in stop["reason"]
    assert count > 1
    assert_no_marker(data)


def test_late_file_change_is_in_final_manifest(engine, data, tmp_path, monkeypatch):
    scanner = processing.scan_ymd_dir
    count = 0

    def late_write(path):
        nonlocal count
        count += 1
        if count == 2:
            (data / f"{YMD}_3_0" / "data.h5").write_bytes(b"final data")
        return scanner(path)

    monkeypatch.setattr(processing, "scan_ymd_dir", late_write)
    re, docs = engine
    re(plan(tmp_path))
    manifest = json.loads((data / MARKER_NAME).read_text())
    assert manifest["files"][1]["size"] == len(b"final data")
    assert count >= 3
    assert stop_document(docs)["exit_status"] == "success"


@pytest.mark.parametrize("operation", ["scan", "write"])
def test_oserror_is_a_failed_run_and_returns_normally(engine, data, tmp_path, monkeypatch, capsys, operation):
    def fail(*args):
        raise OSError("disk unavailable")

    if operation == "scan":
        monkeypatch.setattr(processing, "scan_ymd_dir", fail)
    else:
        monkeypatch.setattr("mouse_bluesky.processing_marker.os.replace", fail)
    re, docs = engine
    re(plan(tmp_path))
    stop = stop_document(docs)
    assert stop["exit_status"] == "fail"
    assert "disk unavailable" in stop["reason"]
    assert "Warning:" in capsys.readouterr().out
    assert_no_marker(data)


@pytest.mark.parametrize("method", ["abort", "halt"])
def test_interrupt_during_settle_writes_no_marker(engine, data, tmp_path, method):
    re, docs = engine
    ready = Event()
    errors = []

    def callback(msg):
        if msg.command == "sleep":
            ready.set()

    def pause():
        try:
            if not ready.wait(timeout=3):
                raise AssertionError("Plan did not reach settle sleep")
            re.request_pause(defer=False)
        except Exception as exc:
            errors.append(exc)

    re.msg_hook = callback
    thread = Thread(target=pause, daemon=True)
    thread.start()
    try:
        with pytest.raises(RunEngineInterrupted):
            re(plan(tmp_path, settle_s=5, poll_interval_s=1, timeout_s=10))
    finally:
        thread.join(timeout=3)
    assert not thread.is_alive()
    assert errors == []
    assert re.state == "paused"
    assert_no_marker(data)
    getattr(re, method)()
    assert re.state == "idle"
    assert stop_document(docs)["exit_status"] == "abort"
    assert_no_marker(data)


@pytest.mark.parametrize("ymd", ["20261232", "20260230", "2026111", "2026-11-18"])
def test_invalid_date_raises_before_filesystem_access_or_documents(engine, tmp_path, monkeypatch, ymd):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid date must be rejected before settings or filesystem access")

    monkeypatch.setattr(processing.Settings, "from_env", forbidden)
    monkeypatch.setattr(processing, "scan_ymd_dir", forbidden)
    re, docs = engine
    with pytest.raises(ValueError, match=ymd):
        re(processing.mark_ymd_complete(ymd=ymd))
    assert docs == []
    assert list(tmp_path.iterdir()) == []
