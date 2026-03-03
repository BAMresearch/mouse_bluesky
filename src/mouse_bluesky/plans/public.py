from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Mapping

from bluesky import plan_stubs as bps

from .atomic import measure_yzstage_atomic
from .snapshot import snapshot_state


def measure_yzstage(
    *,
    entry_row_index: int,
    config_id: int,
    repeat_index: int = 0,
    md: Mapping[str, Any] | None = None,
    eiger=None,
    sample_stage=None,
    beam_stop=None,
    shutter=None,
    snapshot_signals=(),
) -> Iterator:
    run_md = dict(md or {})
    run_md.update({"entry_row_index": entry_row_index, "config_id": int(config_id), "repeat_index": int(repeat_index)})

    yield from bps.open_run(md=run_md)
    try:
        yield from snapshot_state(snapshot_signals, stream_name="snapshot")
        yield from measure_yzstage_atomic(
            eiger=eiger, sample_stage=sample_stage, beam_stop=beam_stop, shutter=shutter, entry=None
        )
    finally:
        yield from bps.close_run()
