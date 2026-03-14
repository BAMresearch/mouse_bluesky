from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Mapping

from bluesky import plan_stubs as bps

from mouse_bluesky.settings import Settings

from .atomic import measure_yzstage_atomic
from .sequence import allocate_sequence_dir
from .snapshot import snapshot_state

UNRESOLVED_YMD_SENTINEL = "20261232"


def _get_ipython_user_ns() -> Mapping[str, object]:
    try:
        from IPython import get_ipython
    except ImportError:
        return {}

    shell = get_ipython()
    if shell is None:
        return {}
    return getattr(shell, "user_ns", {})


def _get_qserver_user_ns() -> Mapping[str, object]:
    try:
        from bluesky_queueserver.manager.profile_tools import global_user_namespace
    except Exception:
        return {}
    user_ns = getattr(global_user_namespace, "user_ns", None)
    if isinstance(user_ns, Mapping):
        return user_ns
    return {}


def _resolve_optional_device(
    value: object | None,
    *,
    name: str,
    namespace: Mapping[str, object] | None = None,
) -> object:
    if value is not None:
        return value
    if namespace is not None:
        resolved = namespace.get(name)
    else:
        resolved = _get_qserver_user_ns().get(name)
        if resolved is None:
            resolved = _get_ipython_user_ns().get(name)
    if resolved is None:
        raise ValueError(f"No `{name}` was provided and none was found in the available namespace.")
    return resolved


def _resolve_measurement_ymd(ymd: str | None) -> str:
    """Return a safe date path segment for the measurement output tree.

    We intentionally do not fall back to today's date. When `ymd` is omitted or
    passed as `None`, we use an impossible-date sentinel so ad hoc runs cannot
    silently write into an existing day directory.
    """
    return UNRESOLVED_YMD_SENTINEL if ymd is None else ymd


def _legacy_generator_name_for_config_id(config_id: int) -> str:
    """Resolve the source generator name from the legacy config-id convention.

    Current beamline operation still infers the active source from the leading
    digit of `config_id`: odd selects `cu_generator`, even selects
    `mo_generator`.
    """
    digits = [char for char in str(config_id) if char.isdigit()]
    if not digits:
        raise ValueError(f"`config_id` must contain at least one digit, got {config_id!r}")
    return "cu_generator" if int(digits[0]) % 2 == 1 else "mo_generator"


def measure_yzstage(
    *,
    entry_row_index: int = 0,
    proposal: str = "2026001",
    sampleid: int = 1,
    sampos: str = "",
    ymd: str | None = UNRESOLVED_YMD_SENTINEL,
    batchnum: int = 0,
    config_id: int = 123,
    repeat_index: int = 0,
    root_path: str | None = None,
    md: dict[str, object] | None = None,
    # devices:
    eiger=None,
    sample_stage_yz=None,
    beam_stop=None,
    namespace: Mapping[str, object] | None = None,
    snapshot_signals=(),
    sample_exposure_time: float = 600,
    sampleposition: dict[str, float] | None = None,
) -> Iterator:
    """Open one run, capture metadata/snapshot, and execute the atomic measurement.

    `ymd` defaults to an impossible-date sentinel rather than today's date so
    underspecified runs do not pollute an existing daily dataset. Source
    selection currently follows the legacy config-id convention implemented by
    `_legacy_generator_name_for_config_id`.
    """
    if root_path is None:
        root_path = Settings.from_env().root_path.as_posix()
    ymd = _resolve_measurement_ymd(ymd)

    eiger = _resolve_optional_device(eiger, name="eiger", namespace=namespace)
    sample_stage_yz = _resolve_optional_device(sample_stage_yz, name="sample_stage_yz", namespace=namespace)
    beam_stop = _resolve_optional_device(beam_stop, name="beam_stop", namespace=namespace)
    xray_generator_name = _legacy_generator_name_for_config_id(int(config_id))

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
            run_md=run_md,
            namespace=namespace,
            xray_generator=xray_generator,
        )

        # Optional: mark success
        (destination / "COMPLETE").write_text("ok\n", encoding="utf-8")
    finally:
        yield from bps.close_run()
