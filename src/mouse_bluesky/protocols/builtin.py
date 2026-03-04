from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..planner.models import CollatePolicy, CompiledEntry, PlanSpec
from .registry import LogbookEntryLike, ProtocolRegistry, ProtocolSpec


def _sample_key(e: LogbookEntryLike) -> str:
    return f"{e.proposal}-{e.sampleid}"


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
            "sampleposition": entry.positions,
            "ymd": entry.ymd,
            "batchnum": entry.batchnum,
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
      - configs: [123, 160, 127]
      - repeats: 2
      - collate: ALLOW|FORBID (default ALLOW)
    """
    collate = params.get("collate", CollatePolicy.ALLOW)
    if not isinstance(collate, CollatePolicy):
        raise ValueError("collate must be CollatePolicy after parsing")

    configs = params.get("configs", [])
    if not isinstance(configs, list):
        raise ValueError("'configs' must be a list (use __json__ for lists)")
    config_ids = [int(x) for x in configs]

    repeats_raw = params.get("repeats", 1)

    # NEW: repeats can be int or list[int] aligned with configs
    if isinstance(repeats_raw, list):
        repeats_list = [int(x) for x in repeats_raw]
        if len(repeats_list) != len(config_ids):
            raise ValueError(
                f"'repeats' length ({len(repeats_list)}) must match 'configs' length ({len(config_ids)})"
            )
    else:
        repeats_int = int(repeats_raw)
        if repeats_int < 1:
            raise ValueError("'repeats' must be >= 1")
        repeats_list = [repeats_int] * len(config_ids)

    sample_key = _sample_key(entry)

    specs: list[PlanSpec] = []
    for step, (cfg, nrep) in enumerate(zip(config_ids, repeats_list, strict=True)):
        if nrep < 1:
            raise ValueError(f"repeats[{step}] must be >= 1 (got {nrep})")
        for r in range(nrep):
            specs.append(
                PlanSpec(
                    name="measure_yzstage",
                    kwargs={
                        "entry_row_index": entry.row_index,
                        "proposal": entry.proposal,
                        "sampleid": entry.sampleid,
                        "sampos": entry.sampos,
                        "ymd": entry.ymd,            # method call
                        "batchnum": entry.batchnum,
                        "config_id": cfg,
                        "repeat_index": r,
                        # sampleposition: ideally pass positions directly if JSON-able
                        "sampleposition": dict(getattr(entry, "positions", {}) or {}),
                    },
                    meta={"sample_key": sample_key, "config_id": cfg, "step": step, "repeat": r},
                )
            )
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
