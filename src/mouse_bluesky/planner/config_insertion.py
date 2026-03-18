from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .models import PlanSpec


def _coerce_config_id(spec: PlanSpec, *, config_kwarg: str, meta_config_key: str) -> int | None:
    cfg = spec.meta.get(meta_config_key, spec.kwargs.get(config_kwarg))
    if cfg is None:
        return None
    try:
        return int(cfg)
    except Exception:
        return None


def insert_apply_config_before_measurements(
    specs: Iterable[PlanSpec],
    *,
    apply_plan_name: str = "apply_config",
    measurement_plan_name: str = "measure_yzstage",
    config_kwarg: str = "config_id",
    meta_config_key: str = "config_id",
    extra_apply_kwargs: Mapping[str, Any] | None = None,
) -> list[PlanSpec]:
    """Insert `apply_config(config_id)` before every matching measurement plan."""
    out: list[PlanSpec] = []
    extra = dict(extra_apply_kwargs or {})

    for s in specs:
        if s.name == measurement_plan_name:
            cfg_int = _coerce_config_id(s, config_kwarg=config_kwarg, meta_config_key=meta_config_key)
            if cfg_int is not None:
                out.append(
                    PlanSpec(
                        name=apply_plan_name,
                        kwargs={config_kwarg: cfg_int, **extra},
                        meta={"config_id": cfg_int},
                    )
                )
        out.append(s)

    return out


def insert_apply_config_on_change(
    specs: Iterable[PlanSpec],
    *,
    apply_plan_name: str = "apply_config",
    measurement_plan_name: str = "measure_yzstage",
    config_kwarg: str = "config_id",
    meta_config_key: str = "config_id",
    extra_apply_kwargs: Mapping[str, Any] | None = None,
) -> list[PlanSpec]:
    """Compatibility wrapper for the current per-measurement config insertion policy."""
    return insert_apply_config_before_measurements(
        specs,
        apply_plan_name=apply_plan_name,
        measurement_plan_name=measurement_plan_name,
        config_kwarg=config_kwarg,
        meta_config_key=meta_config_key,
        extra_apply_kwargs=extra_apply_kwargs,
    )
