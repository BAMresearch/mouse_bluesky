from pathlib import Path

import h5py
import pytest
from bluesky import RunEngine
from bluesky import preprocessors as bpp
from ophyd import Signal
from ophyd.sim import SynSignal, make_fake_device
from ophyd.utils import LimitError

from mouse_bluesky.devices.mouse_motors import MouseEpicsMotor
from mouse_bluesky.planner.logbook2bluesky import build_plan_specs
from mouse_bluesky.planner.materialize import materialize_plans
from mouse_bluesky.plans.configure import HDF5_OPHYD_MAP_BASE, apply_config, build_baseline_signals
from mouse_bluesky.plans.public import measure_yzstage
from mouse_bluesky.protocols.builtin import build_default_registry
from tests.unit.planner.test_triangulation import entry
from tests.unit.plans.support import build_startup_namespace

CONFIG_ROOT = Path("tests/data/mouse_configs")


@pytest.mark.parametrize(
    "overrides",
    [{}, {"detx": 500.0}, {"beam_stop_out": True}, {"detx": 0.0, "beam_stop_out": True}],
)
def test_apply_config_overrides_and_audit_preserve_other_file_values(overrides):
    ns = build_startup_namespace(include_eiger=True, include_gi=True)
    ns["beam_stop"].out_position = 246.8  # Deliberately different from the device's default.
    docs = []
    RE = RunEngine({})
    RE.subscribe(lambda name, doc: docs.append((name, doc)))
    RE(apply_config(config_id=123, config_root=str(CONFIG_ROOT), namespace=ns, **overrides))

    with h5py.File(CONFIG_ROOT / "123.nxs", "r") as f:
        for path, dotted in HDF5_OPHYD_MAP_BASE.items():
            root, attr = dotted.split(".")
            expected = float(f[path][()])
            if path == "/saxs/Saxslab/detx" and "detx" in overrides:
                expected = overrides["detx"]
            if path == "/saxs/Saxslab/bsr" and overrides.get("beam_stop_out"):
                expected = 246.8
            assert getattr(ns[root], attr).position == expected
    start = next(doc for name, doc in docs if name == "start")
    assert start["detx"] == overrides.get("detx")
    assert start["beam_stop_out"] is overrides.get("beam_stop_out", False)
    assert docs[-1][1]["exit_status"] == "success"


def test_apply_config_override_also_obeys_move_required():
    ns = build_startup_namespace(include_eiger=True)
    ns["beam_stop"].out_position = ns["beam_stop"].bsr.position
    messages = []
    RE = RunEngine({})
    RE.msg_hook = messages.append
    RE(apply_config(config_id=123, config_root=str(CONFIG_ROOT), namespace=ns, detx=0.0, beam_stop_out=True))
    assert not [msg for msg in messages if msg.command == "set" and msg.obj in (ns["det_stage"].x, ns["beam_stop"].bsr)]


