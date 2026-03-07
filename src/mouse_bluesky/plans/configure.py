from __future__ import annotations

from collections.abc import Iterator
from collections.abc import Mapping
import inspect
from typing import Any

from pathlib import Path
from bluesky import plan_stubs as bps
import h5py

# create a registry for "movable devices" that defines a machine configuration and needs to be moved
# maps the field paths in nexus to ophyd devices
HDF5_OPHYD_MAP_BASE: dict[str, str] = {
    # detector stage
    "/saxs/Saxslab/detx": "eiger.cam.x",
    "/saxs/Saxslab/dety": "eiger.cam.y",
    "/saxs/Saxslab/detz": "eiger.cam.z",
    # beam stop
    "/saxs/Saxslab/bsr": "beam_stop.bsr",
    "/saxs/Saxslab/bsz": "beam_stop.bsz",
    # dual source motor
    "/saxs/Saxslab/dual": "dual.dual",
    # upstream slits
    "/saxs/Saxslab/s1bot": "s1.bot",
    "/saxs/Saxslab/s1top": "s1.top",
    "/saxs/Saxslab/s1left": "s1.left",
    "/saxs/Saxslab/s1right": "s1.right",
    # middle slits
    "/saxs/Saxslab/s2bot": "s2.bot",
    "/saxs/Saxslab/s2top": "s2.top",
    "/saxs/Saxslab/s2left": "s2.left",
    "/saxs/Saxslab/s2right": "s2.right",
    # downstream slits
    "/saxs/Saxslab/s3bot": "s3.bot",
    "/saxs/Saxslab/s3top": "s3.top",
    "/saxs/Saxslab/s3left": "s3.left",
    "/saxs/Saxslab/s3right": "s3.right",
}

# actually not needed to move the sample stages... probably move elsewhere. 
HDF5_OPHYD_MAP_YZ: dict[str, str] = {
    # standard sample stage
    "/saxs/Saxslab/ysam": "sample_stage_yz.y",
    "/saxs/Saxslab/zsam": "sample_stage_yz.z",
}

# additional devices for GI stage - move if present in the config
HDF5_OPHYD_MAP_GI: dict[str, str] = {
    "/saxs/Saxslab/gsx": "gi_stage.x",
    "/saxs/Saxslab/gsy": "gi_stage.y",
    # ... TODO: complete.
}

MOVE_IN_GROUPS: tuple[tuple[str, ...], ...] = (
    # independently powered stages
    ("/saxs/Saxslab/dual",),
    ("/saxs/Saxslab/detx",),
    # top-bottom slit blades
    ("/saxs/Saxslab/s1top", "/saxs/Saxslab/s1bot"),
    ("/saxs/Saxslab/s2top", "/saxs/Saxslab/s2bot"),
    ("/saxs/Saxslab/s3top", "/saxs/Saxslab/s3bot"),
    # left-right slit blades
    ("/saxs/Saxslab/s1left", "/saxs/Saxslab/s1right"),
    ("/saxs/Saxslab/s2left", "/saxs/Saxslab/s2right"),
    ("/saxs/Saxslab/s3left", "/saxs/Saxslab/s3right"),
    # beam stop motors
    ("/saxs/Saxslab/bsr",),
    ("/saxs/Saxslab/bsz",),
)


def _resolve_dotted_name(name: str, *, namespace: Mapping[str, Any] | None = None) -> Any:
    parts = name.split(".")
    if not parts:
        raise ValueError("Empty dotted name")

    root = parts[0]
    obj = None
    if namespace is not None and root in namespace:
        obj = namespace[root]
    else:
        # Search frames so plans can resolve devices from Queue Server startup namespace.
        for frame_info in inspect.stack():
            frame = frame_info.frame
            if root in frame.f_locals:
                obj = frame.f_locals[root]
                break
            if root in frame.f_globals:
                obj = frame.f_globals[root]
                break

    if obj is None:
        raise NameError(f"Could not resolve root object '{root}' from '{name}'")

    for attr in parts[1:]:
        obj = getattr(obj, attr)
    return obj


