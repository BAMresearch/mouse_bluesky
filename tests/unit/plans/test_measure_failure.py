from pathlib import Path
from threading import Event, Thread, Timer

import pytest
from bluesky import RunEngine
from bluesky import plan_stubs as bps
from bluesky import preprocessors as bpp
from bluesky.utils import RunEngineInterrupted
from ophyd import Signal
from ophyd.status import Status
from ophyd.utils import DisconnectedError

from mouse_bluesky.plans import shutter as shutter_plans
from mouse_bluesky.plans.configure import build_baseline_signals
from mouse_bluesky.plans.public import measure_yzstage
from tests.unit.plans.support import build_startup_namespace


class RecordingShutter(Signal):
    def __init__(self):
        super().__init__(name="cu_shutter", value=0)
        self.writes = []
        self.timeouts = []
        self.open_error = None
        self.close_error = RuntimeError("strict shutter close failed")
        self.close_fault = None
        self.statuses = []
        self.timers = []

    def set(self, value, *, timeout=None, **kwargs):
        self.writes.append(value)
        self.timeouts.append(timeout)
        if value == 1 and self.open_error is not None:
            raise self.open_error
        if value == 0:
            if self.close_fault == "first_close_raises" and self.writes.count(0) == 1:
                raise self.close_error
            if self.close_fault == "raises":
                raise RuntimeError("shutter close rejected")
            if self.close_fault in ("fails_later", "never_completes"):
                assert timeout is not None  # The simulated status must honour the plan's timeout.
                status = Status(self, timeout=timeout)
                self.statuses.append(status)
                if self.close_fault == "fails_later":
                    timer = Timer(0.005, status.set_exception, args=(RuntimeError("shutter close failed"),))
                    self.timers.append(timer)
                    timer.start()
                return status
        return super().set(value, timeout=timeout, **kwargs)


class MeasurementRig:
    def __init__(self, root):
        self.root = root
        self.namespace = build_startup_namespace(include_sensors=True, include_eiger=True)
        self.shutter = RecordingShutter()
        self.namespace["cu_generator"].shutter = self.shutter
        self.beam_stop = self.namespace["beam_stop"]
        self.in_position = self.beam_stop.bsr.position
        self.RE = RunEngine({})
        self.docs = []
        self.messages = []
        self.RE.subscribe(lambda name, doc: self.docs.append((name, doc)))
        self.RE.msg_hook = self.messages.append
        self.exposures = []
        self.fail_at = None
        self.measure_error = RuntimeError("exposure failed")
        self.failure_message_index = None
        self.on_failure = None
        self.first_exposure_sleep_s = 0

    def acquire(self, eiger, destination, *, exposure_time):
        self.exposures.append(destination)
        yield from bps.sleep(self.first_exposure_sleep_s if len(self.exposures) == 1 else 0)
        if len(self.exposures) == self.fail_at:
            self.failure_message_index = len(self.messages)
            if self.on_failure is not None:
                self.on_failure()
            raise self.measure_error

    def plan(self):
        return measure_yzstage(root_path=self.root.as_posix(), namespace=self.namespace)

    def install_baseline(self):
        sd = bpp.SupplementalData()
        sd.baseline = build_baseline_signals(namespace=self.namespace)
        self.RE.preprocessors.append(sd)

    @property
    def stop_doc(self):
        stops = [doc for name, doc in self.docs if name == "stop"]
        assert len(stops) == 1
        return stops[0]

    def assert_incomplete(self):
        assert not list(self.root.rglob("COMPLETE"))

    def assert_failed(self, error):
        assert self.stop_doc["exit_status"] == "fail"
        assert self.stop_doc["reason"] == str(error)
        self.assert_incomplete()


