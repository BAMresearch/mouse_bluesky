from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Mapping

from bluesky import preprocessors as bpp

from mouse_bluesky.devices.eiger import ad_configure_energy
from mouse_bluesky.settings import Settings

from .atomic import measure_yzstage_atomic
from .sequence import allocate_sequence_dir
from .snapshot import snapshot_state
from .source import check_source_power, source_settings_for_config_id

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
    `source_settings_for_config_id`. The active source must first produce at
    least 90% of nominal power (Cu 27 W, Mo 45 W), then detector energies are
    verified, then a sequence directory is allocated and the run is opened.
    A failed power check leaves no detector writes, directory, run or shutter
    commands. Power is checked once; it is not monitored during exposures.
    Strict shutter open and close commands time out after 10 s.

    After an attempted shutter open, exceptions, abort and stop send one
    best-effort close without moving any motor. Exceptions record ``fail``
    with their reason, abort records ``abort``, and stop records ``success``.
    Only normal completion strictly closes the shutter and writes ``COMPLETE``.
    Pausing leaves the shutter open; halt, worker crash or power loss skips
    cleanup. A failed best-effort close warns that the shutter is unconfirmed.
    """
    if root_path is None:
        root_path = Settings.from_env().root_path.as_posix()
    ymd = _resolve_measurement_ymd(ymd)

    eiger = _resolve_optional_device(eiger, name="eiger", namespace=namespace)
    sample_stage_yz = _resolve_optional_device(sample_stage_yz, name="sample_stage_yz", namespace=namespace)
    beam_stop = _resolve_optional_device(beam_stop, name="beam_stop", namespace=namespace)
    source = source_settings_for_config_id(int(config_id))

    xray_generator = _resolve_optional_device(None, name=source.generator_name, namespace=namespace)

    yield from check_source_power(xray_generator, source)

    root = Path(root_path)
    if sampleposition is None:
        sampleposition = {}

    yield from ad_configure_energy(
        eiger,
        photon_energy_ev=source.photon_energy_ev,
        threshold_energy_ev=source.threshold_energy_ev,
    )

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

    def body():
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

    yield from bpp.run_wrapper(body(), md=run_md)
