from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Callable, Tuple

from .models import PlanSpec


def annotate_sequence_index(
    specs: Iterable[PlanSpec],
    *,
    is_measurement: Callable[[PlanSpec], bool] | None = None,
    start: int = 0,
    field: str = "sequence_index",
) -> list[PlanSpec]:
    """Return new PlanSpecs with a monotonic sequence index added to kwargs and meta.

    By default, counts only `measure_yzstage` items.
    """
    def is_measurement(s: PlanSpec) -> bool:
        return s.name == "measure_yzstage"

    out: list[PlanSpec] = []
    seq = start
    for s in specs:
        if is_measurement(s):
            new_kwargs = dict(s.kwargs)
            new_meta = dict(s.meta)
            new_kwargs[field] = seq
            new_meta[field] = seq
            out.append(PlanSpec(name=s.name, kwargs=new_kwargs, meta=new_meta))
            seq += 1
        else:
            out.append(s)
    return out
