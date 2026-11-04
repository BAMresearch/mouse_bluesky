import math
import time

import pytest
from bluesky import RunEngine
from bluesky import plan_stubs as bps
from bluesky import preprocessors as bpp
from ophyd import Signal
from ophyd.utils import DisconnectedError

from mouse_bluesky.plans import vacuum
from mouse_bluesky.plans.configure import (
    GENERATOR_BASELINE_SIGNALS,
    OptionalBaselineSignal,
    _resolve_dotted_name,
    apply_config,
    build_baseline_signals,
)
from mouse_bluesky.plans.public import measure_yzstage
from tests.unit.plans.support import build_startup_namespace


def test_build_baseline_signals_includes_base_optional_stages_and_generators():
    ns = build_startup_namespace(include_yz=True, include_gi=True, include_generators=True, include_sensors=True)

    baseline = build_baseline_signals(namespace=ns)

    assert [signal.signal if isinstance(signal, OptionalBaselineSignal) else signal for signal in baseline] == [
        ns["det_stage"].x,
        ns["det_stage"].y,
        ns["det_stage"].z,
        ns["beam_stop"].bsr,
        ns["beam_stop"].bsz,
        ns["dual"].dual,
        ns["s1"].bot,
        ns["s1"].top,
        ns["s1"].left,
        ns["s1"].right,
        ns["s2"].bot,
        ns["s2"].top,
        ns["s2"].left,
        ns["s2"].right,
        ns["s3"].bot,
        ns["s3"].top,
        ns["s3"].left,
        ns["s3"].right,
        ns["sample_stage_yz"].y,
        ns["sample_stage_yz"].z,
        ns["sample_stage_gi"].x,
        ns["sample_stage_gi"].y,
        ns["cu_generator"].voltage,
        ns["cu_generator"].current,
        ns["mo_generator"].voltage,
        ns["mo_generator"].current,
        ns["pressure_gauge"].pressure,
        ns["arduino"].temperature_env,
        ns["arduino"].temperature_stage,
    ]


def test_build_baseline_signals_skips_missing_optional_devices():
    ns = build_startup_namespace(include_yz=False, include_gi=False, include_generators=False, include_sensors=False)

    baseline = build_baseline_signals(namespace=ns)

    assert baseline == [
        ns["det_stage"].x,
        ns["det_stage"].y,
        ns["det_stage"].z,
        ns["beam_stop"].bsr,
        ns["beam_stop"].bsz,
        ns["dual"].dual,
        ns["s1"].bot,
        ns["s1"].top,
        ns["s1"].left,
        ns["s1"].right,
        ns["s2"].bot,
        ns["s2"].top,
        ns["s2"].left,
        ns["s2"].right,
        ns["s3"].bot,
        ns["s3"].top,
        ns["s3"].left,
        ns["s3"].right,
    ]


class SwitchableSignal(Signal):
    """Simulate an IOC that disconnects or fails a read during a session."""

    def __init__(self, *, name, value, pvname=None):
        self.online = True
        self.raise_on_read = False
        self.calls = dict.fromkeys(("read", "describe", "read_configuration", "describe_configuration", "get"), 0)
        self.set_attempts = []
        super().__init__(name=name, value=value)
        if pvname is not None:
            self.pvname = pvname

    @property
    def connected(self):
        return self.online

    def _check_connection(self):
        if not self.connected:
            raise DisconnectedError(f"{self.name} is disconnected")

    def get(self, **kwargs):
        self.calls["get"] += 1
        self._check_connection()
        return super().get(**kwargs)

    def read(self):
        self.calls["read"] += 1
        self._check_connection()
        if self.raise_on_read:
            raise DisconnectedError(f"{self.name} read failed while connected")
        return super().read()

    def describe(self):
        self.calls["describe"] += 1
        self._check_connection()
        return super().describe()

    def read_configuration(self):
        self.calls["read_configuration"] += 1
        self._check_connection()
        return super().read_configuration()

    def describe_configuration(self):
        self.calls["describe_configuration"] += 1
        self._check_connection()
        return super().describe_configuration()

    def set(self, value, **kwargs):
        self.set_attempts.append(value)
        self._check_connection()
        return super().set(value, **kwargs)


def _baseline_engine(signals):
    RE = RunEngine({})
    sd = bpp.SupplementalData()
    sd.baseline = signals
    RE.preprocessors.append(sd)
    docs = []
    RE.subscribe(lambda name, doc: docs.append((name, doc)))
    return RE, docs


@pytest.fixture
def baseline_run():
    ns = build_startup_namespace(include_sensors=True, include_eiger=True)
    for source in ("cu", "mo"):
        generator = ns[f"{source}_generator"]
        for field in ("voltage", "current", "shutter"):
            signal = getattr(generator, field)
            setattr(
                generator,
                field,
                SwitchableSignal(name=signal.name, value=signal.get(), pvname=f"source_{source}:{field}"),
            )
    RE, docs = _baseline_engine(build_baseline_signals(namespace=ns))
    return ns, RE, docs


