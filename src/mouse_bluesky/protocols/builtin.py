from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..planner.models import CollatePolicy, CompiledEntry, PlanSpec
from .registry import LogbookEntryLike, ProtocolRegistry, ProtocolSpec


def _sample_key(e: LogbookEntryLike) -> str:
    return f"{e.proposal}:{e.sampleid}:{e.sampos}"


def compile_single_plan_protocol(
    *,
    plan_name: str,
    default_collate: CollatePolicy = CollatePolicy.FORBID,
    param_map: Mapping[str, str] | None = None,
):
    """Factory: protocol that compiles to exactly one PlanSpec (one QS item)."""
    mapping = dict(param_map or {})

    def _compile(entry: LogbookEntryLike, params: Mapping[str, Any]) -> CompiledEntry:
        collate = params.get("collate", default_collate)
        if not isinstance(collate, CollatePolicy):
            raise ValueError("collate must be CollatePolicy after parsing")

        kwargs: dict[str, Any] = {
            "entry_row_index": entry.row_index,
            "proposal": entry.proposal,
            "sampleid": entry.sampleid,
            "sampos": entry.sampos,
        }
        for k, v in params.items():
            if k == "collate":
                continue
            kwargs[mapping.get(k, k)] = v

        spec = PlanSpec(name=plan_name, kwargs=kwargs, meta={"sample_key": _sample_key(entry)})
        return CompiledEntry(collate=collate, specs=(spec,))

    return _compile


def compile_standard_measurements(entry: LogbookEntryLike, params: Mapping[str, Any]) -> CompiledEntry:
    """Generator-style protocol -> many PlanSpecs.

    Use `__json__` for typed params:
      - configs: [101, 102, 103]
      - repeats: 2
      - collate: ALLOW|FORBID (default ALLOW)
    """
    collate = params.get("collate", CollatePolicy.ALLOW)
    if not isinstance(collate, CollatePolicy):
        raise ValueError("collate must be CollatePolicy after parsing")

    configs = params.get("configs", [101])
    repeats = int(params.get("repeats", 1))

    if not isinstance(configs, list):
        raise ValueError("'configs' must be a list (use __json__ for lists)")
    if repeats < 1:
        raise ValueError("'repeats' must be >= 1")

    config_ids = [int(x) for x in configs]
    sample_key = _sample_key(entry)

    specs: list[PlanSpec] = []
    step = 0
    for cfg in config_ids:
        for r in range(repeats):
            specs.append(
                PlanSpec(
                    name="measure_yzstage",
                    kwargs={"entry_row_index": entry.row_index, "config_id": cfg, "repeat_index": r},
                    meta={"sample_key": sample_key, "config_id": cfg, "step": step, "repeat": r},
                )
            )
        step += 1

    return CompiledEntry(collate=collate, specs=tuple(specs))


def build_default_registry() -> ProtocolRegistry:
    reg = ProtocolRegistry()
    reg.register(
        ProtocolSpec(
            name="measure_once",
            compile=compile_single_plan_protocol(plan_name="measure_yzstage", default_collate=CollatePolicy.FORBID),
        )
    )
    reg.register(ProtocolSpec(name="standard_measurements", compile=compile_standard_measurements))
    return reg
