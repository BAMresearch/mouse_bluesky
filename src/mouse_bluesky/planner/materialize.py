from __future__ import annotations

from collections.abc import Iterator, Sequence

from .models import PlanFnRegistry, PlanSpec


def materialize_plans(specs: Sequence[PlanSpec], plan_funcs: PlanFnRegistry) -> list[Iterator]:
    """Convert PlanSpecs to actual plan generators for interactive RE usage."""
    plans: list[Iterator] = []
    for s in specs:
        try:
            fn = plan_funcs[s.name]
        except KeyError as e:
            raise ValueError(f"Unknown plan name {s.name!r} in materialize_plans") from e
        plans.append(fn(**dict(s.kwargs)))
    return plans