def _audit_plan(change=None):
    def body():
        yield from bps.null()
        if change is not None:
            change()
        yield from bps.null()

    yield from bpp.run_wrapper(body())


def _baseline_events(docs):
    descriptors = {doc["uid"] for name, doc in docs if name == "descriptor" and doc["name"] == "baseline"}
    return [doc for name, doc in docs if name == "event" and doc["descriptor"] in descriptors]


def _disconnect_mo(ns):
    for field in ("voltage", "current", "shutter"):
        getattr(ns["mo_generator"], field).online = False


def test_only_generator_baseline_signals_are_wrapped(baseline_run):
    ns, RE, _ = baseline_run
    baseline = RE.preprocessors[0].baseline
    generator_signals = [_resolve_dotted_name(name, namespace=ns) for name in GENERATOR_BASELINE_SIGNALS]
    assert [entry.signal for entry in baseline if isinstance(entry, OptionalBaselineSignal)] == generator_signals
    for entry in baseline:
        if isinstance(entry, OptionalBaselineSignal):
            assert entry.name == entry.signal.name
            assert entry.parent is None
        else:
            assert entry not in generator_signals


def test_baseline_deduplicates_underlying_signals_before_wrapping(baseline_run):
    ns, _, _ = baseline_run
    ns["cu_generator"].voltage = ns["det_stage"].x
    ns["mo_generator"].current = ns["mo_generator"].voltage
    baseline = build_baseline_signals(namespace=ns)
    underlying = [entry.signal if isinstance(entry, OptionalBaselineSignal) else entry for entry in baseline]
    assert len(underlying) == len({id(signal) for signal in underlying})
    assert ns["det_stage"].x in baseline
    assert [entry.signal for entry in baseline if isinstance(entry, OptionalBaselineSignal)] == [
        ns["cu_generator"].current,
        ns["mo_generator"].voltage,
    ]


@pytest.mark.parametrize("state", ["up", "down", "crash", "read_error"])
def test_generator_baseline_survives_connection_changes(baseline_run, capsys, state):
    ns, RE, docs = baseline_run
    generator = ns["mo_generator"]
    signals = (generator.voltage, generator.current)
    if state == "down":
        _disconnect_mo(ns)
    elif state == "read_error":
        for signal in signals:
            signal.raise_on_read = True

    before = time.time()
    RE(_audit_plan(lambda: _disconnect_mo(ns) if state == "crash" else None))
    after = time.time()

    events = _baseline_events(docs)
    assert len(events) == 2
    assert [doc["exit_status"] for name, doc in docs if name == "stop"] == ["success"]
    assert len([doc for name, doc in docs if name == "descriptor" and doc["name"] == "baseline"]) == 1
    for index, event in enumerate(events):
        for signal, value in zip(signals, (50.0, 22.0), strict=True):
            unavailable = state in ("down", "read_error") or (state == "crash" and index == 1)
            if unavailable:
                assert math.isnan(event["data"][signal.name])
                assert before <= event["timestamps"][signal.name] <= after
            else:
                assert event["data"][signal.name] == value
    warning = capsys.readouterr().out
    for signal in signals:
        if state != "up":
            assert "Warning:" in warning
            assert signal.name in warning
        assert signal.calls["read"] == {"up": 2, "down": 0, "crash": 1, "read_error": 2}[state]
        assert signal.calls["describe"] == 0
        assert signal.calls["read_configuration"] == 0
        assert signal.calls["describe_configuration"] == 0


@pytest.mark.parametrize("pvname", [None, "source_mo:voltage"])
def test_optional_baseline_metadata_does_not_touch_offline_signal(pvname):
    signal = SwitchableSignal(name="mo_voltage", value=50.0, pvname=pvname)
    signal.online = False
    wrapper = OptionalBaselineSignal(signal)
    assert wrapper.signal is signal
    assert wrapper.name == signal.name
    assert wrapper.parent is None
    assert wrapper.describe() == {
        signal.name: {"source": f"PV:{pvname or signal.name}", "dtype": "number", "shape": []}
    }
    assert wrapper.read_configuration() == {}
    assert wrapper.describe_configuration() == {}
    assert wrapper.hints == {}
    assert not hasattr(wrapper, "trigger")
    description = wrapper.describe()
    signal.online = True
    assert wrapper.describe() == description
    signal.online = False
    RE, docs = _baseline_engine([wrapper])
    RE(_audit_plan())
    assert all(math.isnan(event["data"][signal.name]) for event in _baseline_events(docs))
    assert all(count == 0 for count in signal.calls.values())


