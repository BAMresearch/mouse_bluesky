from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import numpy as np

from ..planner.models import CollatePolicy, CompiledEntry, PlanSpec
from .registry import LogbookEntryLike


def _integer(value: Any, name: str) -> int:
    # Excel logbooks often deliver whole numbers as "123.0", so accept any integral value.
    message = f"triangulation '{name}' must be an int"
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(message)
    if isinstance(value, int):
        return value
    try:
        number = float(value)
    except ValueError as exc:
        raise ValueError(message) from exc
    if not number.is_integer():  # Also rejects inf and nan.
        raise ValueError(message)
    return int(number)


def _number(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"triangulation '{name}' must be a finite number") from exc
    if isinstance(value, bool) or not math.isfinite(result):
        raise ValueError(f"triangulation '{name}' must be a finite number")
    return result


def compile_triangulation(entry: LogbookEntryLike, params: Mapping[str, Any]) -> CompiledEntry:
    """Compile an ordered distance series and one final configuration restore."""
    unknown = set(params) - {"configuration", "steps", "duration", "start", "stop", "collate"}
    if unknown:
        raise ValueError(f"Unknown triangulation parameters: {', '.join(sorted(unknown))}")
    collate = params.get("collate", CollatePolicy.FORBID)
    if not isinstance(collate, CollatePolicy):
        raise ValueError("collate must be CollatePolicy after parsing")
    if collate != CollatePolicy.FORBID:
        raise ValueError("triangulation requires collate=FORBID so points stay together and in order")
    if "configuration" not in params:
        raise ValueError("triangulation requires 'configuration' (int)")
    config_id = _integer(params["configuration"], "configuration")
    steps = _integer(params.get("steps", 50), "steps")
    if steps < 2:
        raise ValueError("triangulation 'steps' must be at least 2")
    duration = _number(params.get("duration", 60), "duration")
    if duration <= 0:
        raise ValueError("triangulation 'duration' must be greater than 0")
    start = _number(params.get("start", 500), "start")
    stop = _number(params.get("stop", -130), "stop")
    if start == stop:
        raise ValueError("triangulation 'start' and 'stop' must differ")

    specs = []
    for index, distance in enumerate(np.linspace(start, stop, steps)):
        detx = float(distance)
        specs.append(
            PlanSpec(
                name="measure_yzstage",
                kwargs={
                    "entry_row_index": entry.row_index,
                    "proposal": entry.proposal,
                    "sampleid": entry.sampleid,
                    "sampos": entry.sampos,
                    "ymd": entry.ymd,
                    "batchnum": entry.batchnum,
                    "config_id": config_id,
                    "repeat_index": 0,
                    "sampleposition": dict(entry.positions),
                    "sample_exposure_time": duration,
                    "md": {
                        "protocol": "triangulation",
                        "triangulation_index": index,
                        "triangulation_points": steps,
                        "triangulation_detx": detx,
                    },
                },
                meta={
                    "sample_key": f"{entry.proposal}-{entry.sampleid}",
                    "config_id": config_id,
                    "step": index,
                    "repeat": 0,
                    "apply_config_kwargs": {"detx": detx, "beam_stop_out": True},
                },
            )
        )
    specs.append(PlanSpec(name="apply_config", kwargs={"config_id": config_id}, meta={"config_id": config_id}))
    return CompiledEntry(collate=CollatePolicy.FORBID, specs=tuple(specs))
