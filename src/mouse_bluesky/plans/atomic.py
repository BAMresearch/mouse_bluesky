from __future__ import annotations

from pathlib import Path
from typing import Iterator

from bluesky import plan_stubs as bps
from mouse_bluesky.devices.eiger import ad_configure_exposure
from ..devices.mouse_motors import BeamStop, SampleStageYZ


def mouse_eiger_measure(eiger, destination: Path, *, exposure_time: float=1) -> Iterator:
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
    sample_exposure_time: float=600,
    destination: Path,
) -> Iterator:
    """Run the low-level Y/Z stage measurement sequence inside an active run."""
    in_position = beam_stop.bsr.position

    yield from bps.mv(shutter, 1)
    yield from bps.mv(beam_stop.bsr, beam_stop.out_position)

    yield from bps.mv(sample_stage_yz.y, sampleposition.get("ysam.blank", sample_stage_yz.y.position))
    yield from bps.mv(sample_stage_yz.z, sampleposition.get("zsam.blank", sample_stage_yz.z.position))

    yield from mouse_eiger_measure(eiger, destination / "beam_profile", exposure_time = 20)

    yield from bps.mv(sample_stage_yz.y, sampleposition.get("ysam", sample_stage_yz.y.position))
    yield from bps.mv(sample_stage_yz.z, sampleposition.get("zsam", sample_stage_yz.z.position))

    yield from mouse_eiger_measure(eiger, destination / "beam_profile_through_sample", exposure_time = 20)

    yield from bps.mv(beam_stop.bsr, in_position)
    yield from mouse_eiger_measure(eiger, destination, exposure_time= sample_exposure_time)

    yield from bps.mv(shutter, 0)