@pytest.fixture
def rig(tmp_path, monkeypatch):
    rig = MeasurementRig(tmp_path)
    monkeypatch.setattr("mouse_bluesky.plans.atomic.mouse_eiger_measure", rig.acquire)
    monkeypatch.setitem(shutter_plans.close_shutter_best_effort.__kwdefaults__, "timeout_s", 0.03)
    yield rig
    if rig.RE.state != "idle":
        rig.RE.halt()
    for timer in rig.shutter.timers:
        timer.join(timeout=1)
        assert not timer.is_alive()
    for status in rig.shutter.statuses:
        if not status.done:
            status.set_finished()


def test_success_uses_only_strict_shutter_close_and_writes_complete(rig):
    rig.RE(rig.plan())

    assert rig.shutter.writes == [1, 0]
    assert rig.shutter.timeouts == [None, None]
    assert rig.shutter.get() == 0
    assert rig.stop_doc["exit_status"] == "success"
    start = next(doc for name, doc in rig.docs if name == "start")
    assert (Path(start["destination"]) / "COMPLETE").read_text() == "ok\n"
    assert len(rig.exposures) == 3


@pytest.mark.parametrize("exposure", [1, 2, 3])
def test_exposure_failure_closes_shutter_and_adds_no_motor_move(rig, exposure):
    rig.fail_at = exposure
    rig.measure_error = RuntimeError(f"exposure {exposure} failed")

    with pytest.raises(RuntimeError) as exc:
        rig.RE(rig.plan())

    assert exc.value is rig.measure_error
    assert rig.shutter.writes == [1, 0]
    assert rig.shutter.get() == 0
    rig.assert_failed(rig.measure_error)
    later_sets = [msg for msg in rig.messages[rig.failure_message_index :] if msg.command == "set"]
    assert len(later_sets) == 1
    assert later_sets[0].obj is rig.shutter
    expected = rig.beam_stop.out_position if exposure < 3 else rig.in_position
    assert rig.beam_stop.bsr.position == expected


def test_state_file_failure_closes_shutter_and_records_failure(rig, monkeypatch):
    error = OSError("state file write failed")

    def failed_write(**kwargs):
        raise error

    monkeypatch.setattr("mouse_bluesky.plans.atomic.write_im_craw_nxs", failed_write)
    with pytest.raises(OSError) as exc:
        rig.RE(rig.plan())

    assert exc.value is error
    assert rig.shutter.writes == [1, 0]
    assert rig.shutter.get() == 0
    rig.assert_failed(error)


def test_failed_shutter_open_still_attempts_close_and_preserves_error(rig):
    error = rig.shutter.open_error = DisconnectedError("shutter open failed")

    with pytest.raises(DisconnectedError) as exc:
        rig.RE(rig.plan())

    assert exc.value is error
    assert rig.shutter.writes == [1, 0]
    assert rig.shutter.get() == 0
    rig.assert_failed(error)


@pytest.mark.parametrize("fault", ["raises", "fails_later", "never_completes"])
def test_best_effort_close_fault_preserves_measurement_error(rig, capsys, fault):
    rig.fail_at = 1
    rig.shutter.close_fault = fault

    with pytest.raises(RuntimeError) as exc:
        rig.RE(rig.plan())

    assert exc.value is rig.measure_error
    assert rig.shutter.writes == [1, 0]
    assert rig.shutter.timeouts[-1] == 0.03
    rig.assert_failed(rig.measure_error)
    warning = capsys.readouterr().out
    assert f"Warning: could not confirm {rig.shutter.name} shutter closed:" in warning


def test_failed_strict_close_fails_measurement_and_retries_once(rig):
    rig.shutter.close_fault = "first_close_raises"

    with pytest.raises(RuntimeError) as exc:
        rig.RE(rig.plan())

    assert exc.value is rig.shutter.close_error
    assert len(rig.exposures) == 3
    assert rig.shutter.writes == [1, 0, 0]
    assert rig.shutter.timeouts == [None, None, 0.03]
    assert rig.shutter.get() == 0
    rig.assert_failed(rig.shutter.close_error)


