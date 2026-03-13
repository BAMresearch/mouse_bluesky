"""Detector exposure-time helpers for interactive scans."""

from __future__ import annotations

from pathlib import Path

from mouse_bluesky.devices.eiger import ad_configure_exposure

DEFAULT_EIGER_OUTPUT_PATH = "/tmp/current/"


def configure_detector_exposure(
    detector: object, exposure_time: float, *, output_path: Path | str = DEFAULT_EIGER_OUTPUT_PATH
):
    """Configure Eiger detector exposure for interactive scans."""
    yield from ad_configure_exposure(detector, exposure_time=exposure_time, output_path=output_path)


def configure_detectors_exposure(
    detectors: list[object],
    exposure_time: float,
    *,
    output_path: Path | str = DEFAULT_EIGER_OUTPUT_PATH,
):
    """Configure exposure time for each Eiger detector."""
    for detector in detectors:
        yield from configure_detector_exposure(detector, exposure_time, output_path=output_path)
