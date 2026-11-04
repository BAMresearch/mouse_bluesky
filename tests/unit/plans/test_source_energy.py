from pathlib import Path
from shutil import copyfile

import pytest
from bluesky import RunEngine

from mouse_bluesky.devices.eiger import ENERGY_SET_TIMEOUT_S, ad_configure_energy
from mouse_bluesky.plans.configure import HDF5_OPHYD_MAP_BASE, _resolve_dotted_name, apply_config
from mouse_bluesky.plans.public import measure_yzstage
from mouse_bluesky.plans.source import CU_SOURCE, MO_SOURCE, source_settings_for_config_id
from tests.unit.plans.support import FakeEiger, build_startup_namespace


@pytest.fixture
def config_root(tmp_path: Path) -> str:
    root = tmp_path / "configs"
    root.mkdir()
    # Motor positions are irrelevant to source selection; reuse a complete config.
    for config_id in (123, 223):
        copyfile("tests/data/mouse_configs/123.nxs", root / f"{config_id}.nxs")
    return root.as_posix()


@pytest.mark.parametrize(
    "config_id, generator_name, photon_energy_ev, threshold_energy_ev",
    [
        (123, "cu_generator", 8050, 4025),
        (223, "mo_generator", 17480, 8740),
        (323, "cu_generator", 8050, 4025),
        (423, "mo_generator", 17480, 8740),
    ],
)
def test_source_settings(config_id, generator_name, photon_energy_ev, threshold_energy_ev):
    source = source_settings_for_config_id(config_id)
    assert source.generator_name == generator_name
    assert source.photon_energy_ev == photon_energy_ev
    assert source.threshold_energy_ev == threshold_energy_ev


def _assert_energy(detector, source):
    assert detector.cam.photon_energy.get() == source.photon_energy_ev
    assert detector.cam.threshold_energy.get() == source.threshold_energy_ev


def _expected_writes(source):
    return [("photon_energy", source.photon_energy_ev), ("threshold_energy", source.threshold_energy_ev)]


def test_fake_eiger_resets_threshold_on_photon_write():
    detector = FakeEiger()
    RunEngine({})(_write_photon_only(detector))
    assert detector.cam.threshold_energy.get() == 0


def _write_photon_only(detector):
    from bluesky import plan_stubs as bps

    yield from bps.abs_set(detector.cam.photon_energy, MO_SOURCE.photon_energy_ev, wait=True)


def test_apply_config_sets_mo_energy_in_order_after_motors(config_root):
    namespace = build_startup_namespace(include_eiger=True)
    detector = namespace["eiger"]
    docs = []
    messages = []
    RE = RunEngine({})
    RE.subscribe(lambda name, doc: docs.append((name, doc)))
    RE.msg_hook = messages.append

    RE(apply_config(config_id=223, config_root=config_root, namespace=namespace))

    _assert_energy(detector, MO_SOURCE)
    assert detector.writes == _expected_writes(MO_SOURCE)
    assert detector.set_timeouts == [ENERGY_SET_TIMEOUT_S, ENERGY_SET_TIMEOUT_S] == [60, 60]
    set_objects = [msg.obj for msg in messages if msg.command == "set"]
    assert len(set_objects) > 2  # Motors really moved before the detector settings.
    assert set_objects[-2:] == [detector.cam.photon_energy, detector.cam.threshold_energy]
    assert [name for name, _ in docs] == ["start", "stop"]
    assert docs[0][1]["photon_energy_ev"] == MO_SOURCE.photon_energy_ev
    assert docs[0][1]["threshold_energy_ev"] == MO_SOURCE.threshold_energy_ev
    assert docs[1][1]["exit_status"] == "success"


def test_apply_config_round_trip_and_measurement_guard_are_idempotent(config_root, tmp_path, monkeypatch):
    namespace = build_startup_namespace(include_eiger=True)
    detector = namespace["eiger"]
    RE = RunEngine({})

    def no_acquisition(*args, **kwargs):
        yield from ()

    monkeypatch.setattr("mouse_bluesky.plans.atomic.mouse_eiger_measure", no_acquisition)

    for config_id, source in ((223, MO_SOURCE), (123, CU_SOURCE), (223, MO_SOURCE)):
        detector.writes.clear()
        RE(apply_config(config_id=config_id, config_root=config_root, namespace=namespace))
        _assert_energy(detector, source)
        assert detector.writes == _expected_writes(source)

        RE(measure_yzstage(root_path=(tmp_path / "data").as_posix(), config_id=config_id, namespace=namespace))
        _assert_energy(detector, source)
        assert detector.writes == _expected_writes(source)  # Measurement added no energy writes.


@pytest.mark.parametrize("source", [CU_SOURCE, MO_SOURCE])
@pytest.mark.parametrize("photon_offset, threshold_offset", [(0, 0), (1, -1), (-1, 1), (0, 2), (2, 0)])
def test_energy_tolerance_and_rewriting_both_values(source, photon_offset, threshold_offset):
    detector = FakeEiger(
        photon_energy_ev=source.photon_energy_ev + photon_offset,
        threshold_energy_ev=source.threshold_energy_ev + threshold_offset,
    )

    RunEngine({})(
        ad_configure_energy(
            detector, photon_energy_ev=source.photon_energy_ev, threshold_energy_ev=source.threshold_energy_ev
        )
    )

    if abs(photon_offset) <= 1 and abs(threshold_offset) <= 1:
        assert detector.writes == []
    else:
        assert detector.writes == _expected_writes(source)
        _assert_energy(detector, source)


