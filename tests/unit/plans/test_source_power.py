import math

import pytest
from bluesky import RunEngine
from ophyd.utils import DisconnectedError

from mouse_bluesky.plans.public import measure_yzstage
from mouse_bluesky.plans.source import (
    CU_SOURCE,
    MIN_SOURCE_POWER_FRACTION,
    MO_SOURCE,
    check_source_power,
    source_power_w,
)
from tests.unit.plans.support import build_startup_namespace


@pytest.mark.parametrize("source, current, watts", [(CU_SOURCE, 60, 30.0), (MO_SOURCE, 100, 50.0)])
def test_raw_source_power_and_nominal_power(source, current, watts):
    assert source_power_w(5000, current) == watts
    assert source.nominal_power_w == watts


@pytest.mark.parametrize("source, current, watts", [(CU_SOURCE, 54, 27.0), (MO_SOURCE, 90, 45.0)])
def test_exact_minimum_source_power_passes(source, current, watts):
    namespace = build_startup_namespace()
    generator = namespace[source.generator_name]
    generator.current.put(current)

    RunEngine({})(check_source_power(generator, source))

    assert source_power_w(5000, current) == watts == MIN_SOURCE_POWER_FRACTION * source.nominal_power_w


@pytest.mark.parametrize(
    "source, config_id, voltage, current",
    [
        (CU_SOURCE, 123, 5000, 53),
        (CU_SOURCE, 123, 4400, 60),
        (MO_SOURCE, 223, 5000, 89),
        (CU_SOURCE, 123, 0, 0),
        (MO_SOURCE, 223, 0, 0),
        *[
            (source, config_id, voltage, current)
            for source, config_id in ((CU_SOURCE, 123), (MO_SOURCE, 223))
            for nonfinite in (math.nan, math.inf, -math.inf)
            for voltage, current in ((nonfinite, 100), (5000, nonfinite))
        ],
    ],
)
def test_power_failure_leaves_no_measurement_output(tmp_path, source, config_id, voltage, current):
    namespace = build_startup_namespace(include_eiger=True)
    detector = namespace["eiger"]
    # Both energies would need a write if the energy guard were reached.
    detector.cam.photon_energy.put(0)
    detector.cam.threshold_energy.put(0)
    generator = namespace[source.generator_name]
    generator.voltage.put(voltage)
    generator.current.put(current)
    docs = []
    messages = []
    RE = RunEngine({})
    RE.subscribe(lambda name, doc: docs.append((name, doc)))
    RE.msg_hook = messages.append

    with pytest.raises(RuntimeError, match=generator.name) as exc:
        RE(measure_yzstage(config_id=config_id, root_path=tmp_path.as_posix(), namespace=namespace))

    message = str(exc.value)
    assert f"source power {source_power_w(voltage, current)} W" in message
    assert f"minimum {MIN_SOURCE_POWER_FRACTION * source.nominal_power_w} W" in message
    assert f"voltage_raw={voltage}" in message
    assert f"current_raw={current}" in message
    assert detector.writes == []
    assert docs == []
    assert list(tmp_path.iterdir()) == []
    assert not any(msg.command == "set" for msg in messages)
    assert [msg.obj for msg in messages if msg.command == "read"] == [generator.voltage, generator.current]


@pytest.mark.parametrize("source", [CU_SOURCE, MO_SOURCE])
@pytest.mark.parametrize("field", ["voltage", "current"])
def test_source_power_read_failure_propagates_unchanged(source, field, monkeypatch):
    generator = build_startup_namespace()[source.generator_name]
    signal = getattr(generator, field)
    error = DisconnectedError(f"{signal.name} disconnected")

    def failed_read():
        raise error

    monkeypatch.setattr(signal, "read", failed_read)
    with pytest.raises(DisconnectedError) as exc:
        RunEngine({})(check_source_power(generator, source))
    assert exc.value is error


def test_cu_measurement_checks_only_cu_once_before_shutter(tmp_path, monkeypatch):
    namespace = build_startup_namespace(include_eiger=True)
    cu = namespace["cu_generator"]
    mo = namespace["mo_generator"]
    mo.voltage.put(0)
    mo.current.put(0)
    messages = []
    RE = RunEngine({})
    RE.msg_hook = messages.append

    def no_acquisition(*args, **kwargs):
        # Source trips during exposure are outside this one-time check.
        cu.voltage.put(0)
        yield from ()

    monkeypatch.setattr("mouse_bluesky.plans.atomic.mouse_eiger_measure", no_acquisition)
    RE(measure_yzstage(config_id=123, root_path=tmp_path.as_posix(), namespace=namespace))

    reads = [(index, msg.obj) for index, msg in enumerate(messages) if msg.command == "read"]
    generator_reads = [(index, obj) for index, obj in reads if obj in (cu.voltage, cu.current, mo.voltage, mo.current)]
    assert [obj for _, obj in generator_reads] == [cu.voltage, cu.current]
    first_set = next(index for index, msg in enumerate(messages) if msg.command == "set")
    open_run = next(index for index, msg in enumerate(messages) if msg.command == "open_run")
    assert generator_reads[-1][0] < open_run < first_set
    assert len(list(tmp_path.rglob("COMPLETE"))) == 1
