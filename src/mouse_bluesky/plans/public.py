from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any, Mapping

from bluesky import plan_stubs as bps

from mouse_bluesky.settings import Settings

from .atomic import measure_yzstage_atomic
from .sequence import allocate_sequence_dir
from .snapshot import snapshot_state


def _get_ipython_user_ns() -> Mapping[str, Any]:
    try:
        from IPython import get_ipython
    except ImportError:
        return {}

    shell = get_ipython()
    if shell is None:
        return {}
    return getattr(shell, "user_ns", {})


def _resolve_optional_device(
    value: Any,
    *,
    name: str,
    namespace: Mapping[str, Any] | None = None,
) -> Any:
    if value is not None:
        return value
    ns = namespace if namespace is not None else _get_ipython_user_ns()
    resolved = ns.get(name)
    if resolved is None:
        raise ValueError(f"No `{name}` was provided and none was found in the interactive namespace.")
    return resolved


def measure_yzstage(
    *,
    entry_row_index: int = 0,
    proposal: str = "2026001",
    sampleid: int = 1,
    sampos: str = "",
    ymd: str | None = "20261232",
    batchnum: int = 0,
    config_id: int = 123,
    repeat_index: int = 0,
    root_path: str | None = None,
    md: dict[str, object] | None = None,
    # devices:
    eiger=None,
    sample_stage_yz=None,
    beam_stop=None,
    namespace: Mapping[str, Any] | None = None,
    snapshot_signals=(),
    sample_exposure_time: float = 600,
    sampleposition: dict[str, float] | None = None,
) -> Iterator:
    """Open one run, capture metadata/snapshot, and execute the atomic measurement."""
    if root_path is None:
        root_path = Settings.from_env().root_path.as_posix()
    if ymd is None:
        ymd = date.today().strftime("%Y%m%d")

    eiger = _resolve_optional_device(eiger, name="eiger", namespace=namespace)
    sample_stage_yz = _resolve_optional_device(sample_stage_yz, name="sample_stage_yz", namespace=namespace)
    beam_stop = _resolve_optional_device(beam_stop, name="beam_stop", namespace=namespace)
    # derive x-ray generator (cu_generator or mo_generator) from config id, if first digit is odd, use cu, otherwise use mo
    xray_generator_name = "cu_generator" if int(str(config_id)[0]) % 2 == 1 else "mo_generator"

    xray_generator = _resolve_optional_device(None, name=xray_generator_name, namespace=namespace)

    root = Path(root_path)
    if sampleposition is None:
        sampleposition = {}

    sequence_index, destination = allocate_sequence_dir(root=root, ymd=ymd, batchnum=batchnum)

    run_md = dict(md or {})
    run_md.update(
        {
            "entry_row_index": entry_row_index,
            "proposal": proposal,
            "sampleid": sampleid,
            "sampos": sampos,
            "ymd": ymd,
            "batchnum": batchnum,
            "config_id": int(config_id),
            "repeat_index": int(repeat_index),
            "sequence_index": int(sequence_index),
            "destination": destination.as_posix(),
            "sample_exposure_time": sample_exposure_time,
        }
    )

    yield from bps.open_run(md=run_md)
    try:
        # Baseline should be configured on the RunEngine via SupplementalData.
        # Snapshot stream just before acquisition:
        if snapshot_signals:
            yield from snapshot_state(snapshot_signals, stream_name="snapshot")

        yield from measure_yzstage_atomic(
            eiger=eiger,
            sample_stage_yz=sample_stage_yz,
            beam_stop=beam_stop,
            shutter=xray_generator.shutter,
            sampleposition=sampleposition,
            destination=destination,
            sample_exposure_time=sample_exposure_time,
        )

        # Optional: mark success
        (destination / "COMPLETE").write_text("ok\n", encoding="utf-8")
    finally:
        yield from bps.close_run()
