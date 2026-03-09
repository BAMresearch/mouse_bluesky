from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np
from bluesky import RunEngine
from mouse_bluesky.interactive.scans import capillary_scan, edge_scan, peak_scan, valley_scan
from ophyd import Signal
from ophyd.sim import SynAxis, SynSignal


@dataclass
class SimBundle:
    motor: SynAxis
    detector: SynSignal
    RE: RunEngine


def _attach_exposure_signals(detector: SynSignal) -> SynSignal:
    detector.cam = SimpleNamespace(
        acquire_time=Signal(name=f"{detector.name}_acquire_time", value=0.1),
        acquire_period=Signal(name=f"{detector.name}_acquire_period", value=0.1),
    )
    return detector


def make_peak_bundle(center: float = 0.35, sigma: float = 0.18) -> SimBundle:
    motor = SynAxis(name="motor")
    detector = SynSignal(
        func=lambda: float(np.exp(-((motor.readback.get() - center) ** 2) / (2.0 * sigma**2))),
        name="eiger",
    )
    return SimBundle(motor=motor, detector=_attach_exposure_signals(detector), RE=RunEngine({}))


def make_valley_bundle(center: float = -0.2, sigma: float = 0.15) -> SimBundle:
    motor = SynAxis(name="motor")
    detector = SynSignal(
        func=lambda: float(1.0 - np.exp(-((motor.readback.get() - center) ** 2) / (2.0 * sigma**2))),
        name="eiger",
    )
    return SimBundle(motor=motor, detector=_attach_exposure_signals(detector), RE=RunEngine({}))


def make_edge_bundle(center: float = 0.1, scale: float = 0.05) -> SimBundle:
    motor = SynAxis(name="motor")
    detector = SynSignal(
        func=lambda: float(1.0 / (1.0 + np.exp(-(motor.readback.get() - center) / scale))),
        name="eiger",
    )
    return SimBundle(motor=motor, detector=_attach_exposure_signals(detector), RE=RunEngine({}))


def make_capillary_bundle(left: float = -0.35, right: float = 0.35, mid_amp: float = 0.25) -> SimBundle:
    motor = SynAxis(name="motor")

    def func() -> float:
        x = motor.readback.get()
        valley = -1.0 if left <= x <= right else 0.0
        mid = mid_amp * np.exp(-(x**2) / (2.0 * 0.08**2))
        return float(1.0 + valley + mid)

    detector = SynSignal(func=func, name="eiger")
    return SimBundle(motor=motor, detector=_attach_exposure_signals(detector), RE=RunEngine({}))


def test_peak_scan_simulated_gaussian() -> None:
    sim = make_peak_bundle()
    result = peak_scan(
        sim.motor,
        -1.0,
        1.0,
        RE=sim.RE,
        dets=[sim.detector],
        num=41,
        exposure_time=0.0,
        table=False,
        plot=False,
    )
    assert result.fit_center is not None
    assert abs(result.fit_center - 0.35) < 0.12
    assert sim.detector.cam.acquire_time.get() == 0.0


def test_valley_scan_simulated_gaussian() -> None:
    sim = make_valley_bundle()
    result = valley_scan(
        sim.motor,
        -1.0,
        1.0,
        RE=sim.RE,
        dets=[sim.detector],
        num=41,
        exposure_time=0.0,
        table=False,
        plot=False,
    )
    assert result.fit_center is not None
    assert abs(result.fit_center + 0.2) < 0.12


def test_edge_scan_simulated_logistic_edge() -> None:
    sim = make_edge_bundle()
    result = edge_scan(
        sim.motor,
        -1.0,
        1.0,
        RE=sim.RE,
        dets=[sim.detector],
        num=41,
        exposure_time=0.0,
        table=False,
        plot=False,
        form="logistic",
    )
    assert result.fit_center is not None
    assert abs(result.fit_center - 0.1) < 0.12


def test_capillary_scan_simulated_profile() -> None:
    sim = make_capillary_bundle()
    result = capillary_scan(
        sim.motor,
        -1.0,
        1.0,
        RE=sim.RE,
        dets=[sim.detector],
        num=61,
        exposure_time=0.0,
        table=False,
        plot=False,
    )
    assert result.fit_center is not None
    assert abs(result.fit_center) < 0.15
