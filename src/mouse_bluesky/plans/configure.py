from __future__ import annotations

import inspect
from collections.abc import Iterator, Mapping
from pathlib import Path
from types import MappingProxyType

import h5py
from attrs import field, frozen
from bluesky import plan_stubs as bps

# NOTE: when adding devices, add them here. For example, adding syringe injector positions and
# temperature controller setpoints would be common additions. This keeps track of what devices
# are expected to be in the config files and allows for dynamic resolution. Adding to baseline
# can be done as well, to keep track of device state during operation.
# TODO: add the pressure gauge readout.


@frozen
class Hdf5OphydMap(Mapping[str, str]):
    """Immutable map of HDF5 dataset paths to dotted Ophyd names."""

    _mapping: Mapping[str, str] = field(converter=lambda value: MappingProxyType(dict(value)), repr=False)

    def __getitem__(self, key: str) -> str:
        return self._mapping[key]

    def __iter__(self):
        return iter(self._mapping)

    def __len__(self) -> int:
        return len(self._mapping)


# create a registry for "movable devices" that defines a machine configuration and needs to be moved
# maps the field paths in nexus to ophyd devices
HDF5_OPHYD_MAP_BASE = Hdf5OphydMap(
    {
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
        "/saxs/Saxslab/s1hl": "s1.left",
        "/saxs/Saxslab/s1hr": "s1.right",
        # middle slits
        "/saxs/Saxslab/s2bot": "s2.bot",
        "/saxs/Saxslab/s2top": "s2.top",
        "/saxs/Saxslab/s2hl": "s2.left",
        "/saxs/Saxslab/s2hr": "s2.right",
        # downstream slits
        "/saxs/Saxslab/s3bot": "s3.bot",
        "/saxs/Saxslab/s3top": "s3.top",
        "/saxs/Saxslab/s3hl": "s3.left",
        "/saxs/Saxslab/s3hr": "s3.right",
    }
)

# actually not needed to move the sample stages... probably move elsewhere.
HDF5_OPHYD_MAP_YZ = Hdf5OphydMap(
    {
        # standard sample stage
        "/saxs/Saxslab/ysam": "sample_stage_yz.y",
        "/saxs/Saxslab/zsam": "sample_stage_yz.z",
    }
)

# additional devices for GI stage - move if present in the config
HDF5_OPHYD_MAP_GI = Hdf5OphydMap(
    {
        "/saxs/Saxslab/gsx": "sample_stage_gi.x",
        "/saxs/Saxslab/gsy": "sample_stage_gi.y",
        # ... TODO: complete.
    }
)

GENERATOR_BASELINE_SIGNALS: tuple[str, ...] = (
    "cu_generator.voltage",
    "cu_generator.current",
    "mo_generator.voltage",
    "mo_generator.current",
)

SENSOR_BASELINE_SIGNALS: tuple[str, ...] = (
    "pressure_gauge.pressure",
    "arduino.temperature_env", 
    "arduino.temperature_stage",
)

MOVE_IN_GROUPS: tuple[tuple[str, ...], ...] = (
    # independently powered stages
    (
        "/saxs/Saxslab/dual",
        "/saxs/Saxslab/detx",
    ),
    # top-bottom slit blades
    ("/saxs/Saxslab/s1top", "/saxs/Saxslab/s1bot"),
    ("/saxs/Saxslab/s2top", "/saxs/Saxslab/s2bot"),
    ("/saxs/Saxslab/s3top", "/saxs/Saxslab/s3bot"),
    # left-right slit blades
    ("/saxs/Saxslab/s1hl", "/saxs/Saxslab/s1hr"),
    ("/saxs/Saxslab/s2hl", "/saxs/Saxslab/s2hr"),
    ("/saxs/Saxslab/s3hl", "/saxs/Saxslab/s3hr"),
    # beam stop motors
    ("/saxs/Saxslab/bsr",),
    ("/saxs/Saxslab/bsz",),
    # detector y, z
    ("/saxs/Saxslab/dety",),
    ("/saxs/Saxslab/detz",),
)


def _resolve_dotted_name(name: str, *, namespace: Mapping[str, object] | None = None) -> object:
    parts = name.split(".")
    if not parts:
        raise ValueError("Empty dotted name")

    root = parts[0]
    obj = None
    if namespace is not None and root in namespace:
        obj = namespace[root]
    else:
        # Queue Server startup namespace (set by worker before plan execution).
        try:
            from bluesky_queueserver.manager.profile_tools import global_user_namespace

            user_ns = global_user_namespace.user_ns
            if isinstance(user_ns, Mapping) and root in user_ns:
                obj = user_ns[root]
        except Exception:
            pass

    if obj is None:
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


