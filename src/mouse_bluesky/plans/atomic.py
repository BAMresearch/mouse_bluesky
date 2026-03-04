from __future__ import annotations

from pathlib import Path
from typing import Iterator

from bluesky import plan_stubs as bps

from ..devices.mouse_motors import BeamStop, SampleStage


def mouse_eiger_measure(eiger, destination: Path, *, num_images: int) -> Iterator:
    destination.mkdir(parents=True, exist_ok=True)
    eiger.stage_sigs["cam.file_path"] = destination.as_posix()
    eiger.stage_sigs["cam.num_images"] = int(num_images)

    yield from bps.stage(eiger)
    try:
        yield from bps.trigger_and_read([eiger], name="mouse_eiger_measure")
    finally:
        yield from bps.unstage(eiger)


def measure_yzstage_atomic(
    *,
    eiger,
    sample_stage: SampleStage,
    beam_stop: BeamStop,
    shutter,
    sampleposition: dict[str, float],
    destination: Path,
) -> Iterator:
    """Atomic measurement: no open_run/close_run, no baseline, no metadata logic."""
    in_position = beam_stop.bsr.position

    yield from bps.mv(shutter, 1)
    yield from bps.mv(beam_stop.bsr, beam_stop.out_position)

    yield from bps.mv(sample_stage.y, sampleposition.get("ysam.blank", sample_stage.y.position))
    yield from bps.mv(sample_stage.z, sampleposition.get("zsam.blank", sample_stage.z.position))

    yield from mouse_eiger_measure(eiger, destination / "beam_profile", num_images=2)

    yield from bps.mv(sample_stage.y, sampleposition.get("ysam", sample_stage.y.position))
    yield from bps.mv(sample_stage.z, sampleposition.get("zsam", sample_stage.z.position))

    yield from mouse_eiger_measure(eiger, destination / "beam_profile_through_sample", num_images=2)

    yield from bps.mv(beam_stop.bsr, in_position)
    yield from mouse_eiger_measure(eiger, destination, num_images=1)

    yield from bps.mv(shutter, 0)
