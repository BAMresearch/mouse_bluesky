from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .models import PlanSpec


def insert_apply_config_on_change(
    specs: Iterable[PlanSpec],
    *,
    apply_plan_name: str = "apply_config",
    config_kwarg: str = "config_id",
    meta_config_key: str = "config_id",
    extra_apply_kwargs: Mapping[str, Any] | None = None,
) -> list[PlanSpec]:
    """Insert `apply_config(config_id)` only when config changes in the sequence."""
    out: list[PlanSpec] = []
    last_cfg: int | None = None
    extra = dict(extra_apply_kwargs or {})

    for s in specs:
        cfg = s.meta.get(meta_config_key, s.kwargs.get(config_kwarg))
        cfg_int: int | None = None
        if cfg is not None:
            try:
                cfg_int = int(cfg)
            except Exception:
                cfg_int = None

        if cfg_int is not None and cfg_int != last_cfg:
            out.append(PlanSpec(name=apply_plan_name, kwargs={config_kwarg: cfg_int, **extra}, meta={"config_id": cfg_int}))
            last_cfg = cfg_int

        out.append(s)

    return out
