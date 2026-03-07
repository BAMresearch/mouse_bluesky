"""Public interactive scan functions with sensible defaults."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import bluesky.plans as bp
from bluesky import preprocessors as bpp
from bluesky.callbacks import LiveTable
from bluesky.callbacks.fitting import LiveFit, PeakStats
from bluesky.callbacks.mpl_plotting import LivePlot

from .defaults import (
    DEFAULT_EDGE_DIRECTION,
    DEFAULT_EDGE_FORM,
    DEFAULT_EXPOSURE_TIME,
    DEFAULT_NUM,
    DEFAULT_PLOT,
    DEFAULT_PROFILE,
    DEFAULT_TABLE,
    DEFAULT_UPDATE_EVERY,
)
from .exposure import configure_detectors_exposure
from .fit_models import (
    EdgeDirection,
    EdgeForm,
    PeakProfile,
    ValleyProfile,
    capillary_init_guess,
    capillary_model,
    edge_init_guess,
    edge_model,
    peak_or_valley_init_guess,
    peak_or_valley_model,
    safe_param_value,
)
from .results import ScanResult
from .runtime import coerce_uid, resolve_default_detector, resolve_detector_field, resolve_run_engine


def _build_callbacks(
    *,
    detector_field: str,
    motor: Any,
    livefit: LiveFit,
    peak_stats: PeakStats | None,
    plot: bool,
    table: bool,
) -> list[Any]:
    """Create the standard callback list for an interactive scan."""
    callbacks: list[Any] = [livefit]
    if peak_stats is not None:
        callbacks.append(peak_stats)
    if table:
        callbacks.append(LiveTable([motor.name, detector_field]))
    if plot:
        callbacks.append(LivePlot(detector_field, x=motor.name))
    return callbacks


def _run_scan(
    RE: Any,
    *,
    kind: str,
    dets: Sequence[Any],
    detector_field: str,
    motor: Any,
    start: float,
    stop: float,
    num: int,
    exposure_time: float,
    livefit: LiveFit,
    peak_stats: PeakStats | None,
    plot: bool,
    table: bool,
    md: Mapping[str, Any] | None,
) -> Any:
    """Execute a 1D scan with configured detector exposure and callbacks."""
    callbacks = _build_callbacks(
        detector_field=detector_field,
        motor=motor,
        livefit=livefit,
        peak_stats=peak_stats,
        plot=plot,
        table=table,
    )

    scan_md = {
        "interactive_scan_kind": kind,
        "interactive_fit_field": detector_field,
        "interactive_motor": motor.name,
        "interactive_exposure_time_s": exposure_time,
    }
    if md:
        scan_md.update(dict(md))

    plan = bp.scan(list(dets), motor, start, stop, num, md=scan_md)
    plan = bpp.pchain(configure_detectors_exposure(list(dets), exposure_time), plan)
    uid = RE(plan, callbacks)
    return coerce_uid(uid)


def peak_scan(
    motor: Any,
    start: float,
    stop: float,
    *,
    RE: Any | None = None,
    dets: Sequence[Any] | Any | None = None,
    detector_field: str | None = None,
    num: int = DEFAULT_NUM,
    exposure_time: float = DEFAULT_EXPOSURE_TIME,
    profile: PeakProfile = DEFAULT_PROFILE,
    plot: bool = DEFAULT_PLOT,
    table: bool = DEFAULT_TABLE,
    update_every: int | None = DEFAULT_UPDATE_EVERY,
    md: Mapping[str, Any] | None = None,
) -> ScanResult:
    """Scan across a peak and return fit center, CEN, COM, and width.

    Parameters
    ----------
    motor
        Motor-like object to scan.
    start, stop
        Scan endpoints.
    RE
        RunEngine. Defaults to `RE` from the interactive namespace.
    dets
        Detector or detectors. Defaults to the interactive `eiger` device.
    detector_field
        Data field to fit and plot. Defaults to the single detector name.
    num
        Number of evenly spaced scan points.
    exposure_time
        Detector frame capture time in seconds.
    profile
        Peak model: `gaussian`, `lorentzian`, or `trapezoid`.
    plot
        Whether to attach a standard Bluesky live plot.
    table
        Whether to attach a live table.
    """
    resolved_RE = resolve_run_engine(RE)
    detectors = resolve_default_detector(dets)
    y_name = resolve_detector_field(detectors, detector_field)
    x_name = motor.name

    model = peak_or_valley_model(profile)
    livefit = LiveFit(
        model,
        y=y_name,
        independent_vars={"x": x_name},
        init_guess=peak_or_valley_init_guess(profile, start=start, stop=stop, invert=False),
        update_every=update_every,
    )
    peak_stats = PeakStats(x_name, y_name)
    uid = _run_scan(
        resolved_RE,
        kind="peak",
        dets=detectors,
        detector_field=y_name,
        motor=motor,
        start=start,
        stop=stop,
        num=num,
        exposure_time=exposure_time,
        livefit=livefit,
        peak_stats=peak_stats,
        plot=plot,
        table=table,
        md=md,
    )

    result = livefit.result
    width = safe_param_value(result, "p_fwhm")
    if width is None and profile == "trapezoid":
        left = safe_param_value(result, "p_center1")
        right = safe_param_value(result, "p_center2")
        width = abs(right - left) if left is not None and right is not None else None

    return ScanResult(
        uid=uid,
        kind="peak",
        detector_field=y_name,
        motor_field=x_name,
        fit_success=bool(getattr(result, "success", False)),
        fit_message=getattr(result, "message", None),
        fit_center=safe_param_value(result, "p_center"),
        com=getattr(peak_stats, "com", None),
        cen=getattr(peak_stats, "cen", None),
        width=width if width is not None else getattr(peak_stats, "fwhm", None),
        fit_result=result,
        peak_stats=peak_stats,
        livefit=livefit,
        extra={"profile": profile, "exposure_time": exposure_time},
    )


def valley_scan(
    motor: Any,
    start: float,
    stop: float,
    *,
    RE: Any | None = None,
    dets: Sequence[Any] | Any | None = None,
    detector_field: str | None = None,
    num: int = DEFAULT_NUM,
    exposure_time: float = DEFAULT_EXPOSURE_TIME,
    profile: ValleyProfile = DEFAULT_PROFILE,
    plot: bool = DEFAULT_PLOT,
    table: bool = DEFAULT_TABLE,
    update_every: int | None = DEFAULT_UPDATE_EVERY,
    md: Mapping[str, Any] | None = None,
) -> ScanResult:
    """Scan across a valley and return fit center, CEN, COM, and width."""
    resolved_RE = resolve_run_engine(RE)
    detectors = resolve_default_detector(dets)
    y_name = resolve_detector_field(detectors, detector_field)
    x_name = motor.name

    model = peak_or_valley_model(profile)
    livefit = LiveFit(
        model,
        y=y_name,
        independent_vars={"x": x_name},
        init_guess=peak_or_valley_init_guess(profile, start=start, stop=stop, invert=True),
        update_every=update_every,
    )
    peak_stats = PeakStats(x_name, y_name)
    uid = _run_scan(
        resolved_RE,
        kind="valley",
        dets=detectors,
        detector_field=y_name,
        motor=motor,
        start=start,
        stop=stop,
        num=num,
        exposure_time=exposure_time,
        livefit=livefit,
        peak_stats=peak_stats,
        plot=plot,
        table=table,
        md=md,
    )

    result = livefit.result
    width = safe_param_value(result, "p_fwhm")
    if width is None and profile == "trapezoid":
        left = safe_param_value(result, "p_center1")
        right = safe_param_value(result, "p_center2")
        width = abs(right - left) if left is not None and right is not None else None

    return ScanResult(
        uid=uid,
        kind="valley",
        detector_field=y_name,
        motor_field=x_name,
        fit_success=bool(getattr(result, "success", False)),
        fit_message=getattr(result, "message", None),
        fit_center=safe_param_value(result, "p_center"),
        com=getattr(peak_stats, "com", None),
        cen=getattr(peak_stats, "cen", None),
        width=width if width is not None else getattr(peak_stats, "fwhm", None),
        fit_result=result,
        peak_stats=peak_stats,
        livefit=livefit,
        extra={"profile": profile, "exposure_time": exposure_time},
    )


def edge_scan(
    motor: Any,
    start: float,
    stop: float,
    *,
    RE: Any | None = None,
    dets: Sequence[Any] | Any | None = None,
    detector_field: str | None = None,
    num: int = DEFAULT_NUM,
    exposure_time: float = DEFAULT_EXPOSURE_TIME,
    direction: EdgeDirection = DEFAULT_EDGE_DIRECTION,
    form: EdgeForm = DEFAULT_EDGE_FORM,
    plot: bool = DEFAULT_PLOT,
    table: bool = DEFAULT_TABLE,
    update_every: int | None = DEFAULT_UPDATE_EVERY,
    md: Mapping[str, Any] | None = None,
) -> ScanResult:
    """Scan across an edge and return center and characteristic width."""
    resolved_RE = resolve_run_engine(RE)
    detectors = resolve_default_detector(dets)
    y_name = resolve_detector_field(detectors, detector_field)
    x_name = motor.name

    model = edge_model(form=form)
    livefit = LiveFit(
        model,
        y=y_name,
        independent_vars={"x": x_name},
        init_guess=edge_init_guess(start=start, stop=stop, direction=direction),
        update_every=update_every,
    )
    uid = _run_scan(
        resolved_RE,
        kind="edge",
        dets=detectors,
        detector_field=y_name,
        motor=motor,
        start=start,
        stop=stop,
        num=num,
        exposure_time=exposure_time,
        livefit=livefit,
        peak_stats=None,
        plot=plot,
        table=table,
        md=md,
    )

    result = livefit.result
    center = safe_param_value(result, "edge_center")
    sigma = safe_param_value(result, "edge_sigma")

    return ScanResult(
        uid=uid,
        kind="edge",
        detector_field=y_name,
        motor_field=x_name,
        fit_success=bool(getattr(result, "success", False)),
        fit_message=getattr(result, "message", None),
        fit_center=center,
        com=center,
        cen=center,
        width=abs(sigma) if sigma is not None else None,
        fit_result=result,
        peak_stats=None,
        livefit=livefit,
        extra={"direction": direction, "form": form, "exposure_time": exposure_time},
    )


def capillary_scan(
    motor: Any,
    start: float,
    stop: float,
    *,
    RE: Any | None = None,
    dets: Sequence[Any] | Any | None = None,
    detector_field: str | None = None,
    num: int = DEFAULT_NUM,
    exposure_time: float = DEFAULT_EXPOSURE_TIME,
    plot: bool = DEFAULT_PLOT,
    table: bool = DEFAULT_TABLE,
    update_every: int | None = DEFAULT_UPDATE_EVERY,
    md: Mapping[str, Any] | None = None,
) -> ScanResult:
    """Scan across a capillary profile and return fitted mid-center and width."""
    resolved_RE = resolve_run_engine(RE)
    detectors = resolve_default_detector(dets)
    y_name = resolve_detector_field(detectors, detector_field)
    x_name = motor.name

    model = capillary_model()
    livefit = LiveFit(
        model,
        y=y_name,
        independent_vars={"x": x_name},
        init_guess=capillary_init_guess(start=start, stop=stop),
        update_every=update_every,
    )
    uid = _run_scan(
        resolved_RE,
        kind="capillary",
        dets=detectors,
        detector_field=y_name,
        motor=motor,
        start=start,
        stop=stop,
        num=num,
        exposure_time=exposure_time,
        livefit=livefit,
        peak_stats=None,
        plot=plot,
        table=table,
        md=md,
    )

    result = livefit.result
    left = safe_param_value(result, "cap_center1")
    right = safe_param_value(result, "cap_center2")
    mid_center = safe_param_value(result, "mid_center")

    width = abs(right - left) if left is not None and right is not None else None

    return ScanResult(
        uid=uid,
        kind="capillary",
        detector_field=y_name,
        motor_field=x_name,
        fit_success=bool(getattr(result, "success", False)),
        fit_message=getattr(result, "message", None),
        fit_center=mid_center,
        com=mid_center,
        cen=mid_center,
        width=width,
        fit_result=result,
        peak_stats=None,
        livefit=livefit,
        extra={
            "left_center": left,
            "right_center": right,
            "mid_center": mid_center,
            "exposure_time": exposure_time,
        },
    )
