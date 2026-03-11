from __future__ import annotations

from pathlib import Path
from typing import Iterator, Mapping

from bluesky import plan_stubs as bps

from mouse_bluesky.devices.eiger import ad_configure_exposure

from ..devices.mouse_motors import BeamStop, SampleStageYZ
from .im_craw import write_im_craw_nxs

BEAM_PROFILE_EXPOSURE_TIME: float = 20.0
BEAM_PROFILE_THROUGH_SAMPLE_EXPOSURE_TIME: float = 20.0


def mouse_eiger_measure(eiger, destination: Path, *, exposure_time: float = 1) -> Iterator:
    """Acquire one Eiger reading after staging into a target destination."""
    # destination.mkdir(parents=True, exist_ok=True)
    yield from ad_configure_exposure(eiger, exposure_time=exposure_time, output_path=destination)

    yield from bps.stage(eiger)
    try:
        yield from bps.trigger_and_read([eiger], name="mouse_eiger_measure")
    finally:
        yield from bps.unstage(eiger)


def measure_yzstage_atomic(
    *,
    eiger,
    sample_stage_yz: SampleStageYZ,
    beam_stop: BeamStop,
    shutter,
    sampleposition: dict[str, float],
    sample_exposure_time: float = 600,
    destination: Path,
    run_md: Mapping[str, object] | None = None,
    namespace: Mapping[str, object] | None = None,
    xray_generator: object | None = None,
) -> Iterator:
    """Run the low-level Y/Z stage measurement sequence inside an active run."""
    in_position = beam_stop.bsr.position

    yield from bps.mv(shutter, 1)
    yield from bps.mv(beam_stop.bsr, beam_stop.out_position)

    yield from bps.mv(sample_stage_yz.y, sampleposition.get("ysam.blank", sample_stage_yz.y.position))
    yield from bps.mv(sample_stage_yz.z, sampleposition.get("zsam.blank", sample_stage_yz.z.position))

    write_im_craw_nxs(
        destination=destination / "beam_profile",
        run_md={**dict(run_md or {}), "sample_exposure_time": BEAM_PROFILE_EXPOSURE_TIME},
        namespace=namespace,
        xray_generator=xray_generator,
    )
    yield from mouse_eiger_measure(
        eiger,
        destination / "beam_profile",
        exposure_time=BEAM_PROFILE_EXPOSURE_TIME,
    )

    yield from bps.mv(sample_stage_yz.y, sampleposition.get("ysam", sample_stage_yz.y.position))
    yield from bps.mv(sample_stage_yz.z, sampleposition.get("zsam", sample_stage_yz.z.position))

    write_im_craw_nxs(
        destination=destination / "beam_profile_through_sample",
        run_md={**dict(run_md or {}), "sample_exposure_time": BEAM_PROFILE_THROUGH_SAMPLE_EXPOSURE_TIME},
        namespace=namespace,
        xray_generator=xray_generator,
    )
    yield from mouse_eiger_measure(
        eiger,
        destination / "beam_profile_through_sample",
        exposure_time=BEAM_PROFILE_THROUGH_SAMPLE_EXPOSURE_TIME,
    )

    yield from bps.mv(beam_stop.bsr, in_position)
    write_im_craw_nxs(
        destination=destination,
        run_md={**dict(run_md or {}), "sample_exposure_time": float(sample_exposure_time)},
        namespace=namespace,
        xray_generator=xray_generator,
    )
    yield from mouse_eiger_measure(eiger, destination, exposure_time=sample_exposure_time)

    yield from bps.mv(shutter, 0)
