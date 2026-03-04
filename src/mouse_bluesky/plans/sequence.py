from __future__ import annotations

from pathlib import Path


def allocate_sequence_dir(*, root: Path, ymd: str, batchnum: int) -> tuple[int, Path]:
    """
    Atomically allocate a unique directory for this measurement using mkdir().
    Creates: root/YYYY/YMD/{YMD}_{batchnum:03d}_{sequence_index}/

    Returns:
        (sequence_index, destination_path)
    """
    base = root / ymd[:4] / ymd
    base.mkdir(parents=True, exist_ok=True)

    prefix = f"{ymd}_{batchnum:03d}_"
    for seq in range(0, 1_000_000_000):  # brute force, but should be fast enough since mkdir is atomic and we expect few collisions
        dest = base / f"{prefix}{seq}"
        try:
            dest.mkdir()
        except FileExistsError:
            continue
        return seq, dest

    raise RuntimeError("Sequence index exhausted (unexpected).")
