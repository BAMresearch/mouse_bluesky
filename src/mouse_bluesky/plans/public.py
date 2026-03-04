from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, Mapping

from bluesky import plan_stubs as bps

from .atomic import measure_yzstage_atomic
from .sequence import allocate_sequence_dir
from .snapshot import snapshot_state


def measure_yzstage(
    *,
    entry_row_index: int,
    proposal: str,
    sampleid: int,
    sampos: str,
    ymd: str,
    batchnum: int,
    config_id: int,
    repeat_index: int = 0,
    root_path: str | Path,
    md: Mapping[str, Any] | None = None,
    # devices:
    eiger=None,
    sample_stage=None,
    beam_stop=None,
    shutter=None,
    snapshot_signals=(),
    sampleposition: dict[str, float] | None = None,
) -> Iterator:
    """Open one run, capture metadata/snapshot, and execute the atomic measurement."""
    root = Path(root_path)
    if sampleposition is None:
        sampleposition = {}

    sequence_index, destination = allocate_sequence_dir(root=root, ymd=ymd, batchnum=batchnum)

    run_md = dict(md or {})
    run_md.update(
        {
            "entry_row_index": entry_row_index,
            "proposal": proposal,
            "sampleid": sampleid,
            "sampos": sampos,
            "ymd": ymd,
            "batchnum": batchnum,
            "config_id": int(config_id),
            "repeat_index": int(repeat_index),
            "sequence_index": int(sequence_index),
            "destination": destination.as_posix(),
        }
    )

    yield from bps.open_run(md=run_md)
    try:
        # Baseline should be configured on the RunEngine via SupplementalData.
        # Snapshot stream just before acquisition:
        if snapshot_signals:
            yield from snapshot_state(snapshot_signals, stream_name="snapshot")

        yield from measure_yzstage_atomic(
            eiger=eiger,
            sample_stage=sample_stage,
            beam_stop=beam_stop,
            shutter=shutter,
            sampleposition=sampleposition,
            destination=destination,
        )

        # Optional: mark success
        (destination / "COMPLETE").write_text("ok\n", encoding="utf-8")
    finally:
        yield from bps.close_run()
