from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import h5py

from .configure import collect_baseline_motor_readbacks, collect_sensor_readbacks


def _as_dataset_value(value: Any) -> int | float | str:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float, str)):
        return value
    if value is None:
        return ""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _sanitize_dataset_name(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)


def _write_dataset(f: h5py.File, path: str, value: Any) -> None:
    parent = str(Path(path).parent)
    if parent and parent != "/":
        f.require_group(parent)
    dataset_value = _as_dataset_value(value)
    if isinstance(dataset_value, str):
        f.create_dataset(path, data=dataset_value, dtype=h5py.string_dtype("utf-8"))
        return
    f.create_dataset(path, data=dataset_value)


def write_im_craw_nxs(
    *,
    destination: Path,
    run_md: Mapping[str, object] | None = None,
    namespace: Mapping[str, object] | None = None,
    xray_generator: object | None = None,
) -> Path:
    """Write `im_craw.nxs` with run metadata and baseline-like machine state."""
    destination.mkdir(parents=True, exist_ok=True)
    out = destination / "im_craw.nxs"
    metadata = dict(run_md or {})

    state_values = collect_baseline_motor_readbacks(namespace=namespace)
    sensor_values = collect_sensor_readbacks(namespace=namespace)
    source_name = getattr(xray_generator, "name", "")
    source_voltage = getattr(xray_generator, "voltage", None)
    source_current = getattr(xray_generator, "current", None)

    with h5py.File(out, "w") as f:
        entry = f.require_group("/entry1")
        entry.attrs["NX_class"] = "NXentry"
        entry.attrs["default"] = "instrument"

        instrument = f.require_group("/entry1/instrument")
        instrument.attrs["NX_class"] = "NXinstrument"
        sample = f.require_group("/entry1/sample")
        sample.attrs["NX_class"] = "NXsample"
        sample.attrs["default"] = "name"

        _write_dataset(f, "/entry1/experiment/logbook_json", metadata)
        for key, value in sorted(metadata.items()):
            _write_dataset(f, f"/entry1/experiment/{_sanitize_dataset_name(key)}", value)

        _write_dataset(f, "/entry1/sample/sampleid", metadata.get("sampleid", -1))
        _write_dataset(f, "/entry1/sample/sampos", metadata.get("sampos", ""))
        _write_dataset(
            f,
            "/entry1/sample/name",
            f"{metadata.get('proposal', '')}-{metadata.get('sampleid', '')}",
        )
        _write_dataset(f, "/entry1/instrument/configuration", metadata.get("config_id", -1))
        _write_dataset(f, "/entry1/instrument/detector00/count_time", metadata.get("sample_exposure_time", ""))
        _write_dataset(f, "/entry1/instrument/source/name", source_name)
        if source_voltage is not None:
            _write_dataset(f, "/entry1/instrument/source/voltage", source_voltage.get())
        if source_current is not None:
            _write_dataset(f, "/entry1/instrument/source/current", source_current.get())

        for hdf5_path, value in state_values.items():
            _write_dataset(f, hdf5_path, value)
        for hdf5_path, value in sensor_values.items():
            _write_dataset(f, hdf5_path, value)

    return out