def _select_apply_ophyd_map(f: h5py.File) -> dict[str, str]:
    ophyd_map = dict(HDF5_OPHYD_MAP_BASE.items())

    has_any_gi = any(path in f for path in HDF5_OPHYD_MAP_GI)
    if has_any_gi:
        missing = [path for path in HDF5_OPHYD_MAP_GI if path not in f]
        if missing:
            raise KeyError(f"Incomplete GI stage fields in config file: {missing}")
        ophyd_map.update(HDF5_OPHYD_MAP_GI)

    return ophyd_map


def _readback_value(signal: object) -> float:
    if hasattr(signal, "user_readback"):
        return float(signal.user_readback.get())
    if hasattr(signal, "position"):
        return float(signal.position)
    if hasattr(signal, "get"):
        return float(signal.get())
    raise TypeError(f"Cannot read value from signal object: {signal!r}")


def _try_resolve_dotted_name(name: str, *, namespace: Mapping[str, object] | None = None) -> object | None:
    try:
        return _resolve_dotted_name(name, namespace=namespace)
    except Exception:
        return None


def build_baseline_signals(*, namespace: Mapping[str, object] | None = None) -> list[object]:
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

    for signal_name in SENSOR_BASELINE_SIGNALS:
        if _try_resolve_dotted_name(signal_name, namespace=namespace) is not None:
            signal_names.append(signal_name)

    baseline_signals: list[object] = []
    seen_ids: set[int] = set()
    for signal_name in signal_names:
        signal = _resolve_dotted_name(signal_name, namespace=namespace)
        signal_id = id(signal)
        if signal_id in seen_ids:
            continue
        seen_ids.add(signal_id)
        baseline_signals.append(signal)

    return baseline_signals


def collect_baseline_motor_readbacks(*, namespace: Mapping[str, object] | None = None) -> dict[str, float]:
    """Collect baseline-mapped motor readbacks keyed by NeXus dataset path."""
    values: dict[str, float] = {}

    for hdf5_path, signal_name in HDF5_OPHYD_MAP_BASE.items():
        signal = _resolve_dotted_name(signal_name, namespace=namespace)
        values[hdf5_path] = _readback_value(signal)

    for optional_map in (HDF5_OPHYD_MAP_YZ, HDF5_OPHYD_MAP_GI):
        for hdf5_path, signal_name in optional_map.items():
            signal = _try_resolve_dotted_name(signal_name, namespace=namespace)
            if signal is None:
                continue
            values[hdf5_path] = _readback_value(signal)

    return values


def apply_config(*, config_id: int, config_root: str, namespace: Mapping[str, object] | None = None) -> Iterator:
    """Apply a machine configuration from ``{config_root}/{config_id}.nxs``.

    The plan:
    1. Loads scalar setpoints from the NeXus file using the HDF5->Ophyd maps.
    2. Resolves mapped dotted names (for example ``"s1.top"``) to live Ophyd
       objects, optionally using ``namespace`` as the root lookup source.
    3. Optionally includes GI stage signals if present in the file.
       YZ sample-stage signals are intentionally not moved by this plan.
    4. Executes grouped moves in ``MOVE_IN_GROUPS`` order to coordinate motors
       that should move together.
    5. Moves remaining mapped signals one-by-one.

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
        ophyd_map = _select_apply_ophyd_map(f)

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


def save_config(*, config_id: int, config_root: str, namespace: Mapping[str, object] | None = None) -> Iterator:
    """Persist the current machine state to ``{config_root}/{config_id}.nxs``.

    This records all signals in ``HDF5_OPHYD_MAP_BASE`` plus
    ``HDF5_OPHYD_MAP_YZ`` (sample stage ``y``/``z``) by reading their current
    positions/readbacks and writing scalar datasets at the mapped HDF5 paths.

    The optional ``namespace`` argument can be used to provide explicit root
    objects for dotted-name resolution.
    """
    config_file_path = Path(config_root) / f"{config_id}.nxs"
    config_file_path.parent.mkdir(parents=True, exist_ok=True)

    ophyd_map = {**dict(HDF5_OPHYD_MAP_BASE.items()), **dict(HDF5_OPHYD_MAP_YZ.items())}
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
