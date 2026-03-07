"""Runtime helpers for resolving interactive defaults."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def get_ipython_user_ns() -> dict[str, Any]:
    """Return the active IPython namespace when available."""
    try:
        from IPython import get_ipython
    except ImportError:
        return {}

    shell = get_ipython()
    if shell is None:
        return {}
    return getattr(shell, "user_ns", {})


def resolve_run_engine(RE: Any | None) -> Any:
    """Resolve a RunEngine from the argument or the interactive namespace."""
    if RE is not None:
        return RE

    user_ns = get_ipython_user_ns()
    re_obj = user_ns.get("RE")
    if re_obj is None:
        raise ValueError("No RunEngine was provided and no `RE` was found in the interactive namespace.")
    return re_obj


def resolve_default_detector(dets: Sequence[Any] | Any | None) -> list[Any]:
    """Resolve detectors from the argument or the interactive `eiger` device."""
    if dets is None:
        user_ns = get_ipython_user_ns()
        eiger = user_ns.get("eiger")
        if eiger is None:
            raise ValueError(
                "No detectors were provided and no `eiger` device was found in the interactive namespace."
            )
        return [eiger]

    if isinstance(dets, Sequence) and not isinstance(dets, (str, bytes)):
        return list(dets)
    return [dets]


def resolve_detector_field(dets: Sequence[Any], detector_field: str | None) -> str:
    """Resolve the detector field name used for fitting and plotting."""
    if detector_field is not None:
        return detector_field
    if len(dets) != 1:
        names = [getattr(det, "name", repr(det)) for det in dets]
        raise ValueError(
            "`detector_field` must be provided when more than one detector is supplied. "
            f"Received detectors={names!r}."
        )
    return str(dets[0].name)


def coerce_uid(uid: Any) -> Any:
    """Normalize a RunEngine result to a single uid when possible."""
    if isinstance(uid, tuple) and len(uid) == 1:
        return uid[0]
    return uid
