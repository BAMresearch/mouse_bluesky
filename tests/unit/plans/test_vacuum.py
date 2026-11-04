from collections import deque
from threading import Event, Thread, Timer
from types import SimpleNamespace

import pytest
from bluesky import RunEngine
from bluesky.utils import RunEngineInterrupted
from ophyd import Signal
from ophyd.status import Status

from mouse_bluesky.plans import vacuum


class RecordingSignal(Signal):
    def __init__(self, rig, *, name, value=0):
        super().__init__(name=name, value=value)
        self.rig = rig

    def set(self, value, *, timeout=None):
        self.rig.writes.append((self.name, value, timeout))
        self.rig.events.append((self.name, value))
        self.put(value)
        self.rig.record_valves()
        status = Status(self, timeout=timeout)
        status.set_finished()
        return status


class ScriptedPressure(Signal):
    def __init__(self):
        super().__init__(name="pressure", value=1)
        self.readings = deque()

    def read(self):
        if self.readings:
            value = self.readings.popleft()
            if isinstance(value, Exception):
                raise value
            self.put(value)
        return super().read()


class VacuumRig:
    def __init__(self):
        self.writes = []
        self.events = []
        self.valve_states = []
        self.timers = []
        self.shutter_statuses = []
        self.detx = RecordingSignal(self, name="detx")
        self.do6 = RecordingSignal(self, name="do6")
        self.do7 = RecordingSignal(self, name="do7")
        self.pressure = ScriptedPressure()
        self.namespace = {
            "det_stage": SimpleNamespace(x=self.detx),
            "arduino": SimpleNamespace(digital_output_6=self.do6, digital_output_7=self.do7),
            "pressure_gauge": SimpleNamespace(pressure=self.pressure),
            "cu_generator": SimpleNamespace(shutter=RecordingSignal(self, name="cu_shutter", value=1)),
            "mo_generator": SimpleNamespace(shutter=RecordingSignal(self, name="mo_shutter", value=1)),
        }
        self.docs = []
        self.messages = []
        self.RE = RunEngine({})
        self.RE.subscribe(lambda name, doc: self.docs.append((name, doc)))
        self.RE.msg_hook = self.record_message

    def record_message(self, msg):
        self.messages.append(msg)
        if msg.command == "sleep":
            self.events.append(("sleep", msg.args[0]))

    def record_valves(self):
        self.valve_states.append((self.do6.get(), self.do7.get()))

    def run(self, plan, *, pressures, **kwargs):
        self.pressure.readings = deque(pressures)
        return self.RE(plan(namespace=self.namespace, **kwargs))


@pytest.fixture
def rig(monkeypatch):
    for name, value in (
        ("EVACUATE_POLL_INTERVAL_S", 0.003),
        ("VENTILATE_POLL_INTERVAL_S", 0.001),
        ("VENTILATE_PUMP_OFF_DELAY_S", 0.001),
        ("VENTILATE_HOLD_S", 0.01),
        ("SHUTTER_CLOSE_TIMEOUT_S", 0.03),
    ):
        monkeypatch.setattr(vacuum, name, value)
    rig = VacuumRig()
    yield rig
    for timer in rig.timers:
        timer.join(timeout=1)
        assert not timer.is_alive()
    # Release simulated statuses left pending by an abort after assertions;
    # otherwise their timeout threads outlive the test.
    for status in rig.shutter_statuses:
        if not status.done:
            status.set_finished()
    rig.record_valves()
    assert all(state != (1, 1) for state in rig.valve_states)


def assert_audit(rig, activity, target, timeout, status):
    assert [name for name, _ in rig.docs] == ["start", "stop"]
    start, stop = [doc for _, doc in rig.docs]
    assert start["activity"] == activity
    assert start["target_pressure"] == target
    assert start["timeout_s"] == timeout
    assert stop["exit_status"] == status


def test_evacuate_success_and_exact_threshold(rig, capsys):
    rig.do7.put(1)
    rig.run(vacuum.evacuate, pressures=[1000, 20, 1])

    assert rig.events == [("cu_shutter", 0), ("mo_shutter", 0), ("detx", 400), ("do7", 0), ("do6", 1), ("sleep", 0.003)]
    assert (rig.do6.get(), rig.do7.get()) == (1, 0)
    assert_audit(rig, "evacuate", 1, 1800.0, "success")
    assert "current pressure: 1" in capsys.readouterr().out
    run_messages = [msg.command for msg in rig.messages]
    assert run_messages[run_messages.index("open_run") + 1] == "clear_checkpoint"
    assert [timeout for name, _, timeout in rig.writes if name.startswith("do")] == [30, 30]


