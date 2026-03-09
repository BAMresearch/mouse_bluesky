"""Convenience one-shot measurement helpers for interactive workflows."""

from __future__ import annotations

import json
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import bluesky.plans as bp
from bluesky import preprocessors as bpp

from .exposure import configure_detectors_exposure
from .runtime import coerce_uid, resolve_default_detector, resolve_detector_field, resolve_run_engine


class _DocCollector:
    """Collect run documents and retain the last measured data payload."""

    def __init__(self) -> None:
        self.docs: list[tuple[str, dict[str, Any]]] = []
        self.last_data: dict[str, Any] | None = None

    def __call__(self, name: str, doc: dict[str, Any]) -> None:
        self.docs.append((name, doc))
        if name == "event":
            self.last_data = dict(doc.get("data", {}))
            return
        if name == "event_page":
            page_data = doc.get("data", {})
            self.last_data = {
                key: values[-1] if isinstance(values, Sequence) and not isinstance(values, (str, bytes)) else values
                for key, values in page_data.items()
            }


def _json_default(value: Any) -> Any:
    """Coerce non-JSON-native values into a serializable form."""
    if hasattr(value, "tolist"):
        return value.tolist()
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def _run_single_count(
    *,
    RE: Any,
    dets: list[Any],
    exposure_time: float,
    md: Mapping[str, Any] | None,
) -> tuple[Any, _DocCollector]:
    collector = _DocCollector()

    count_md = {
        "interactive_scan_kind": "count",
        "interactive_exposure_time_s": exposure_time,
    }
    if md:
        count_md.update(dict(md))

    plan = bp.count(dets, num=1, md=count_md)
    plan = bpp.pchain(configure_detectors_exposure(dets, exposure_time), plan)
    uid = coerce_uid(RE(plan, [collector]))
    return uid, collector


def ct(
    seconds: float = 1.0,
    *,
    RE: Any | None = None,
    dets: Sequence[Any] | Any | None = None,
    detector_field: str | None = None,
    md: Mapping[str, Any] | None = None,
) -> Any:
    """Run a quick one-shot exposure and return the measured detector counts."""
    resolved_RE = resolve_run_engine(RE)
    detectors = resolve_default_detector(dets)
    y_name = resolve_detector_field(detectors, detector_field)

    _, collector = _run_single_count(RE=resolved_RE, dets=detectors, exposure_time=seconds, md=md)
    if collector.last_data is None or y_name not in collector.last_data:
        raise RuntimeError(f"Detector field {y_name!r} was not present in the collected count data.")

    return collector.last_data[y_name]


def test_measure(
    seconds: float = 1.0,
    *,
    RE: Any | None = None,
    dets: Sequence[Any] | Any | None = None,
    detector_field: str | None = None,
    visualize: bool = False,
    md: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Collect one measurement, persist documents to a temporary file, and optionally plot."""
    resolved_RE = resolve_run_engine(RE)
    detectors = resolve_default_detector(dets)
    y_name = resolve_detector_field(detectors, detector_field)

    uid, collector = _run_single_count(RE=resolved_RE, dets=detectors, exposure_time=seconds, md=md)
    if collector.last_data is None or y_name not in collector.last_data:
        raise RuntimeError(f"Detector field {y_name!r} was not present in the collected count data.")

    temp_dir = Path(tempfile.mkdtemp(prefix="mouse_bluesky_test_measure_"))
    data_path = temp_dir / "measurement.json"
    payload = {
        "uid": uid,
        "seconds": seconds,
        "detector_field": y_name,
        "counts": collector.last_data[y_name],
        "last_data": collector.last_data,
        "documents": [{"name": name, "doc": doc} for name, doc in collector.docs],
    }
    data_path.write_text(json.dumps(payload, indent=2, default=_json_default), encoding="utf-8")

    plot_path: str | None = None
    # todo: update with an actual visualisation of the data. check for data location.
    # if visualize:
    #     try:
    #         import matplotlib.pyplot as plt
    #     except ImportError:
    #         plot_path = None
    #     else:
    #         fig, ax = plt.subplots(figsize=(5, 3))
    #         ax.bar([y_name], [collector.last_data[y_name]])
    #         ax.set_xlabel("Signal")
    #         ax.set_ylabel("Counts")
    #         ax.set_title("test_measure result")
    #         fig.tight_layout()
    #         image_path = temp_dir / "measurement.png"
    #         fig.savefig(image_path, dpi=120)
    #         plt.close(fig)
    #         plot_path = str(image_path)

    return {
        "uid": uid,
        "counts": collector.last_data[y_name],
        "data_path": str(data_path),
        "plot_path": plot_path,
    }
