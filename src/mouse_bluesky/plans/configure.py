from __future__ import annotations

import inspect
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import h5py
from bluesky import plan_stubs as bps

# NOTE: when adding devices, add them here. For example, adding syringe injector positions and
# temperature controller setpoints would be common additions. This keeps track of what devices
# are expected to be in the config files and allows for dynamic resolution. Adding to baseline
# can be done as well, to keep track of device state during operation.
# TODO: add the pressure gauge readout.

# create a registry for "movable devices" that defines a machine configuration and needs to be moved
# maps the field paths in nexus to ophyd devices
HDF5_OPHYD_MAP_BASE: dict[str, str] = {
    # detector stage
    "/saxs/Saxslab/detx": "det_stage.x",
    "/saxs/Saxslab/dety": "det_stage.y",
    "/saxs/Saxslab/detz": "det_stage.z",
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
    "/saxs/Saxslab/gsx": "sample_stage_gi.x",
    "/saxs/Saxslab/gsy": "sample_stage_gi.y",
    # ... TODO: complete.
}

GENERATOR_BASELINE_SIGNALS: tuple[str, ...] = (
    "cu_generator.voltage",
    "cu_generator.current",
    "mo_generator.voltage",
    "mo_generator.current",
)

MOVE_IN_GROUPS: tuple[tuple[str, ...], ...] = (
    # independently powered stages
    ("/saxs/Saxslab/dual", "/saxs/Saxslab/dual",),
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
    # detector y, z
    ("/saxs/Saxslab/detx",),
    ("/saxs/Saxslab/dety",),
    ("/saxs/Saxslab/detz",),
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


def _try_resolve_dotted_name(name: str, *, namespace: Mapping[str, Any] | None = None) -> Any | None:
    try:
        return _resolve_dotted_name(name, namespace=namespace)
    except Exception:
        return None


def build_baseline_signals(*, namespace: Mapping[str, Any] | None = None) -> list[Any]:
    """Build an ordered baseline signal list for RunEngine SupplementalData.

    Baseline always includes all signals mapped in ``HDF5_OPHYD_MAP_BASE``.
    Additional YZ and GI stage signals are included when their mapped objects
    can be resolved in the provided ``namespace`` (or caller/global frames).
    X-ray generator readbacks (voltage/current) are included when available.
    """
    signal_names: list[str] = list(HDF5_OPHYD_MAP_BASE.values())

    for optional_map in (HDF5_OPHYD_MAP_YZ, HDF5_OPHYD_MAP_GI):
        for signal_name in optional_map.values():
            if _try_resolve_dotted_name(signal_name, namespace=namespace) is not None:
                signal_names.append(signal_name)

    for signal_name in GENERATOR_BASELINE_SIGNALS:
        if _try_resolve_dotted_name(signal_name, namespace=namespace) is not None:
            signal_names.append(signal_name)

    baseline_signals: list[Any] = []
    seen_ids: set[int] = set()
    for signal_name in signal_names:
        signal = _resolve_dotted_name(signal_name, namespace=namespace)
        signal_id = id(signal)
        if signal_id in seen_ids:
            continue
        seen_ids.add(signal_id)
        baseline_signals.append(signal)

    return baseline_signals


def apply_config(*, config_id: int, config_root: str, namespace: Mapping[str, Any] | None = None) -> Iterator:
    """Apply a machine configuration from ``{config_root}/{config_id}.nxs``.

    The plan:
    1. Loads scalar setpoints from the NeXus file using the HDF5->Ophyd maps.
    2. Resolves mapped dotted names (for example ``"s1.top"``) to live Ophyd
       objects, optionally using ``namespace`` as the root lookup source.
    3. Executes grouped moves in ``MOVE_IN_GROUPS`` order to coordinate motors
       that should move together.
    4. Moves remaining mapped signals one-by-one.

    Raises:
        FileNotFoundError: If the config file does not exist.
        KeyError: If required datasets are missing or a stage section is partial.
        NameError: If a mapped device root name cannot be resolved.
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

        # resolve ophyd objects and read values from the file
        resolved = {
            hdf5_path: _resolve_dotted_name(signal_name, namespace=namespace)
            for hdf5_path, signal_name in ophyd_map.items()
        }
        values = {hdf5_path: float(f[hdf5_path][()]) for hdf5_path in ophyd_map}

    moved_paths: set[str] = set()
    for group in MOVE_IN_GROUPS:
        if not all(path in resolved for path in group):
            # print an error message:
            missing = [path for path in group if path not in resolved]
            print(f"Warning: skipping move group {group} due to missing paths: {missing}")
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
    """Persist the current machine state to ``{config_root}/{config_id}.nxs``.

    This records all signals in ``HDF5_OPHYD_MAP_BASE`` plus
    ``HDF5_OPHYD_MAP_YZ`` (sample stage ``y``/``z``) by reading their current
    positions/readbacks and writing scalar datasets at the mapped HDF5 paths.

    The optional ``namespace`` argument can be used to provide explicit root
    objects for dotted-name resolution.
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
