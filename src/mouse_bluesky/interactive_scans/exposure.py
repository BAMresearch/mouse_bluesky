"""Detector exposure-time helpers for interactive scans."""

from __future__ import annotations

from typing import Any

import bluesky.plan_stubs as bps

EIGER_EXPOSURE_SIGNAL_PATH = "cam.acquire_time"
EIGER_PERIOD_SIGNAL_PATH = "cam.acquire_period"

def _resolve_signal(device: Any, dotted_name: str) -> Any:
    """Resolve a dotted attribute path on a device."""
    current = device
    for part in dotted_name.split("."):
        current = getattr(current, part)
    return current


def configure_detector_exposure(detector: Any, exposure_time: float):
    """Yield plan messages that configure detector exposure for Eiger-like devices.

    TODO: check the final IOC field names in the lab and update constants above.
    """
    try:
        exposure_signal = _resolve_signal(detector, EIGER_EXPOSURE_SIGNAL_PATH)
    except AttributeError:
        return

    yield from bps.mv(exposure_signal, exposure_time)

    try:
        period_signal = _resolve_signal(detector, EIGER_PERIOD_SIGNAL_PATH)
    except AttributeError:
        pass
    else:
        yield from bps.mv(period_signal, max(float(exposure_time), 0.0))


def configure_detectors_exposure(detectors: list[Any], exposure_time: float):
    """Configure exposure time for each detector when supported."""
    for detector in detectors:
        yield from configure_detector_exposure(detector, exposure_time)
