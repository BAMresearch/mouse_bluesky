from __future__ import annotations

from collections.abc import Iterable

from .models import CollatePolicy, CompiledEntry, PlanSpec


def _collate_block(specs: list[PlanSpec]) -> list[PlanSpec]:
    """Collate within one contiguous ALLOW block by config_id then sample_key."""
    def key(s: PlanSpec) -> tuple:
        m = dict(s.meta)
        return (m.get("config_id", -1), m.get("sample_key", ""), m.get("step", 0), m.get("repeat", 0))

    return sorted(specs, key=key)


def schedule(compiled_entries: Iterable[CompiledEntry]) -> list[PlanSpec]:
    """Barrier-aware scheduling.

    - `FORBID` entries are barriers and preserve order.
    - `ALLOW` entries are collated only within their contiguous ALLOW block.
    """
    out: list[PlanSpec] = []
    buf: list[PlanSpec] = []

    def flush() -> None:
        nonlocal buf
        if buf:
            out.extend(_collate_block(buf))
            buf = []

    for ce in compiled_entries:
        if ce.collate == CollatePolicy.ALLOW:
            buf.extend(list(ce.specs))
        else:
            flush()
            out.extend(list(ce.specs))

    flush()
    return out