def test_three_point_series_through_runengine_records_positions_and_restores(tmp_path):
    ns = build_startup_namespace(include_sensors=True, include_eiger=True)
    ns["beam_stop"].out_position = 246.8
    exposures = []

    # Signal-only detector executes the real exposure configuration, stage,
    # trigger/read and unstage plans, without EPICS or time spent exposing.
    detector = SynSignal(name="eiger")
    detector.cam = ns["eiger"].cam
    for field in ("num_images", "acquire_time", "acquire_period", "file_path"):
        setattr(detector.cam, field, Signal(name=f"eiger_{field}", value="" if field == "file_path" else 0))

    def acquire():
        exposures.append(
            {
                "detx": ns["det_stage"].x.position,
                "bsr": ns["beam_stop"].bsr.position,
                "y": ns["sample_stage_yz"].y.position,
                "z": ns["sample_stage_yz"].z.position,
                "shutter": ns["cu_generator"].shutter.get(),
                "duration": detector.cam.num_images.get() * detector.cam.acquire_time.get(),
                "destination": Path(detector.cam.file_path.get()),
            }
        )
        return 1.0

    detector.sim_set_func(acquire)
    ns["eiger"] = detector
    specs = build_plan_specs(
        [entry(additional_parameters={"configuration": "123", "steps": "3", "duration": "2.5"})],
        registry=build_default_registry(),
        apply_config_extra_kwargs={"config_root": str(CONFIG_ROOT)},
        measurement_extra_kwargs={"root_path": str(tmp_path)},
    )
    docs, messages = [], []
    RE = RunEngine({})
    sd = bpp.SupplementalData()
    sd.baseline = build_baseline_signals(namespace=ns)
    RE.preprocessors.append(sd)
    RE.subscribe(lambda name, doc: docs.append((name, doc)))
    RE.msg_hook = messages.append
    funcs = {
        "apply_config": lambda **kwargs: apply_config(namespace=ns, **kwargs),
        "measure_yzstage": lambda **kwargs: measure_yzstage(namespace=ns, **kwargs),
    }
    for plan in materialize_plans(specs, funcs):
        RE(plan)

    starts = [doc for name, doc in docs if name == "start"]
    runs = [doc for doc in starts if doc.get("protocol") == "triangulation"]
    assert len(starts) == 7
    assert len(runs) == 3
    assert len(exposures) == 9
    assert len({run["destination"] for run in runs}) == 3
    assert len({run["sequence_index"] for run in runs}) == 3
    descriptors = {doc["uid"]: doc for name, doc in docs if name == "descriptor"}
    for index, (run, distance) in enumerate(zip(runs, [500.0, 185.0, -130.0], strict=True)):
        assert run["triangulation_index"] == index
        assert run["triangulation_points"] == 3
        assert run["triangulation_detx"] == distance
        assert run["sample_exposure_time"] == 2.5
        destination = Path(run["destination"])
        assert (destination / "COMPLETE").read_text() == "ok\n"
        for exposure, subdir, duration, y, z in zip(
            exposures[index * 3 : index * 3 + 3],
            ["beam_profile", "beam_profile_through_sample", ""],
            [20.0, 20.0, 2.5],
            [5.6, 1.2, 1.2],
            [7.8, 3.4, 3.4],
            strict=True,
        ):
            assert exposure == {
                "detx": distance,
                "bsr": 246.8,
                "y": pytest.approx(y),
                "z": pytest.approx(z),
                "shutter": 1,
                "duration": duration,
                "destination": destination / subdir,
            }
            with h5py.File(exposure["destination"] / "im_craw.nxs", "r") as f:
                assert f["/saxs/Saxslab/detx"][()] == distance
                assert f["/saxs/Saxslab/bsr"][()] == 246.8
                assert f["/entry1/experiment/triangulation_index"][()] == index
                assert f["/entry1/experiment/protocol"].asstr()[()] == "triangulation"
                assert f["/entry1/instrument/detector00/count_time"][()] == duration
        baseline = [
            doc["data"]["detx"]
            for name, doc in docs
            if name == "event"
            and descriptors[doc["descriptor"]]["name"] == "baseline"
            and descriptors[doc["descriptor"]]["run_start"] == run["uid"]
        ]
        assert baseline == [distance, distance]
    with h5py.File(CONFIG_ROOT / "123.nxs", "r") as f:
        file_detx = float(f["/saxs/Saxslab/detx"][()])
        file_bsr = float(f["/saxs/Saxslab/bsr"][()])
    assert ns["det_stage"].x.position == file_detx
    assert ns["beam_stop"].bsr.position == file_bsr
    assert ns["cu_generator"].shutter.get() == 0
    assert [msg.args[0] for msg in messages if msg.command == "set" and msg.obj is ns["det_stage"].x] == [
        500.0,
        185.0,
        -130.0,
        file_detx,
    ]
    assert starts[-1]["activity"] == "apply_config"
    assert starts[-1]["detx"] is None
    assert starts[-1]["beam_stop_out"] is False
    assert all(doc["exit_status"] == "success" for name, doc in docs if name == "stop")


def test_point_configuration_reestablishes_state_after_other_measurement(tmp_path):
    ns = build_startup_namespace(include_eiger=True)
    ns["beam_stop"].out_position = 246.8
    specs = build_plan_specs(
        [entry(additional_parameters={"configuration": "123", "steps": "3"})],
        registry=build_default_registry(),
        apply_config_extra_kwargs={"config_root": str(CONFIG_ROOT)},
        measurement_extra_kwargs={"root_path": str(tmp_path)},
    )
    RE = RunEngine({})
    # An ordinary configuration has reset the machine before restarting point 1.
    RE(apply_config(config_id=123, config_root=str(CONFIG_ROOT), namespace=ns))
    ns["s1"].top.set(-999).wait()
    RE(apply_config(namespace=ns, **specs[2].kwargs))
    assert ns["det_stage"].x.position == 185.0
    assert ns["beam_stop"].bsr.position == 246.8
    with h5py.File(CONFIG_ROOT / "123.nxs", "r") as f:
        assert ns["s1"].top.position == float(f["/saxs/Saxslab/s1top"][()])


def test_outside_simulated_epics_limits_fails_apply_audit_before_measurement():
    ns = build_startup_namespace(include_eiger=True)
    motor = make_fake_device(MouseEpicsMotor)("SIM:", name="detx")
    motor.user_readback.sim_put(0)
    motor.user_setpoint.sim_set_limits((-10, 10))
    ns["det_stage"].x = motor
    docs = []
    RE = RunEngine({})
    RE.subscribe(lambda name, doc: docs.append((name, doc)))
    with pytest.raises(LimitError, match="value=11.0 not within limits"):
        RE(apply_config(config_id=123, config_root=str(CONFIG_ROOT), namespace=ns, detx=11.0, beam_stop_out=True))
    assert motor.position == 0
    assert [name for name, doc in docs] == ["start", "stop"]
    assert docs[-1][1]["exit_status"] == "fail"
    assert "value=11.0 not within limits (-10, 10)" in docs[-1][1]["reason"]