def test_ventilate_success_and_exact_threshold(rig, capsys):
    rig.do6.put(1)
    rig.run(vacuum.ventilate, pressures=[1, 100, 900, 950])

    assert rig.events == [
        ("cu_shutter", 0),
        ("mo_shutter", 0),
        ("detx", 400),
        ("do6", 0),
        ("sleep", 0.001),
        ("do7", 1),
        ("sleep", 0.001),
        ("sleep", 0.01),
        ("do7", 0),
    ]
    assert (rig.do6.get(), rig.do7.get()) == (0, 0)
    assert_audit(rig, "ventilate", 900, 600.0, "success")
    assert "current pressure: 950" in capsys.readouterr().out
    run_messages = [msg.command for msg in rig.messages]
    assert run_messages[run_messages.index("open_run") + 1] == "clear_checkpoint"
    assert [timeout for name, _, timeout in rig.writes if name.startswith("do")] == [30, 30, 30]


@pytest.mark.parametrize(
    "plan, initial, pressures, expected",
    [
        (vacuum.evacuate, (1, 0), [1, 1], [("do7", 0), ("do6", 1)]),
        (vacuum.ventilate, (0, 1), [900, 900, 900], [("do6", 0), ("do7", 1), ("do7", 0)]),
    ],
)
def test_valves_are_written_even_when_already_at_target(rig, plan, initial, pressures, expected):
    rig.do6.put(initial[0])
    rig.do7.put(initial[1])
    rig.run(plan, pressures=pressures)
    assert [(name, value) for name, value, _ in rig.writes if name.startswith("do")] == expected


@pytest.mark.parametrize(
    "plan, closing, pressures",
    [(vacuum.evacuate, "do7", [1, 1]), (vacuum.ventilate, "do6", [900, 900, 900])],
)
def test_opposite_output_is_confirmed_off_before_enabling_next(rig, monkeypatch, plan, closing, pressures):
    signal = getattr(rig, closing)
    signal.put(1)
    statuses = []

    def delayed_close(value, *, timeout):
        assert value == 0
        assert timeout == 30
        rig.writes.append((signal.name, value, timeout))
        rig.events.append((signal.name, value))
        status = Status(signal, timeout=timeout)
        statuses.append(status)

        def complete():
            signal.put(value)
            rig.record_valves()
            status.set_finished()

        timer = Timer(0.01, complete)
        rig.timers.append(timer)
        timer.start()
        return status

    monkeypatch.setattr(signal, "set", delayed_close)
    rig.run(plan, pressures=pressures)
    assert statuses and all(status.done and status.success for status in statuses)


@pytest.mark.parametrize(
    "plan, last_pressure, target, final_valves",
    [(vacuum.evacuate, 20, 1, (1, 0)), (vacuum.ventilate, 100, 900, (0, 0))],
)
def test_timeout_fails_audit_and_preserves_required_valve_state(rig, plan, last_pressure, target, final_valves):
    with pytest.raises(TimeoutError, match=rf"last pressure {last_pressure}, target {target}"):
        rig.run(plan, pressures=[100, last_pressure], timeout_s=0)
    assert (rig.do6.get(), rig.do7.get()) == final_valves
    assert_audit(rig, plan.__name__, target, 0, "fail")


