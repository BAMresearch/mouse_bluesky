from __future__ import annotations

from pathlib import Path

from mouse_bluesky.plans.sequence import allocate_sequence_dir


def test_allocate_sequence_dir_touches_daily_keep_file(tmp_path: Path) -> None:
    _, destination = allocate_sequence_dir(root=tmp_path, ymd="20260506", batchnum=3)

    daily_dir = tmp_path / "2026" / "20260506"
    assert destination.parent == daily_dir
    assert (daily_dir / ".keep").exists()
