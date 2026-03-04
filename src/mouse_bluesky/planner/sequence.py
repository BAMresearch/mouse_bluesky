from __future__ import annotations

from collections.abc import Iterable
from typing import Callable

from .models import PlanSpec


def annotate_sequence_index(
    specs: Iterable[PlanSpec],
    *,
    is_measurement: Callable[[PlanSpec], bool] | None = None,
    start: int = 0,
    field: str = "sequence_index",
) -> list[PlanSpec]:
    """Annotate measurement specs with a monotonic `sequence_index`."""
    predicate = is_measurement or (lambda spec: spec.name == "measure_yzstage")

    out: list[PlanSpec] = []
    seq = start
    for s in specs:
        if predicate(s):
            new_kwargs = dict(s.kwargs)
            new_meta = dict(s.meta)
            new_kwargs[field] = seq
            new_meta[field] = seq
            out.append(PlanSpec(name=s.name, kwargs=new_kwargs, meta=new_meta))
            seq += 1
        else:
            out.append(s)
    return out
