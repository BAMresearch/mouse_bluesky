from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import h5py

from .models import PlanSpec


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    kind: str
    message: str
    context: Mapping[str, Any] | None = None


def validate_specs(
    specs: Sequence[PlanSpec],
    *,
    known_plans: set[str] | None = None,
    config_root: str | Path | None = None,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    if known_plans is not None:
        for i, s in enumerate(specs):
            if s.name not in known_plans:
                issues.append(
                    ValidationIssue(
                        "unknown_plan",
                        f"Unknown plan name: {s.name}",
                        {"index": i, "name": s.name},
                    )
                )

    # Validate measure_yzstage required args (superficial)
    for i, s in enumerate(specs):
        if s.name != "measure_yzstage":
            continue
        for k in ("root_path", "ymd", "batchnum", "config_id", "entry_row_index"):
            if k not in s.kwargs:
                issues.append(
                    ValidationIssue(
                        "missing_measurement_kwarg",
                        f"measure_yzstage missing kwarg '{k}'",
                        {"index": i, "entry_row_index": s.kwargs.get("entry_row_index")},
                    )
                )

    # Validate config files used by apply_config (or by measure_yzstage)
    if config_root is not None:
        root = Path(config_root)
        cfg_ids: set[int] = set()

        for s in specs:
            if "config_id" in s.kwargs:
                try:
                    cfg_ids.add(int(s.kwargs["config_id"]))
                except Exception:
                    issues.append(
                        ValidationIssue("bad_config_id", f"Non-integer config_id: {s.kwargs['config_id']!r}", {"plan": s.name})
                    )

        for cfg in sorted(cfg_ids):
            issues.extend(_validate_config_nxs(root=root, config_id=cfg))

    return issues


def _validate_config_nxs(*, root: Path, config_id: int) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    path = root / f"{config_id}.nxs"
    if not path.exists():
        return [ValidationIssue("missing_config_file", f"Missing config file: {path}", {"config_id": config_id})]

    grp_path = "/saxs/Saxslab"
    try:
        with h5py.File(path, "r") as f:
            if grp_path not in f:
                return [ValidationIssue("missing_group", f"Missing HDF5 group: {grp_path}", {"file": str(path)})]
            grp = f[grp_path]
            keys = list(grp.keys())
            if not keys:
                return [ValidationIssue("empty_group", f"No datasets under {grp_path}", {"file": str(path)})]

            for name in keys[:500]:
                ds = grp[name]
                if getattr(ds, "shape", None) != ():
                    issues.append(
                        ValidationIssue(
                            "non_scalar_dataset",
                            f"Dataset {grp_path}/{name} is not scalar",
                            {"file": str(path), "dataset": f"{grp_path}/{name}"},
                        )
                    )
    except OSError as e:
        issues.append(ValidationIssue("hdf5_open_failed", f"Could not open {path}: {e}", {"file": str(path)}))

    return issues
