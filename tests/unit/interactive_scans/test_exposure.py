from __future__ import annotations

from types import SimpleNamespace

from bluesky import RunEngine
from ophyd import Signal

from mouse_bluesky.interactive.exposure import configure_detector_exposure


def test_configure_detector_exposure_updates_expected_signals(tmp_path) -> None:
    acquire_time = Signal(name="acquire_time", value=0.1)
    acquire_period = Signal(name="acquire_period", value=0.1)
    num_images = Signal(name="num_images", value=1)
    file_path = Signal(name="file_path", value="")
    detector = SimpleNamespace(
        cam=SimpleNamespace(
            acquire_time=acquire_time,
            acquire_period=acquire_period,
            num_images=num_images,
            file_path=file_path,
        )
    )

    RE = RunEngine({})
    RE(configure_detector_exposure(detector, 25, output_path=tmp_path))

    assert num_images.get() == 3
    assert acquire_time.get() == acquire_period.get() == (25 / 3)
    assert file_path.get() == tmp_path.as_posix()


def test_configure_detector_exposure_clamps_non_positive_exposure_to_one_second(tmp_path) -> None:
    acquire_time = Signal(name="acquire_time", value=0.1)
    acquire_period = Signal(name="acquire_period", value=0.1)
    num_images = Signal(name="num_images", value=2)
    file_path = Signal(name="file_path", value="")
    detector = SimpleNamespace(
        cam=SimpleNamespace(
            acquire_time=acquire_time,
            acquire_period=acquire_period,
            num_images=num_images,
            file_path=file_path,
        )
    )

    RE = RunEngine({})
    RE(configure_detector_exposure(detector, 0.0, output_path=tmp_path))

    assert num_images.get() == 1
    assert acquire_time.get() == acquire_period.get() == 1.0