def _select_ophyd_map(f: h5py.File) -> dict[str, str]:
    ophyd_map = dict(HDF5_OPHYD_MAP_BASE)

    has_any_yz = any(path in f for path in HDF5_OPHYD_MAP_YZ)
    if has_any_yz:
        missing = [path for path in HDF5_OPHYD_MAP_YZ if path not in f]
        if missing:
            raise KeyError(f"Incomplete YZ stage fields in config file: {missing}")
        ophyd_map.update(HDF5_OPHYD_MAP_YZ)

    has_any_gi = any(path in f for path in HDF5_OPHYD_MAP_GI)
    if has_any_gi:
        missing = [path for path in HDF5_OPHYD_MAP_GI if path not in f]
        if missing:
            raise KeyError(f"Incomplete GI stage fields in config file: {missing}")
        ophyd_map.update(HDF5_OPHYD_MAP_GI)

    return ophyd_map


def _readback_value(signal: Any) -> float:
    if hasattr(signal, "user_readback"):
        return float(signal.user_readback.get())
    if hasattr(signal, "position"):
        return float(signal.position)
    if hasattr(signal, "get"):
        return float(signal.get())
    raise TypeError(f"Cannot read value from signal object: {signal!r}")


def apply_config(*, config_id: int, config_root: str, namespace: Mapping[str, Any] | None = None) -> Iterator:
    """Apply a machine configuration from `{config_root}/{config_id}.nxs`.

    TODO: implement:
    - open nxs
    - read scalar datasets under /saxs/Saxslab/*
    - map dataset names -> ophyd signals
    - sequence bps.mv safely (clever grouping to avoid overloading motor power supplies)
    """
    config_file_path = Path(config_root) / f"{config_id}.nxs"
    if not config_file_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_file_path}")
    with h5py.File(config_file_path, "r") as f:
        # check that all expected devices are present in the file
        for hdf5_path in HDF5_OPHYD_MAP_BASE:
            if hdf5_path not in f:
                raise KeyError(f"Expected config dataset not found: {hdf5_path} from BASE map")
        ophyd_map = _select_ophyd_map(f)

        resolved = {
            hdf5_path: _resolve_dotted_name(signal_name, namespace=namespace)
            for hdf5_path, signal_name in ophyd_map.items()
        }
        values = {hdf5_path: float(f[hdf5_path][()]) for hdf5_path in ophyd_map}

        moved_paths: set[str] = set()
        for group in MOVE_IN_GROUPS:
            if not all(path in resolved for path in group):
                continue
            move_args = []
            for path in group:
                move_args.extend([resolved[path], values[path]])
            yield from bps.mv(*move_args)
            moved_paths.update(group)

        for hdf5_path, signal in resolved.items():
            if hdf5_path in moved_paths:
                continue
            yield from bps.mv(signal, values[hdf5_path])


def save_config(*, config_id: int, config_root: str, namespace: Mapping[str, Any] | None = None) -> Iterator:
    """
    Save current machine configuration to `{config_root}/{config_id}.nxs`.

    Includes all base motors and currently defined YZ sample stage motors from the
    Queue Server startup profile.
    """
    config_file_path = Path(config_root) / f"{config_id}.nxs"
    config_file_path.parent.mkdir(parents=True, exist_ok=True)

    ophyd_map = {**HDF5_OPHYD_MAP_BASE, **HDF5_OPHYD_MAP_YZ}
    values = {}
    for hdf5_path, signal_name in ophyd_map.items():
        signal = _resolve_dotted_name(signal_name, namespace=namespace)
        values[hdf5_path] = _readback_value(signal)

    with h5py.File(config_file_path, "w") as f:
        for hdf5_path, value in values.items():
            parent = str(Path(hdf5_path).parent)
            if parent and parent != "/":
                f.require_group(parent)
            f.create_dataset(hdf5_path, data=value)

    yield from bps.null()
