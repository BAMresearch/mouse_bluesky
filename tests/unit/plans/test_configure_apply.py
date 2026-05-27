from pathlib import Path
from types import SimpleNamespace

import h5py
import pytest
from bluesky import RunEngine
from bluesky_queueserver.manager.profile_tools import global_user_namespace
from ophyd import Signal
from ophyd.sim import SynAxis

from mouse_bluesky.plans.configure import HDF5_OPHYD_MAP_BASE, apply_config
from tests.unit.plans.support import build_startup_namespace

CONFIG_ROOT = Path("tests/data/mouse_configs")


class CountingSynAxis(SynAxis):
    def __init__(self, *, name: str, value: float, retry_deadband: float) -> None:
        super().__init__(name=name, value=value)
        self.retry_deadband = Signal(name=f"{name}_retry_deadband", value=retry_deadband)
        self.set_count = 0

    def set(self, value: float):
        self.set_count += 1
        return super().set(value)


def _build_counting_namespace(
    *,
    config_id: int = 123,
    retry_deadband: float = 0.1,
    offsets: dict[str, float] | None = None,
) -> tuple[dict[str, object], dict[str, CountingSynAxis]]:
    namespace: dict[str, object] = {}
    axes: dict[str, CountingSynAxis] = {}
    config_file = CONFIG_ROOT / f"{config_id}.nxs"

    with h5py.File(config_file, "r") as f:
        for hdf5_path, signal_name in HDF5_OPHYD_MAP_BASE.items():
            root, attr = signal_name.split(".")
            parent = namespace.setdefault(root, SimpleNamespace())
            value = float(f[hdf5_path][()]) + (offsets or {}).get(hdf5_path, 0.0)
            axis = CountingSynAxis(name=attr, value=value, retry_deadband=retry_deadband)
            setattr(parent, attr, axis)
            axes[hdf5_path] = axis

    namespace["beam_stop"].out_position = 270.0
    return namespace, axes


def test_apply_config_does_not_move_sample_stage_yz():
    namespace = build_startup_namespace(include_yz=True, include_generators=False)
    RE = RunEngine({})
    config_root = CONFIG_ROOT.as_posix()

    y_before = namespace["sample_stage_yz"].y.position
    z_before = namespace["sample_stage_yz"].z.position

    RE(apply_config(config_id=123, config_root=config_root, namespace=namespace))

    assert namespace["sample_stage_yz"].y.position == y_before
    assert namespace["sample_stage_yz"].z.position == z_before


def test_apply_config_uses_qserver_user_namespace_when_namespace_is_none():
    namespace = build_startup_namespace(include_yz=True, include_generators=False)
    RE = RunEngine({})
    config_root = CONFIG_ROOT.as_posix()

    original_user_ns = dict(global_user_namespace.user_ns)
    try:
        global_user_namespace.set_user_namespace(user_ns=namespace, use_ipython=False)
        RE(apply_config(config_id=123, config_root=config_root))
    finally:
        global_user_namespace.set_user_namespace(user_ns=original_user_ns, use_ipython=False)


def test_apply_config_emits_start_and_stop_documents():
    namespace = build_startup_namespace(include_yz=True, include_generators=False)
    RE = RunEngine({})
    config_root = CONFIG_ROOT.as_posix()
    docs: list[tuple[str, dict]] = []

    RE.subscribe(lambda name, doc: docs.append((name, doc)))
    RE(apply_config(config_id=123, config_root=config_root, namespace=namespace))

    assert [name for name, _ in docs] == ["start", "stop"]
    start_doc = docs[0][1]
    stop_doc = docs[1][1]
    assert start_doc["config_id"] == 123
    assert start_doc["activity"] == "apply_config"
    assert start_doc["config_file"].endswith("/123.nxs")
    assert stop_doc["exit_status"] == "success"


def test_apply_config_skips_motors_inside_retry_deadband():
    namespace, axes = _build_counting_namespace(offsets={"/saxs/Saxslab/detx": 0.05})
    RE = RunEngine({})

    RE(apply_config(config_id=123, config_root=CONFIG_ROOT.as_posix(), namespace=namespace))

    assert {path: axis.set_count for path, axis in axes.items()} == dict.fromkeys(axes, 0)


def test_apply_config_moves_motors_outside_retry_deadband():
    namespace, axes = _build_counting_namespace(offsets={"/saxs/Saxslab/detx": 0.2})
    RE = RunEngine({})

    RE(apply_config(config_id=123, config_root=CONFIG_ROOT.as_posix(), namespace=namespace))

    assert axes["/saxs/Saxslab/detx"].set_count == 1
    assert {path: axis.set_count for path, axis in axes.items() if path != "/saxs/Saxslab/detx"} == dict.fromkeys(
        (path for path in axes if path != "/saxs/Saxslab/detx"), 0
    )


def test_apply_config_emits_failed_run_documents_when_config_is_missing(tmp_path: Path):
    namespace = build_startup_namespace(include_yz=True, include_generators=False)
    RE = RunEngine({})
    docs: list[tuple[str, dict]] = []

    RE.subscribe(lambda name, doc: docs.append((name, doc)))

    with pytest.raises(FileNotFoundError):
        RE(apply_config(config_id=999, config_root=tmp_path.as_posix(), namespace=namespace))

    assert [name for name, _ in docs] == ["start", "stop"]
    start_doc = docs[0][1]
    stop_doc = docs[1][1]
    assert start_doc["config_id"] == 999
    assert stop_doc["exit_status"] == "fail"
    assert "Config file not found" in stop_doc["reason"]
