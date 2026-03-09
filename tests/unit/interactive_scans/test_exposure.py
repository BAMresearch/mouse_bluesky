from __future__ import annotations

from types import SimpleNamespace

from bluesky import RunEngine
from mouse_bluesky.interactive.exposure import configure_detector_exposure
from ophyd import Signal


def test_configure_detector_exposure_updates_expected_signals() -> None:
    acquire_time = Signal(name="acquire_time", value=0.1)
    acquire_period = Signal(name="acquire_period", value=0.1)
    detector = SimpleNamespace(cam=SimpleNamespace(acquire_time=acquire_time, acquire_period=acquire_period))

    RE = RunEngine({})
    RE(configure_detector_exposure(detector, 0.25))

    assert acquire_time.get() == 0.25
    assert acquire_period.get() == 0.25


def test_configure_detector_exposure_is_noop_when_signal_missing() -> None:
    detector = SimpleNamespace(cam=SimpleNamespace())

    RE = RunEngine({})
    RE(configure_detector_exposure(detector, 0.25))
