"""Result containers for interactive scans."""

from __future__ import annotations

from typing import Any

import attrs
from lmfit.model import ModelResult


@attrs.define(slots=True)
class DerivedStats:
    """Derived 1D statistics computed from sampled x/y data."""

    com: float | None = None
    cen: float | None = None
    fwhm: float | None = None
    max_x: float | None = None
    min_x: float | None = None
    crossings: tuple[float, ...] = attrs.field(factory=tuple)


@attrs.define(slots=True)
class ScanResult:
    """Structured result returned by an interactive scan."""

    uid: Any
    kind: str
    detector_field: str
    motor_field: str
    fit_success: bool
    fit_message: str | None
    fit_center: float | None
    com: float | None
    cen: float | None
    width: float | None
    fit_result: ModelResult | None = None
    peak_stats: Any | None = None
    livefit: Any | None = None
    extra: dict[str, Any] = attrs.field(factory=dict)