@pytest.mark.parametrize(
    "field, target, readback",
    [
        ("photon_energy", MO_SOURCE.photon_energy_ev, CU_SOURCE.photon_energy_ev),
        ("threshold_energy", MO_SOURCE.threshold_energy_ev, 0),
    ],
)
def test_apply_config_bad_energy_readback_fails_audit_run(config_root, field, target, readback):
    namespace = build_startup_namespace(include_eiger=True)
    detector = namespace["eiger"]
    signal = getattr(detector.cam, field)
    signal.respond_to_set = False
    docs = []
    RE = RunEngine({})
    RE.subscribe(lambda name, doc: docs.append((name, doc)))

    with pytest.raises(RuntimeError, match=rf"{signal.name}: target {target} eV, readback {readback} eV"):
        RE(apply_config(config_id=223, config_root=config_root, namespace=namespace))

    assert [name for name, _ in docs] == ["start", "stop"]
    assert docs[-1][1]["exit_status"] == "fail"
    assert signal.name in docs[-1][1]["reason"]


def test_apply_config_missing_detector_moves_no_motors(config_root):
    namespace = build_startup_namespace()
    axes = [_resolve_dotted_name(name, namespace=namespace) for name in HDF5_OPHYD_MAP_BASE.values()]
    before = [axis.position for axis in axes]
    messages = []
    RE = RunEngine({})
    RE.msg_hook = messages.append

    with pytest.raises(NameError, match="eiger"):
        RE(apply_config(config_id=223, config_root=config_root, namespace=namespace))

    assert [axis.position for axis in axes] == before
    assert not any(msg.command == "set" for msg in messages)


@pytest.mark.parametrize("field", ["photon_energy", "threshold_energy"])
def test_apply_config_energy_set_timeout_fails_audit_run(config_root, monkeypatch, field):
    namespace = build_startup_namespace(include_eiger=True)
    signal = getattr(namespace["eiger"].cam, field)
    timeouts = []

    def timed_out(value, *, timeout):
        timeouts.append(timeout)
        raise TimeoutError(f"{signal.name} timed out")

    monkeypatch.setattr(signal, "set", timed_out)
    docs = []
    RE = RunEngine({})
    RE.subscribe(lambda name, doc: docs.append((name, doc)))

    with pytest.raises(TimeoutError, match=signal.name):
        RE(apply_config(config_id=223, config_root=config_root, namespace=namespace))

    assert timeouts == [60]
    assert docs[-1][1]["exit_status"] == "fail"


@pytest.mark.parametrize("config_id, initial, target", [(223, CU_SOURCE, MO_SOURCE), (123, MO_SOURCE, CU_SOURCE)])
def test_measurement_alone_corrects_energy_before_shutter_opens(tmp_path, monkeypatch, config_id, initial, target):
    namespace = build_startup_namespace(include_eiger=True)
    detector = FakeEiger(photon_energy_ev=initial.photon_energy_ev, threshold_energy_ev=initial.threshold_energy_ev)
    namespace["eiger"] = detector
    shutter = namespace[target.generator_name].shutter
    energy_at_shutter_open = []

    def check_shutter(*, value, **kwargs):
        if value == 1:
            energy_at_shutter_open.append((detector.cam.photon_energy.get(), detector.cam.threshold_energy.get()))

    shutter.subscribe(check_shutter, run=False)

    def no_acquisition(*args, **kwargs):
        _assert_energy(detector, target)
        yield from ()

    monkeypatch.setattr("mouse_bluesky.plans.atomic.mouse_eiger_measure", no_acquisition)
    RunEngine({})(measure_yzstage(root_path=tmp_path.as_posix(), config_id=config_id, namespace=namespace))

    assert energy_at_shutter_open == [(target.photon_energy_ev, target.threshold_energy_ev)]
    assert detector.writes == _expected_writes(target)
    assert shutter.get() == 0


@pytest.mark.parametrize("field", ["photon_energy", "threshold_energy"])
@pytest.mark.parametrize("failure", ["readback", "timeout"])
def test_measurement_energy_failure_opens_no_shutter_or_directory(tmp_path, monkeypatch, field, failure):
    namespace = build_startup_namespace(include_eiger=True)
    signal = getattr(namespace["eiger"].cam, field)
    if failure == "readback":
        signal.respond_to_set = False
        error = RuntimeError
    else:

        def timed_out(value, *, timeout):
            assert timeout == 60
            raise TimeoutError(f"{signal.name} timed out")

        monkeypatch.setattr(signal, "set", timed_out)
        error = TimeoutError

    shutter_values = []
    for source in (CU_SOURCE, MO_SOURCE):
        namespace[source.generator_name].shutter.subscribe(
            lambda *, value, **kwargs: shutter_values.append(value), run=False
        )

    with pytest.raises(error, match=signal.name):
        RunEngine({})(measure_yzstage(root_path=tmp_path.as_posix(), config_id=223, namespace=namespace))

    assert shutter_values == []
    assert list(tmp_path.iterdir()) == []
