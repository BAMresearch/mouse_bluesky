"""Fitting models and lightweight numerical helpers."""

from __future__ import annotations

from typing import Literal

import numpy as np
from lmfit.model import ModelResult
from lmfit.models import ConstantModel, GaussianModel, LorentzianModel, RectangleModel, StepModel

PeakProfile = Literal["gaussian", "lorentzian", "trapezoid"]
ValleyProfile = Literal["gaussian", "lorentzian", "trapezoid"]
EdgeDirection = Literal["auto", "up", "down"]
EdgeForm = Literal["erf", "logistic", "atan", "linear"]


def safe_param_value(result: ModelResult | None, *names: str) -> float | None:
    """Return the first available fitted parameter value."""
    if result is None:
        return None
    for name in names:
        param = result.params.get(name)
        if param is not None and param.value is not None:
            return float(param.value)
    return None


def guess_sigma(start: float, stop: float) -> float:
    """Estimate a sensible width scale from the scan span."""
    span = abs(float(stop) - float(start))
    return max(span / 10.0, np.finfo(float).eps)


def peak_or_valley_model(profile: PeakProfile | ValleyProfile):
    """Build a peak-like model with constant background."""
    background = ConstantModel(prefix="bkg_")
    if profile == "gaussian":
        return background + GaussianModel(prefix="p_")
    if profile == "lorentzian":
        return background + LorentzianModel(prefix="p_")
    if profile == "trapezoid":
        return background + RectangleModel(prefix="p_", form="linear", independent_vars=["x"])
    raise ValueError(f"Unsupported profile: {profile!r}")


def peak_or_valley_init_guess(
    profile: PeakProfile | ValleyProfile,
    *,
    start: float,
    stop: float,
    invert: bool,
) -> dict[str, float]:
    """Create initial fit guesses for peak-like models."""
    center = (float(start) + float(stop)) / 2.0
    sigma = guess_sigma(start, stop)
    amplitude = -1.0 if invert else 1.0

    if profile in {"gaussian", "lorentzian"}:
        return {
            "bkg_c": 0.0,
            "p_amplitude": amplitude,
            "p_center": center,
            "p_sigma": sigma,
        }

    return {
        "bkg_c": 0.0,
        "p_amplitude": amplitude,
        "p_center1": center - sigma,
        "p_center2": center + sigma,
        "p_sigma1": sigma / 2.0,
        "p_sigma2": sigma / 2.0,
    }


def edge_model(form: EdgeForm = "erf"):
    """Build a sigmoidal edge model with constant background."""
    return ConstantModel(prefix="bkg_") + StepModel(prefix="edge_", form=form, independent_vars=["x"])


def edge_init_guess(*, start: float, stop: float, direction: EdgeDirection) -> dict[str, float]:
    """Create initial guesses for an edge fit."""
    center = (float(start) + float(stop)) / 2.0
    sigma = guess_sigma(start, stop)
    sigma = -abs(sigma) if direction == "down" else abs(sigma)
    return {
        "bkg_c": 0.0,
        "edge_amplitude": 1.0,
        "edge_center": center,
        "edge_sigma": sigma,
    }


def capillary_model():
    """Build a pragmatic capillary profile model."""
    background = ConstantModel(prefix="bkg_")
    valley = RectangleModel(prefix="cap_", form="erf", independent_vars=["x"])
    center_bump = GaussianModel(prefix="mid_")
    return background + valley + center_bump


def capillary_init_guess(*, start: float, stop: float) -> dict[str, float]:
    """Create initial guesses for a capillary scan fit."""
    center = (float(start) + float(stop)) / 2.0
    span = abs(float(stop) - float(start))
    half_width = max(span / 6.0, np.finfo(float).eps)
    edge_sigma = max(span / 30.0, np.finfo(float).eps)
    return {
        "bkg_c": 0.0,
        "cap_amplitude": -1.0,
        "cap_center1": center - half_width,
        "cap_center2": center + half_width,
        "cap_sigma1": edge_sigma,
        "cap_sigma2": edge_sigma,
        "mid_amplitude": 0.25,
        "mid_center": center,
        "mid_sigma": max(span / 20.0, np.finfo(float).eps),
    }
