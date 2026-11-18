from __future__ import annotations

from collections.abc import Sequence

from ..processing_marker import UNRESOLVED_YMD_SENTINEL
from .models import PlanSpec


def insert_ymd_complete_markers(
    specs: Sequence[PlanSpec],
    *,
    measurement_plan_name: str = "measure_yzstage",
    marker_plan_name: str = "mark_ymd_complete",
) -> list[PlanSpec]:
    """Insert one processing trigger after each YMD's last scheduled measurement."""
    last = {}
    for index, spec in enumerate(specs):
        ymd = spec.kwargs.get("ymd")
        if spec.name == measurement_plan_name and ymd and ymd != UNRESOLVED_YMD_SENTINEL:
            last[ymd] = index
    out = []
    for index, spec in enumerate(specs):
        out.append(spec)
        ymd = spec.kwargs.get("ymd")
        if spec.name != measurement_plan_name or last.get(ymd) != index:
            continue
        kwargs = {"ymd": ymd}
        if "root_path" in spec.kwargs:
            kwargs["root_path"] = spec.kwargs["root_path"]
        out.append(PlanSpec(name=marker_plan_name, kwargs=kwargs, meta={"ymd": ymd}))
    return out