@pytest.mark.parametrize("plan, target, final_valves", [(vacuum.evacuate, 1, (1, 0)), (vacuum.ventilate, 900, (0, 0))])
@pytest.mark.parametrize("bad_pressure", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_polling_pressure_fails(rig, plan, target, final_valves, bad_pressure):
    with pytest.raises(ValueError, match="Non-finite pressure"):
        rig.run(plan, pressures=[100, bad_pressure])
    assert (rig.do6.get(), rig.do7.get()) == final_valves
    assert_audit(rig, plan.__name__, target, plan.__kwdefaults__["timeout_s"], "fail")


@pytest.mark.parametrize("pressures", [[1, OSError("gauge offline")], [1, 900, OSError("gauge offline")]])
def test_ventilate_gauge_read_failure_closes_vent_including_after_hold(rig, pressures):
    with pytest.raises(OSError, match="gauge offline"):
        rig.run(vacuum.ventilate, pressures=pressures)
    assert rig.do7.get() == 0
    assert_audit(rig, "ventilate", 900, 600.0, "fail")


@pytest.mark.parametrize("plan", [vacuum.evacuate, vacuum.ventilate])
@pytest.mark.parametrize("missing", ["det_stage", "arduino", "pressure_gauge"])
def test_missing_required_device_writes_nothing(rig, plan, missing):
    del rig.namespace[missing]
    with pytest.raises(ValueError, match=missing):
        rig.run(plan, pressures=[1])
    assert rig.writes == []
    assert rig.docs == []


@pytest.mark.parametrize("plan", [vacuum.evacuate, vacuum.ventilate])
@pytest.mark.parametrize("bad_pressure", [OSError("gauge offline"), float("nan"), float("inf")])
def test_bad_preflight_pressure_writes_nothing(rig, plan, bad_pressure):
    with pytest.raises((OSError, ValueError)):
        rig.run(plan, pressures=[bad_pressure])
    assert rig.writes == []
    assert rig.docs == []


@pytest.mark.parametrize("plan", [vacuum.evacuate, vacuum.ventilate])
@pytest.mark.parametrize("unreadable", ["detx", "do6", "do7"])
def test_other_preflight_read_failures_write_nothing(rig, monkeypatch, plan, unreadable):
    def read_failure():
        raise OSError(f"{unreadable} unreadable")

    monkeypatch.setattr(getattr(rig, unreadable), "read", read_failure)
    with pytest.raises(OSError, match=unreadable):
        rig.run(plan, pressures=[1])
    assert rig.writes == []
    assert rig.docs == []


class FaultyShutter(RecordingSignal):
    def __init__(self, rig, fault):
        super().__init__(rig, name="cu_shutter", value=1)
        self.fault = fault

    def set(self, value, *, timeout):
        self.rig.writes.append((self.name, value, timeout))
        self.rig.events.append((self.name, value))
        self.rig.record_valves()
        if self.fault == "raises":
            raise ConnectionError("shutter offline")
        status = Status(self, timeout=timeout)
        self.rig.shutter_statuses.append(status)
        if self.fault == "fails_later":
            timer = Timer(0.005, status.set_exception, args=(RuntimeError("shutter failed"),))
            self.rig.timers.append(timer)
            timer.start()
        return status


@pytest.mark.parametrize("plan, target", [(vacuum.evacuate, 1), (vacuum.ventilate, 900)])
@pytest.mark.parametrize("fault", ["raises", "fails_later", "never_completes", "missing", "missing_shutter"])
def test_shutter_fault_warns_and_still_closes_second_shutter(rig, capsys, plan, target, fault):
    if fault == "missing":
        del rig.namespace["cu_generator"]
    elif fault == "missing_shutter":
        rig.namespace["cu_generator"] = SimpleNamespace()
    else:
        rig.namespace["cu_generator"].shutter = FaultyShutter(rig, fault)

    rig.run(plan, pressures=[target, target, target])

    assert "Warning:" in capsys.readouterr().out
    assert ("mo_shutter", 0) in rig.events
    assert rig.events.index(("mo_shutter", 0)) < rig.events.index(("detx", 400))
    assert rig.do7.get() == 0
    assert_audit(rig, plan.__name__, target, plan.__kwdefaults__["timeout_s"], "success")


def interrupt_run(rig, plan, method, trigger):
    ready = Event()
    errors = []
    original_hook = rig.RE.msg_hook

    def hook(msg):
        original_hook(msg)
        if trigger(msg):
            ready.set()

    def interrupt():
        try:
            if not ready.wait(timeout=3):
                raise AssertionError("Plan did not reach the interruption point")
            if method == "pause":
                rig.RE.request_pause(defer=False)
            else:
                getattr(rig.RE, method)()
        except Exception as exc:
            errors.append(exc)

    rig.RE.msg_hook = hook
    thread = Thread(target=interrupt, daemon=True)
    thread.start()
    try:
        with pytest.raises(RunEngineInterrupted):
            rig.RE(plan(namespace=rig.namespace))
    finally:
        thread.join(timeout=3)
    assert not thread.is_alive()
    assert errors == []
    assert rig.RE.state == "idle"


@pytest.mark.parametrize("method, exit_status", [("stop", "success"), ("abort", "abort"), ("pause", "fail")])
def test_ventilate_interruption_closes_vent_and_does_not_leave_paused(rig, method, exit_status):
    rig.pressure.put(100)
    interrupt_run(
        rig,
        vacuum.ventilate,
        method,
        lambda msg: msg.command == "sleep" and rig.do7.get() == 1,
    )
    assert ("do7", 1) in rig.events
    assert rig.events[-1] == ("do7", 0)
    assert rig.do7.get() == 0
    assert rig.docs[-1][1]["exit_status"] == exit_status


def test_evacuate_abort_leaves_pump_running(rig):
    rig.pressure.put(100)
    interrupt_run(rig, vacuum.evacuate, "abort", lambda msg: msg.command == "sleep" and rig.do6.get() == 1)
    assert (rig.do6.get(), rig.do7.get()) == (1, 0)
    assert [(name, value) for name, value, _ in rig.writes if name == "do6"] == [("do6", 1)]
    assert rig.docs[-1][1]["exit_status"] == "abort"


@pytest.mark.parametrize("plan", [vacuum.evacuate, vacuum.ventilate])
def test_abort_during_shutter_wait_is_not_swallowed_and_writes_no_valve(rig, monkeypatch, plan):
    monkeypatch.setattr(vacuum, "SHUTTER_CLOSE_TIMEOUT_S", 1)
    rig.namespace["cu_generator"].shutter = FaultyShutter(rig, "never_completes")
    interrupt_run(rig, plan, "abort", lambda msg: msg.command == "wait")
    assert [(name, value) for name, value, _ in rig.writes] == [("cu_shutter", 0)]
    assert rig.docs[-1][1]["exit_status"] == "abort"
