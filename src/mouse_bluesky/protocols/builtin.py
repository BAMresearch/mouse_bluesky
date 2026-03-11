from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..planner.models import CollatePolicy, CompiledEntry, PlanSpec
from .registry import LogbookEntryLike, ProtocolRegistry, ProtocolSpec


def _sample_key(e: LogbookEntryLike) -> str:
    """Build a stable grouping key used for collation metadata."""
    return f"{e.proposal}-{e.sampleid}"


def compile_single_plan_protocol(
    *,
    plan_name: str,
    default_collate: CollatePolicy = CollatePolicy.FORBID,
    param_map: Mapping[str, str] | None = None,
):
    """Build a compiler for protocols that map to exactly one plan item."""
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
    """Compile one entry into repeated per-config `measure_yzstage` plan specs.

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

    if isinstance(repeats_raw, list):
        repeats_list = [int(x) for x in repeats_raw]
        if len(repeats_list) != len(config_ids):
            raise ValueError(f"'repeats' length ({len(repeats_list)}) must match 'configs' length ({len(config_ids)})")
    else:
        repeats_int = int(repeats_raw)
        if repeats_int < 1:
            raise ValueError("'repeats' must be >= 1")
        repeats_list = [repeats_int] * len(config_ids)

    sample_exposure_time_raw = params.get("sample_exposure_time")
    if isinstance(sample_exposure_time_raw, list):
        sample_exposure_times = [float(x) for x in sample_exposure_time_raw]
        if len(sample_exposure_times) != len(config_ids):
            raise ValueError(
                "'sample_exposure_time' list length "
                f"({len(sample_exposure_times)}) must match 'configs' length ({len(config_ids)})"
            )
    elif sample_exposure_time_raw is None:
        sample_exposure_times = [None] * len(config_ids)
    else:
        sample_exposure_times = [float(sample_exposure_time_raw)] * len(config_ids)

    sample_key = _sample_key(entry)

    specs: list[PlanSpec] = []
    for step, (cfg, nrep, exposure_time) in enumerate(
        zip(config_ids, repeats_list, sample_exposure_times, strict=True)
    ):
        if nrep < 1:
            raise ValueError(f"repeats[{step}] must be >= 1 (got {nrep})")
        for r in range(nrep):
            kwargs: dict[str, Any] = {
                "entry_row_index": entry.row_index,
                "proposal": entry.proposal,
                "sampleid": entry.sampleid,
                "sampos": entry.sampos,
                "ymd": entry.ymd,
                "batchnum": entry.batchnum,
                "config_id": cfg,
                "repeat_index": r,
                "sampleposition": dict(entry.positions),
            }
            if exposure_time is not None:
                kwargs["sample_exposure_time"] = exposure_time
            specs.append(
                PlanSpec(
                    name="measure_yzstage",
                    kwargs=kwargs,
                    meta={"sample_key": sample_key, "config_id": cfg, "step": step, "repeat": r},
                )
            )
    return CompiledEntry(collate=collate, specs=tuple(specs))


def build_default_registry() -> ProtocolRegistry:
    """Create the default protocol registry used by CLI and tests."""
    reg = ProtocolRegistry()
    reg.register(
        ProtocolSpec(
            name="measure_once",
            compile=compile_single_plan_protocol(plan_name="measure_yzstage", default_collate=CollatePolicy.FORBID),
        )
    )
    reg.register(ProtocolSpec(name="standard_measurements", compile=compile_standard_measurements))
    return reg