def pause_measurement(rig):
    ready = Event()
    errors = []
    original_hook = rig.RE.msg_hook
    rig.first_exposure_sleep_s = 1

    def hook(msg):
        original_hook(msg)
        if msg.command == "sleep" and rig.shutter.get() == 1:
            ready.set()

    def pause():
        try:
            if not ready.wait(timeout=3):
                raise AssertionError("Measurement did not reach an exposure")
            rig.RE.request_pause(defer=False)
        except Exception as exc:
            errors.append(exc)

    rig.RE.msg_hook = hook
    thread = Thread(target=pause, daemon=True)
    thread.start()
    try:
        with pytest.raises(RunEngineInterrupted):
            rig.RE(rig.plan())
    finally:
        thread.join(timeout=3)
    assert not thread.is_alive()
    assert errors == []
    assert rig.RE.state == "paused"
    assert rig.shutter.get() == 1
    assert rig.shutter.writes == [1]
    assert not [doc for name, doc in rig.docs if name == "stop"]
    rig.assert_incomplete()


@pytest.mark.parametrize("method, status", [("abort", "abort"), ("stop", "success")])
def test_paused_measurement_closes_shutter_on_abort_or_stop(rig, method, status):
    pause_measurement(rig)
    getattr(rig.RE, method)()

    assert rig.RE.state == "idle"
    assert rig.shutter.writes == [1, 0]
    assert rig.shutter.get() == 0
    assert rig.stop_doc["exit_status"] == status
    rig.assert_incomplete()


def test_abort_status_survives_failed_shutter_close(rig, capsys):
    pause_measurement(rig)
    rig.shutter.close_fault = "raises"
    rig.RE.abort()

    assert rig.shutter.writes == [1, 0]
    assert rig.stop_doc["exit_status"] == "abort"
    assert f"Warning: could not confirm {rig.shutter.name} shutter closed:" in capsys.readouterr().out
    rig.assert_incomplete()


def test_halt_skips_close_and_leaves_shutter_open(rig):
    pause_measurement(rig)
    rig.RE.halt()

    assert rig.RE.state == "idle"
    assert rig.shutter.writes == [1]
    assert rig.shutter.get() == 1
    assert rig.stop_doc["exit_status"] == "abort"
    rig.assert_incomplete()


def test_resume_completes_measurement_and_closes_shutter(rig):
    pause_measurement(rig)
    rig.RE.resume()

    assert rig.RE.state == "idle"
    assert rig.shutter.get() == 0
    assert rig.stop_doc["exit_status"] == "success"
    assert len(list(rig.root.rglob("COMPLETE"))) == 1


def test_energy_failure_sends_no_shutter_command(rig):
    energy = rig.namespace["eiger"].cam.photon_energy
    energy.put(0)
    energy.respond_to_set = False

    with pytest.raises(RuntimeError, match=energy.name):
        rig.RE(rig.plan())

    assert rig.shutter.writes == []
    assert rig.exposures == []
    assert rig.docs == []
    rig.assert_incomplete()


def test_strict_baseline_failure_at_open_sends_no_shutter_command(rig, monkeypatch):
    rig.install_baseline()

    def failed_read():
        raise DisconnectedError("baseline open failed")

    monkeypatch.setattr(rig.namespace["pressure_gauge"].pressure, "read", failed_read)
    with pytest.raises(DisconnectedError, match="baseline open failed"):
        rig.RE(rig.plan())

    assert rig.shutter.writes == []
    assert rig.exposures == []
    rig.assert_failed(DisconnectedError("baseline open failed"))


def test_baseline_failure_at_close_does_not_prevent_shutter_cleanup(rig, monkeypatch):
    rig.install_baseline()
    rig.fail_at = 1

    def failed_read():
        raise DisconnectedError("baseline close failed")

    rig.on_failure = lambda: monkeypatch.setattr(rig.namespace["pressure_gauge"].pressure, "read", failed_read)
    with pytest.raises(DisconnectedError, match="baseline close failed"):
        rig.RE(rig.plan())

    assert rig.shutter.writes == [1, 0]
    assert rig.shutter.get() == 0
    assert rig.stop_doc["exit_status"] == "fail"
    rig.assert_incomplete()
