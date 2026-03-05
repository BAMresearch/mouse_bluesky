from __future__ import annotations

from collections.abc import Iterator

from bluesky import plan_stubs as bps


def apply_config(*, config_id: int, config_root: str, settle_s: float = 0.0) -> Iterator:
    """Apply a machine configuration from `{config_root}/{config_id}.nxs`.

    TODO: implement:
    - open nxs
    - read scalar datasets under /saxs/Saxslab/*
    - map dataset names -> ophyd signals
    - sequence bps.mv safely (glever grouping to avoid overloading motor power supplies)
    """
    _ = (config_id, config_root)
    if settle_s:
        yield from bps.sleep(float(settle_s))