@pytest.mark.parametrize("path", ["pressure_gauge.pressure", "det_stage.x", "arduino.temperature_env"])
@pytest.mark.parametrize("when", ["open", "close"])
def test_strict_baseline_read_failure_still_fails_run(baseline_run, monkeypatch, path, when):
    ns, RE, docs = baseline_run
    signal = _resolve_dotted_name(path, namespace=ns)

    def failed_read():
        raise DisconnectedError(f"{signal.name} read failed")

    def disconnect():
        monkeypatch.setattr(signal, "read", failed_read)

    if when == "open":
        disconnect()
    with pytest.raises(DisconnectedError, match=signal.name):
        RE(_audit_plan(disconnect if when == "close" else None))
    assert [doc["exit_status"] for name, doc in docs if name == "stop"] == ["fail"]


@pytest.mark.parametrize(
    "plan, target, valve_order, final_valves",
    [
        (vacuum.evacuate, 1, [("do7", 0), ("do6", 1)], (1, 0)),
        (vacuum.ventilate, 900, [("do6", 0), ("do7", 1), ("do7", 0)], (0, 0)),
    ],
)
def test_vacuum_plans_keep_valve_sequence_with_offline_mo_baseline(
    baseline_run, monkeypatch, plan, target, valve_order, final_valves
):
    ns, RE, docs = baseline_run
    _disconnect_mo(ns)
    ns["pressure_gauge"].pressure.put(target)
    do6 = ns["arduino"].digital_output_6 = Signal(name="do6", value=int(plan is vacuum.ventilate))
    do7 = ns["arduino"].digital_output_7 = Signal(name="do7", value=int(plan is vacuum.evacuate))
    valve_states = [(do6.get(), do7.get())]

    def record_valves(**kwargs):
        valve_states.append((do6.get(), do7.get()))

    do6.subscribe(record_valves, run=False)
    do7.subscribe(record_valves, run=False)
    monkeypatch.setattr(vacuum, "VENTILATE_PUMP_OFF_DELAY_S", 0)
    monkeypatch.setattr(vacuum, "VENTILATE_HOLD_S", 0)
    messages = []
    RE.msg_hook = messages.append

    RE(plan(namespace=ns))

    writes = [(msg.obj.name, msg.args[0]) for msg in messages if msg.command == "set"]
    assert writes == [("cu_shutter", 0), ("mo_shutter", 0), ("detx", 400), *valve_order]
    assert all(state != (1, 1) for state in valve_states)
    assert (do6.get(), do7.get()) == final_valves
    assert [doc["exit_status"] for name, doc in docs if name == "stop"] == ["success"]
    events = _baseline_events(docs)
    assert len(events) == 2
    assert all(math.isnan(event["data"]["mo_voltage"]) and math.isnan(event["data"]["mo_current"]) for event in events)


def test_apply_cu_config_with_offline_mo_baseline(baseline_run):
    ns, RE, docs = baseline_run
    _disconnect_mo(ns)

    RE(apply_config(config_id=123, config_root="tests/data/mouse_configs", namespace=ns))

    assert [doc["exit_status"] for name, doc in docs if name == "stop"] == ["success"]
    events = _baseline_events(docs)
    assert len(events) == 2
    assert all(math.isnan(event["data"]["mo_voltage"]) and math.isnan(event["data"]["mo_current"]) for event in events)


@pytest.mark.parametrize("offline", ["all", "voltage", "current"])
def test_active_mo_measurement_stays_strict_with_tolerant_baseline(baseline_run, tmp_path, offline):
    ns, RE, docs = baseline_run
    if offline == "all":
        _disconnect_mo(ns)
        failed_signal = ns["mo_generator"].shutter
    else:
        failed_signal = getattr(ns["mo_generator"], offline)
        failed_signal.online = False

    with pytest.raises(DisconnectedError, match=failed_signal.name):
        RE(measure_yzstage(config_id=223, root_path=tmp_path.as_posix(), namespace=ns))

    assert ns["mo_generator"].shutter.set_attempts == [1, 0]
    assert [doc["exit_status"] for name, doc in docs if name == "stop"] == ["fail"]
    assert len(_baseline_events(docs)) == 2
    assert not list(tmp_path.rglob("COMPLETE"))


def test_cu_measurement_with_offline_mo_baseline_succeeds(baseline_run, tmp_path, monkeypatch):
    ns, RE, docs = baseline_run
    _disconnect_mo(ns)

    def no_acquisition(*args, **kwargs):
        yield from ()

    monkeypatch.setattr("mouse_bluesky.plans.atomic.mouse_eiger_measure", no_acquisition)
    RE(measure_yzstage(config_id=123, root_path=tmp_path.as_posix(), namespace=ns))

    assert [doc["exit_status"] for name, doc in docs if name == "stop"] == ["success"]
    assert len(_baseline_events(docs)) == 2
    assert len(list(tmp_path.rglob("COMPLETE"))) == 1
